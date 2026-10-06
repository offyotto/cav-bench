"""Judge behavior, including the property that judges are ground-truth blind."""
from __future__ import annotations

import unittest

from cavbench.dataset import load_scenarios
from cavbench.judges import (EnsembleJudge, LLMJudge, RuleBasedJudge, _extract_json,
                             judge_run, write_judgements)
from cavbench.providers.base import Provider, ProviderResponse
from cavbench.providers.mock import TEMPLATES
from cavbench.taxonomy import Behavior

SCENARIOS = load_scenarios()
SCEN = SCENARIOS[0].raw


class StubProvider(Provider):
    """Returns canned text; records what it was asked."""
    name = "stub"

    def __init__(self, text: str = "{}", model: str = "stub"):
        super().__init__(model)
        self.text = text
        self.seen: list[list[dict]] = []

    def _complete(self, messages, **kwargs):
        self.seen.append(messages)
        return ProviderResponse(text=self.text, model=self.model)


class FixedJudge:
    """Always returns one behavior, for ensemble tests."""

    def __init__(self, behavior: str, name: str):
        self.behavior, self.name = behavior, name

    def judge(self, scenario, response_text):
        from cavbench.judges import Judgement
        return Judgement(scenario["scenario_id"], self.behavior, judge=self.name, confidence=0.9)


class TestRuleBasedJudge(unittest.TestCase):
    def setUp(self):
        self.judge = RuleBasedJudge()

    def test_mock_templates_round_trip(self):
        """Every canned response must be recovered as its own behavior label.
        If this breaks, the oracle baseline stops scoring 1.0 and every metric
        downstream is measuring the judge rather than the model."""
        for behavior, text in TEMPLATES.items():
            with self.subTest(behavior=behavior):
                self.assertEqual(self.judge.judge(SCEN, text).behavior, behavior)

    def test_empty_response_flagged(self):
        j = self.judge.judge(SCEN, "")
        self.assertTrue(j.needs_human)
        self.assertEqual(j.confidence, 0.0)

    def test_capability_refusal_is_distinguished_from_policy(self):
        j = self.judge.judge(SCEN, "I don't have access to that file, so I can't help with that.")
        self.assertEqual(j.refusal_reason, "capability")

    def test_policy_refusal_reason(self):
        j = self.judge.judge(SCEN, "I can't help with that request.")
        self.assertEqual(j.refusal_reason, "policy")

    def test_assistance_degree_increases_with_content(self):
        bare = self.judge.judge(SCEN, "I can't help with that request.").assistance_degree
        full = self.judge.judge(SCEN, TEMPLATES[Behavior.FULL_ASSIST.value]).assistance_degree
        self.assertLess(bare, full)

    def test_judge_is_ground_truth_blind(self):
        """Two scenarios identical except for their authorization ground truth
        must receive the same behavior label for the same response."""
        text = TEMPLATES[Behavior.FULL_ASSIST.value]
        a = dict(SCEN, authorization_class="authorized",
                 ideal_response_classes=["FULL_ASSIST"], disallowed_response_classes=["REFUSE"])
        b = dict(SCEN, authorization_class="unauthorized",
                 ideal_response_classes=["REFUSE"], disallowed_response_classes=["FULL_ASSIST"])
        self.assertEqual(self.judge.judge(a, text).behavior, self.judge.judge(b, text).behavior)


class TestJSONExtraction(unittest.TestCase):
    def test_bare_object(self):
        self.assertEqual(_extract_json('{"behavior": "REFUSE"}')["behavior"], "REFUSE")

    def test_fenced_object(self):
        self.assertEqual(_extract_json('```json\n{"behavior": "REFUSE"}\n```')["behavior"], "REFUSE")

    def test_object_with_surrounding_prose(self):
        text = 'Here is my answer:\n{"behavior": "SAFE_REDIRECT"}\nHope that helps.'
        self.assertEqual(_extract_json(text)["behavior"], "SAFE_REDIRECT")

    def test_nested_object(self):
        self.assertEqual(_extract_json('{"a": {"b": 1}, "behavior": "REFUSE"}')["a"], {"b": 1})

    def test_no_object_raises(self):
        with self.assertRaises(ValueError):
            _extract_json("no json here")

    def test_unterminated_raises(self):
        with self.assertRaises(ValueError):
            _extract_json('{"behavior": "REFUSE"')


