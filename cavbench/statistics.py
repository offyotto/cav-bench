"""Statistics for CAV-Bench. Standard library only.

Two things here are not optional for this benchmark to be read honestly:

1. Triplets are not independent observations. Three scenarios share one
   underlying technical task, so confidence intervals must resample *base tasks*,
   not scenarios. `cluster_bootstrap` does that. Using a naive binomial interval
   over 30 scenarios would understate uncertainty.

2. Comparing two models on the same scenarios is a paired design, so use
   McNemar's exact test rather than a two-proportion z-test.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Callable, Iterable, Sequence


# --------------------------------------------------------------------------
# intervals
# --------------------------------------------------------------------------

def wilson_ci(successes: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    """Wilson score interval. Degrades gracefully at n=0 and at p=0 or 1."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 1]."""
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = q * (len(s) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return s[int(idx)]
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def cluster_bootstrap(items: Sequence[dict],
                      statistic: Callable[[Sequence[dict]], float | None],
                      cluster_key: Callable[[dict], str] = lambda r: r["base_task_id"],
                      n_boot: int = 2000, seed: int = 0,
                      alpha: float = 0.05) -> dict:
    """Percentile bootstrap resampling whole clusters with replacement.

    Returns point estimate, CI bounds, and how many resamples were usable
    (a resample can be undefined, e.g. no authorized scenarios drawn).
    """
    point = statistic(items)
    clusters: dict[str, list[dict]] = defaultdict(list)
    for r in items:
        clusters[cluster_key(r)].append(r)
    keys = list(clusters)
    if not keys:
        return {"point": point, "lo": float("nan"), "hi": float("nan"),
                "n_boot_used": 0, "n_clusters": 0}

    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(n_boot):
        drawn: list[dict] = []
        for _ in range(len(keys)):
            drawn.extend(clusters[keys[rng.randrange(len(keys))]])
        v = statistic(drawn)
        if v is not None and not math.isnan(v):
            stats.append(v)

    if not stats:
        return {"point": point, "lo": float("nan"), "hi": float("nan"),
                "n_boot_used": 0, "n_clusters": len(keys)}
    return {
        "point": point,
        "lo": percentile(stats, alpha / 2),
        "hi": percentile(stats, 1 - alpha / 2),
        "n_boot_used": len(stats),
        "n_clusters": len(keys),
    }


# --------------------------------------------------------------------------
# paired comparison
# --------------------------------------------------------------------------

def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts.

    b = cases where A succeeded and B failed; c = the reverse. Concordant pairs
    carry no information and are not used.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2 * tail)


def paired_compare(a_correct: dict[str, bool], b_correct: dict[str, bool]) -> dict:
    """Compare two models over the scenario ids present in both."""
    shared = sorted(set(a_correct) & set(b_correct))
    b_only = sum(1 for s in shared if a_correct[s] and not b_correct[s])
    c_only = sum(1 for s in shared if b_correct[s] and not a_correct[s])
    both = sum(1 for s in shared if a_correct[s] and b_correct[s])
    neither = len(shared) - both - b_only - c_only
    return {
        "n_paired": len(shared),
        "both_correct": both, "neither_correct": neither,
        "a_only_correct": b_only, "b_only_correct": c_only,
        "p_value": mcnemar_exact(b_only, c_only),
    }


# --------------------------------------------------------------------------
# inter-rater agreement
# --------------------------------------------------------------------------

def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa for two raters over the same items."""
    if len(a) != len(b):
        raise ValueError("rater label sequences must be the same length")
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    if pe == 1.0:
        return float("nan")
    return (po - pe) / (1 - pe)


def krippendorff_alpha_nominal(units: Iterable[Sequence[str]]) -> float:
    """Krippendorff's alpha for nominal data, any number of raters per unit.

    `units` is an iterable of per-unit label lists. Units with fewer than two
    labels carry no pairable information and are dropped.
    """
    usable = [list(u) for u in units if len(u) >= 2]
    if not usable:
        return float("nan")

    coincidence: dict[tuple[str, str], float] = defaultdict(float)
    for labels in usable:
        m = len(labels)
        counts = Counter(labels)
        for c in counts:
            for k in counts:
                delta = 1 if c == k else 0
                coincidence[(c, k)] += counts[c] * (counts[k] - delta) / (m - 1)

    cats = sorted({c for c, _ in coincidence})
    n_c = {c: sum(coincidence[(c, k)] for k in cats) for c in cats}
    n = sum(n_c.values())
    if n <= 1:
        return float("nan")

    do = sum(coincidence[(c, k)] for c in cats for k in cats if c != k) / n
    de = sum(n_c[c] * n_c[k] for c in cats for k in cats if c != k) / (n * (n - 1))
    if de == 0:
        return float("nan")
    return 1 - do / de


def agreement_report(judgements_by_judge: dict[str, dict[str, str]]) -> dict:
    """Pairwise kappa plus overall alpha. Input: judge -> {scenario_id: behavior}."""
    names = sorted(judgements_by_judge)
    shared = set.intersection(*(set(judgements_by_judge[n]) for n in names)) if names else set()
    shared = sorted(shared)

    pairwise = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pairwise[f"{a} vs {b}"] = cohens_kappa(
                [judgements_by_judge[a][s] for s in shared],
                [judgements_by_judge[b][s] for s in shared])

    units = [[judgements_by_judge[n][s] for n in names] for s in shared]
    return {
        "n_items": len(shared),
        "judges": names,
        "cohens_kappa": pairwise,
        "krippendorff_alpha": krippendorff_alpha_nominal(units),
    }
