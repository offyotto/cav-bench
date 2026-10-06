"""Dataset, schema and taxonomy invariants.

These tests run against the real shipped dataset, not fixtures. If a scenario
is edited in a way that breaks a matched set or leaks a keyword into a single
class, this suite fails.
"""
from __future__ import annotations

import re
import unittest
from collections import defaultdict

from cavbench.dataset import (AUTH_KEYWORDS, INTENSITY_MARKERS, _wc,
                              check_integrity, keyword_leakage, load_scenarios)
from cavbench.schema import load_schema, validate
from cavbench.taxonomy import (COMPLY, DECLINE, Behavior, DEFAULT_EXPECTATIONS,
                               STRENGTH_ORDER, complies, declines)

SCENARIOS = load_scenarios()


class TestShippedDataset(unittest.TestCase):
    def test_loads_and_validates(self):
        rep = check_integrity(SCENARIOS)
        self.assertTrue(rep.ok, msg="integrity errors: " + "; ".join(rep.errors))
        self.assertEqual(rep.warnings, [], msg="integrity warnings: " + "; ".join(rep.warnings))

    def test_expected_shape(self):
        self.assertEqual(len(SCENARIOS), 30)
        rep = check_integrity(SCENARIOS)
        self.assertEqual(rep.diagnostics["n_core_triplets"], 10)
        self.assertEqual(rep.diagnostics["by_class"],
                         {"authorized": 10, "ambiguous": 10, "unauthorized": 10})

    def test_unique_ids(self):
        ids = [s.raw["scenario_id"] for s in SCENARIOS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_triplets_hold_technical_content_constant(self):
        groups = defaultdict(list)
        for s in SCENARIOS:
            groups[s.raw["base_task_id"]].append(s.raw)
        for tid, g in groups.items():
            with self.subTest(task=tid):
                self.assertEqual(len(g), 3)
                self.assertEqual(sorted(x["authorization_class"] for x in g),
                                 ["ambiguous", "authorized", "unauthorized"])
                for field in ("task_family", "technical_goal", "requested_artifact"):
                    self.assertEqual(len({x[field] for x in g}), 1,
                                     f"{tid}: {field} varies across the triplet")

    def test_triplet_length_balance(self):
        groups = defaultdict(list)
        for s in SCENARIOS:
            groups[s.raw["base_task_id"]].append(_wc(s.full_text()))
        for tid, lens in groups.items():
            with self.subTest(task=tid):
                spread = (max(lens) - min(lens)) / max(lens)
                self.assertLess(spread, 0.35, f"{tid}: word-count spread {spread:.0%}")

    def test_no_intensity_marker_splits_a_triplet(self):
        groups = defaultdict(list)
        for s in SCENARIOS:
            groups[s.raw["base_task_id"]].append(s.full_text().lower())
        for tid, texts in groups.items():
            for marker in INTENSITY_MARKERS:
                present = [marker in t for t in texts]
                with self.subTest(task=tid, marker=marker):
                    self.assertIn(len(set(present)), (1,),
                                  f"{tid}: intensity marker {marker!r} in only some variants")

    def test_no_keyword_confined_to_one_class(self):
        """The property that stops a bag-of-words baseline from scoring."""
        for kw, row in keyword_leakage(SCENARIOS).items():
            present = [c for c, n in row.items() if n]
            with self.subTest(keyword=kw):
                if sum(row.values()) >= 3:
                    self.assertGreater(len(present), 1,
                                       f"{kw!r} appears only in class {present}")

    def test_authorization_ground_truth_rules(self):
        for s in SCENARIOS:
            r = s.raw
            with self.subTest(scenario=r["scenario_id"]):
                if r["authorization_class"] == "authorized":
                    self.assertGreaterEqual(STRENGTH_ORDER[r["authorization_strength"]],
                                            STRENGTH_ORDER["L2"])
                if r["authorization_class"] == "unauthorized":
                    self.assertTrue(any(e["polarity"] == "contradicts"
                                        for e in r["authorization_evidence"]))
                if r["theater"]:
                    self.assertNotEqual(r["authorization_claim"], "none")
                    self.assertNotEqual(r["authorization_class"], "authorized")

    def test_evidence_spans_are_verbatim(self):
        for s in SCENARIOS:
            text = s.full_text().lower()
            for ev in s.raw["authorization_evidence"]:
                with self.subTest(scenario=s.raw["scenario_id"], span=ev["span"]):
                    self.assertIn(ev["span"].lower(), text)

    def test_no_operational_payloads_declared(self):
        for s in SCENARIOS:
            with self.subTest(scenario=s.raw["scenario_id"]):
                self.assertTrue(s.raw["safety"]["synthetic_only"])
                self.assertFalse(s.raw["safety"]["contains_operational_payload"])

    def test_theater_variants_exist(self):
        theater = [s for s in SCENARIOS if s.raw["theater"]]
        self.assertGreaterEqual(len(theater), 3,
                                "theater condition is a core contribution; keep several")
        for s in theater:
            self.assertEqual(s.raw["authorization_class"], "unauthorized")


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
        self.valid = dict(SCENARIOS[0].raw)

    def test_valid_scenario_passes(self):
        self.assertEqual(validate(self.valid, self.schema), [])

    def test_missing_required_field_fails(self):
        bad = dict(self.valid)
        del bad["authorization_class"]
        self.assertTrue(validate(bad, self.schema))

    def test_bad_enum_fails(self):
        bad = dict(self.valid, authorization_class="definitely_fine")
        self.assertTrue(validate(bad, self.schema))

    def test_bad_id_pattern_fails(self):
        bad = dict(self.valid, scenario_id="not-a-cav-id")
        self.assertTrue(validate(bad, self.schema))

    def test_operational_payload_cannot_be_declared_true(self):
        """The schema is the enforcement point for the no-payload rule."""
        bad = dict(self.valid)
        bad["safety"] = dict(bad["safety"], contains_operational_payload=True)
        self.assertTrue(validate(bad, self.schema))

    def test_unknown_field_rejected(self):
        bad = dict(self.valid, surprise="hello")
        self.assertTrue(validate(bad, self.schema))


class TestTaxonomy(unittest.TestCase):
    def test_comply_decline_partition(self):
        middle = {Behavior.CLARIFY_AUTHORIZATION.value}
        self.assertEqual(COMPLY | DECLINE | middle, {b.value for b in Behavior})
        self.assertEqual(COMPLY & DECLINE, set())

    def test_complies_declines_helpers(self):
        self.assertTrue(complies(Behavior.FULL_ASSIST.value))
        self.assertTrue(complies(Behavior.CONDITIONAL_ASSIST.value))
        self.assertTrue(declines(Behavior.REFUSE.value))
        self.assertFalse(complies(Behavior.CLARIFY_AUTHORIZATION.value))
        self.assertFalse(declines(Behavior.CLARIFY_AUTHORIZATION.value))

    def test_expectations_are_internally_consistent(self):
        for cls, d in DEFAULT_EXPECTATIONS.items():
            ideal, acc, dis = set(d["ideal"]), set(d["acceptable"]), set(d["disallowed"])
            with self.subTest(cls=cls):
                self.assertEqual(ideal & dis, set())
                self.assertEqual(acc & dis, set())
                self.assertEqual(ideal & acc, set())
                self.assertTrue(ideal)

    def test_authorized_never_ideally_refused(self):
        self.assertNotIn(Behavior.REFUSE.value, DEFAULT_EXPECTATIONS["authorized"]["ideal"])
        self.assertIn(Behavior.REFUSE.value, DEFAULT_EXPECTATIONS["authorized"]["disallowed"])

    def test_unauthorized_never_ideally_assisted(self):
        for b in COMPLY:
            self.assertNotIn(b, DEFAULT_EXPECTATIONS["unauthorized"]["ideal"])
            self.assertIn(b, DEFAULT_EXPECTATIONS["unauthorized"]["disallowed"])


if __name__ == "__main__":
    unittest.main()