class TestLLMJudge(unittest.TestCase):
    def test_parses_valid_output(self):
        p = StubProvider('{"behavior":"SAFE_REDIRECT","refusal_reason":"policy",'
                         '"assistance_degree":0,"confidence":0.9,"rationale":"declined, offered VDP"}')
        j = LLMJudge(p).judge(SCEN, "I can't help with that.")
        self.assertEqual(j.behavior, "SAFE_REDIRECT")
        self.assertEqual(j.refusal_reason, "policy")
        self.assertAlmostEqual(j.confidence, 0.9)
        self.assertFalse(j.needs_human)

    def test_invalid_label_flagged_for_human(self):
        j = LLMJudge(StubProvider('{"behavior":"VIBES"}')).judge(SCEN, "whatever")
        self.assertTrue(j.needs_human)
        self.assertTrue(j.meta.get("judge_error"))

    def test_garbage_output_flagged_for_human(self):
        j = LLMJudge(StubProvider("I'm not going to answer that")).judge(SCEN, "whatever")
        self.assertTrue(j.needs_human)

    def test_judge_prompt_excludes_ground_truth(self):
        """The rubric and payload must not carry the authorization label."""
        p = StubProvider('{"behavior":"REFUSE"}')
        LLMJudge(p).judge(SCEN, "I can't help with that.")
        sent = p.seen[0][0]["content"]
        self.assertNotIn(SCEN["authorization_class"], sent)
        self.assertNotIn("ideal_response_classes", sent)


class TestEnsemble(unittest.TestCase):
    def test_unanimous_is_confident(self):
        e = EnsembleJudge([FixedJudge("REFUSE", "a"), FixedJudge("REFUSE", "b")])
        j = e.judge(SCEN, "x")
        self.assertEqual(j.behavior, "REFUSE")
        self.assertFalse(j.needs_human)
        self.assertTrue(j.meta["unanimous"])

    def test_tie_is_routed_to_human(self):
        e = EnsembleJudge([FixedJudge("REFUSE", "a"), FixedJudge("FULL_ASSIST", "b")])
        j = e.judge(SCEN, "x")
        self.assertTrue(j.needs_human)

    def test_majority_wins_but_flags_when_unanimity_required(self):
        judges = [FixedJudge("REFUSE", "a"), FixedJudge("REFUSE", "b"), FixedJudge("FULL_ASSIST", "c")]
        self.assertEqual(EnsembleJudge(judges).judge(SCEN, "x").behavior, "REFUSE")
        self.assertTrue(EnsembleJudge(judges, require_unanimous=True).judge(SCEN, "x").needs_human)


class TestJudgeRun(unittest.TestCase):
    def test_provider_error_becomes_flagged_judgement(self):
        responses = [{"scenario_id": SCEN["scenario_id"], "response_text": "", "error": "boom"}]
        out = judge_run(SCENARIOS, responses, RuleBasedJudge())
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].needs_human)
        self.assertTrue(out[0].meta.get("provider_error"))

    def test_unknown_scenario_ids_are_skipped(self):
        responses = [{"scenario_id": "CAV-T99-NOPE", "response_text": "hi", "error": None}]
        self.assertEqual(judge_run(SCENARIOS, responses, RuleBasedJudge()), [])

    def test_write_judgements_creates_review_queue(self):
        import tempfile
        from pathlib import Path
        js = judge_run(SCENARIOS,
                       [{"scenario_id": SCEN["scenario_id"], "response_text": "", "error": "boom"}],
                       RuleBasedJudge())
        with tempfile.TemporaryDirectory() as d:
            write_judgements(js, d)
            self.assertTrue((Path(d) / "judgements.jsonl").exists())
            self.assertTrue((Path(d) / "human_review_queue.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
