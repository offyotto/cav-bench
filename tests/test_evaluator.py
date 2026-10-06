"""Evaluator: retries, resume, error recording, and run provenance."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cavbench.dataset import load_scenarios
from cavbench.evaluator import (EvalConfig, dataset_digest, load_responses,
                                run_evaluation)
from cavbench.providers.base import Provider, ProviderError, ProviderResponse

SCENARIOS = load_scenarios()
SMALL = SCENARIOS[:3]
FAST = dict(backoff_base_s=0.0, backoff_cap_s=0.0, progress=False)


class FlakyProvider(Provider):
    """Fails `fail_times` times per call site, then succeeds."""
    name = "flaky"

    def __init__(self, fail_times: int = 2):
        super().__init__("flaky-model")
        self.fail_times = fail_times
        self.calls = 0

    def _complete(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("transient upstream failure")
        return ProviderResponse(text="ok", model=self.model)


class AlwaysFailProvider(Provider):
    name = "always_fail"

    def __init__(self):
        super().__init__("doomed")

    def _complete(self, messages, **kwargs):
        raise ProviderError("permanent failure")


def mock_provider(policy: str = "oracle"):
    from cavbench.providers import build_provider
    return build_provider({"provider": "mock", "model": "mock", "policy": policy})


class TestRun(unittest.TestCase):
    def test_writes_one_record_per_scenario(self):
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SMALL, mock_provider(), EvalConfig(output_dir=d, **FAST))
            rows = load_responses(d)
            self.assertEqual(len(rows), len(SMALL))
            self.assertEqual({r["scenario_id"] for r in rows},
                             {s.raw["scenario_id"] for s in SMALL})

    def test_writes_run_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SMALL, mock_provider(), EvalConfig(output_dir=d, **FAST))
            meta = json.loads((Path(d) / "run_metadata.json").read_text())
            self.assertEqual(meta["n_scenarios_total"], len(SMALL))
            self.assertEqual(meta["n_errors"], 0)
            self.assertIn("dataset_digest_sha256", meta)
            self.assertEqual(meta["provider"]["provider"], "mock")

    def test_metadata_never_contains_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SMALL, mock_provider(), EvalConfig(output_dir=d, **FAST))
            text = (Path(d) / "run_metadata.json").read_text().lower()
            for banned in ("api_key", "sk-", "bearer", "authorization:"):
                self.assertNotIn(banned, text.replace("api_key_env", ""))

    def test_mock_receives_scenario_metadata(self):
        """The oracle policy can only work if the evaluator passes the scenario."""
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SMALL, mock_provider("oracle"), EvalConfig(output_dir=d, **FAST))
            self.assertTrue(all(r["error"] is None for r in load_responses(d)))


class TestResume(unittest.TestCase):
    def test_second_run_skips_completed(self):
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SMALL, mock_provider(), EvalConfig(output_dir=d, **FAST))
            run_evaluation(SMALL, mock_provider(), EvalConfig(output_dir=d, **FAST))
            meta = json.loads((Path(d) / "run_metadata.json").read_text())
            self.assertEqual(meta["n_evaluated_this_run"], 0)
            self.assertEqual(meta["n_skipped_resumed"], len(SMALL))
            self.assertEqual(len(load_responses(d)), len(SMALL))

    def test_overwrite_reruns_everything(self):
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SMALL, mock_provider(), EvalConfig(output_dir=d, **FAST))
            run_evaluation(SMALL, mock_provider(), EvalConfig(output_dir=d, overwrite=True, **FAST))
            meta = json.loads((Path(d) / "run_metadata.json").read_text())
            self.assertEqual(meta["n_evaluated_this_run"], len(SMALL))
            self.assertEqual(len(load_responses(d)), len(SMALL))

    def test_failed_scenarios_are_retried_on_resume(self):
        """Errored records must not count as done, or a flaky run silently
        ships with holes in it."""
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SMALL, AlwaysFailProvider(),
                           EvalConfig(output_dir=d, max_retries=1, **FAST))
            run_evaluation(SMALL, mock_provider(), EvalConfig(output_dir=d, **FAST))
            meta = json.loads((Path(d) / "run_metadata.json").read_text())
            self.assertEqual(meta["n_evaluated_this_run"], len(SMALL))


class TestRetry(unittest.TestCase):
    def test_retries_then_succeeds(self):
        p = FlakyProvider(fail_times=2)
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SCENARIOS[:1], p, EvalConfig(output_dir=d, max_retries=4, **FAST))
            rec = load_responses(d)[0]
            self.assertIsNone(rec["error"])
            self.assertEqual(rec["attempts"], 3)

    def test_gives_up_after_max_retries_and_records_error(self):
        with tempfile.TemporaryDirectory() as d:
            run_evaluation(SCENARIOS[:1], AlwaysFailProvider(),
                           EvalConfig(output_dir=d, max_retries=2, **FAST))
            rec = load_responses(d)[0]
            self.assertIsNotNone(rec["error"])
            self.assertIn("permanent failure", rec["error"])
            self.assertEqual(rec["attempts"], 2)

    def test_stop_on_error_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ProviderError):
                run_evaluation(SCENARIOS[:1], AlwaysFailProvider(),
                               EvalConfig(output_dir=d, max_retries=1,
                                          stop_on_error=True, **FAST))


class TestDigest(unittest.TestCase):
    def test_stable_and_order_independent(self):
        self.assertEqual(dataset_digest(SCENARIOS), dataset_digest(list(reversed(SCENARIOS))))

    def test_changes_when_a_prompt_changes(self):
        import copy
        before = dataset_digest(SCENARIOS)
        mutated = copy.deepcopy(SCENARIOS)
        mutated[0].raw["prompt"] += " (edited)"
        self.assertNotEqual(before, dataset_digest(mutated))


if __name__ == "__main__":
    unittest.main()
