"""Statistics checked against hand-computed values, not against themselves."""
from __future__ import annotations

import math
import unittest

from cavbench.statistics import (agreement_report, cluster_bootstrap, cohens_kappa,
                                 krippendorff_alpha_nominal, mcnemar_exact,
                                 paired_compare, percentile, wilson_ci)


class TestWilson(unittest.TestCase):
    def test_known_value(self):
        lo, hi = wilson_ci(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)

    def test_symmetry_about_half(self):
        lo, hi = wilson_ci(5, 10)
        self.assertAlmostEqual(lo + hi, 1.0, places=9)

    def test_zero_successes_has_zero_lower_bound(self):
        lo, hi = wilson_ci(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)

    def test_all_successes_has_unit_upper_bound(self):
        lo, hi = wilson_ci(10, 10)
        self.assertEqual(hi, 1.0)
        self.assertLess(lo, 1.0)

    def test_empty_sample_is_maximally_uncertain(self):
        self.assertEqual(wilson_ci(0, 0), (0.0, 1.0))

    def test_interval_narrows_with_n(self):
        w_small = wilson_ci(5, 10)
        w_big = wilson_ci(500, 1000)
        self.assertLess(w_big[1] - w_big[0], w_small[1] - w_small[0])


class TestMcNemar(unittest.TestCase):
    def test_no_discordant_pairs(self):
        self.assertEqual(mcnemar_exact(0, 0), 1.0)

    def test_fully_one_sided(self):
        self.assertAlmostEqual(mcnemar_exact(10, 0), 2 * 0.5 ** 10, places=12)

    def test_balanced_is_not_significant(self):
        self.assertEqual(mcnemar_exact(5, 5), 1.0)

    def test_symmetric_in_arguments(self):
        self.assertAlmostEqual(mcnemar_exact(7, 2), mcnemar_exact(2, 7), places=12)

    def test_never_exceeds_one(self):
        for b in range(6):
            for c in range(6):
                self.assertLessEqual(mcnemar_exact(b, c), 1.0)

    def test_more_evidence_lowers_p(self):
        self.assertLess(mcnemar_exact(12, 1), mcnemar_exact(4, 1))


class TestPairedCompare(unittest.TestCase):
    def test_counts_and_direction(self):
        a = {"s1": True, "s2": True, "s3": False, "s4": False}
        b = {"s1": True, "s2": False, "s3": True, "s4": False}
        out = paired_compare(a, b)
        self.assertEqual(out["n_paired"], 4)
        self.assertEqual(out["both_correct"], 1)
        self.assertEqual(out["neither_correct"], 1)
        self.assertEqual(out["a_only_correct"], 1)
        self.assertEqual(out["b_only_correct"], 1)
        self.assertEqual(out["p_value"], 1.0)

    def test_only_shared_ids_are_compared(self):
        out = paired_compare({"s1": True, "extra": True}, {"s1": False})
        self.assertEqual(out["n_paired"], 1)


class TestAgreement(unittest.TestCase):
    def test_kappa_perfect_and_inverted(self):
        self.assertAlmostEqual(cohens_kappa(["x", "y", "x"], ["x", "y", "x"]), 1.0)
        self.assertAlmostEqual(cohens_kappa(["x", "x", "y", "y"], ["y", "y", "x", "x"]), -1.0)

    def test_kappa_rejects_mismatched_lengths(self):
        with self.assertRaises(ValueError):
            cohens_kappa(["a"], ["a", "b"])

    def test_kappa_undefined_when_both_raters_constant(self):
        self.assertTrue(math.isnan(cohens_kappa(["a", "a"], ["a", "a"])))

    def test_alpha_unanimous_is_one(self):
        units = [["a", "a"], ["b", "b"], ["a", "a"], ["b", "b"]]
        self.assertAlmostEqual(krippendorff_alpha_nominal(units), 1.0, places=9)

    def test_alpha_systematic_disagreement_is_negative(self):
        units = [["a", "b"], ["a", "b"], ["b", "a"], ["b", "a"]]
        self.assertLess(krippendorff_alpha_nominal(units), 0.0)

    def test_alpha_ignores_units_with_one_rating(self):
        self.assertTrue(math.isnan(krippendorff_alpha_nominal([["a"], ["b"]])))

    def test_alpha_handles_variable_rater_counts(self):
        units = [["a", "a", "a"], ["b", "b"], ["a", "a"]]
        self.assertAlmostEqual(krippendorff_alpha_nominal(units), 1.0, places=9)

    def test_agreement_report_shape(self):
        rep = agreement_report({
            "j1": {"s1": "A", "s2": "B"},
            "j2": {"s1": "A", "s2": "B"},
        })
        self.assertEqual(rep["n_items"], 2)
        self.assertIn("j1 vs j2", rep["cohens_kappa"])


class TestPercentile(unittest.TestCase):
    def test_median(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], 0.5), 3)

    def test_bounds(self):
        self.assertEqual(percentile([1, 2, 3], 0.0), 1)
        self.assertEqual(percentile([1, 2, 3], 1.0), 3)

    def test_interpolates(self):
        self.assertAlmostEqual(percentile([0, 10], 0.25), 2.5)

    def test_empty_is_nan(self):
        self.assertTrue(math.isnan(percentile([], 0.5)))


class TestClusterBootstrap(unittest.TestCase):
    def setUp(self):
        # two clusters, perfectly correlated within cluster
        self.items = ([{"base_task_id": "T01", "hit": True}] * 5 +
                      [{"base_task_id": "T02", "hit": False}] * 5)
        self.stat = lambda rows: (sum(r["hit"] for r in rows) / len(rows)) if rows else None

    def test_point_estimate(self):
        out = cluster_bootstrap(self.items, self.stat, n_boot=200, seed=1)
        self.assertAlmostEqual(out["point"], 0.5)
        self.assertEqual(out["n_clusters"], 2)

    def test_deterministic_for_a_seed(self):
        a = cluster_bootstrap(self.items, self.stat, n_boot=200, seed=7)
        b = cluster_bootstrap(self.items, self.stat, n_boot=200, seed=7)
        self.assertEqual(a, b)

    def test_resamples_clusters_not_rows(self):
        """With two fully-correlated clusters the only reachable values are
        0.0, 0.5 and 1.0. Row-level resampling would produce intermediate
        values and a falsely narrow interval."""
        out = cluster_bootstrap(self.items, self.stat, n_boot=400, seed=3)
        self.assertEqual(out["lo"], 0.0)
        self.assertEqual(out["hi"], 1.0)

    def test_handles_empty_input(self):
        out = cluster_bootstrap([], self.stat, n_boot=10)
        self.assertEqual(out["n_clusters"], 0)
        self.assertTrue(math.isnan(out["lo"]))

    def test_skips_undefined_resamples(self):
        items = [{"base_task_id": "T01", "hit": True}]
        out = cluster_bootstrap(items, lambda rows: None, n_boot=50)
        self.assertEqual(out["n_boot_used"], 0)


if __name__ == "__main__":
    unittest.main()
