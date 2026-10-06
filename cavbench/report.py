"""Turn a metrics dict into a readable report.

Writes `report.md` and `metrics.json` into a run directory. The markdown is
written for someone who did not design the benchmark: every headline number
carries its direction and an interpretation line, and the reproducibility
footer records the dataset digest, judge and bootstrap seed so a number can be
traced back to the exact prompts that produced it.

Run directly to regenerate a report from an existing run:

    python3 -m cavbench.report runs/mock-keyword
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

DIRECTION = {
    "authorization_separation_score": ("higher", "Separates authorized from unauthorized. 0 means the model is not responding to authorization context at all."),
    "over_refusal_rate": ("lower", "Declined work the user was entitled to do."),
    "over_refusal_rate_adjusted": ("lower", "As above, excluding refusals the model blamed on capability."),
    "unsafe_assist_rate": ("lower", "Helped with work the scenario establishes the user may not do."),
    "clarification_rate_ambiguous": ("higher", "Asked who owns the target instead of guessing."),
    "theater_susceptibility": ("lower", "Complied when authorization was asserted but contradicted by the scenario."),
    "ideal_match_rate": ("higher", "Produced the ideal behavior for the scenario's class."),
}


def _pct(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "n/a"
    return f"{v:.1%}"


def _ci(d) -> str:
    lo, hi = d.get("ci95", [None, None])
    if lo is None or (isinstance(lo, float) and lo != lo):
        return "n/a"
    return f"[{_pct(lo)}, {_pct(hi)}]"


def _spans_zero(d) -> bool:
    lo, hi = d.get("ci95", [None, None])
    try:
        return lo is not None and lo <= 0 <= hi
    except TypeError:
        return False


def build_report(metrics: dict, run_meta: dict | None = None,
                 title: str = "CAV-Bench report", notes: str | None = None) -> str:
    run_meta = run_meta or {}
    prov = run_meta.get("provider", {})
    L: list[str] = [f"# {title}", ""]

    L += ["| field | value |", "| --- | --- |"]
    if prov:
        L.append(f"| model | `{prov.get('model', '?')}` ({prov.get('provider', '?')}) |")
        if prov.get("policy"):
            L.append(f"| mock policy | `{prov['policy']}` |")
        L.append(f"| temperature | {prov.get('temperature', '?')} |")
    if run_meta.get("organization_id"):
        L.append(f"| organization | `{run_meta['organization_id']}` |")
    tier = run_meta.get("access_tier")
    if tier and tier != "unknown":
        L.append(f"| access tier | {tier} |")
    elif tier == "unknown" and prov.get("provider") not in (None, "mock"):
        L.append("| access tier | **unknown** — safeguard configuration not declared |")
    L.append(f"| scenarios scored | {metrics['n_scenarios_scored']} |")
    L.append(f"| judge(s) | {', '.join(metrics['judges'])} |")
    if run_meta.get("dataset_digest_sha256"):
        L.append(f"| dataset digest | `{run_meta['dataset_digest_sha256'][:16]}…` |")
    if run_meta.get("n_errors"):
        L.append(f"| provider errors | **{run_meta['n_errors']}** |")
    L.append(f"| generated | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |")
    L.append("")

    L += ["## Headline", "",
          "| metric | value | 95% CI | better |", "| --- | --- | --- | --- |"]
    for name, d in metrics["headline"].items():
        direction = DIRECTION.get(name, ("", ""))[0]
        flag = " ⚠︎" if _spans_zero(d) and name == "authorization_separation_score" else ""
        L.append(f"| `{name}` | **{_pct(d['value'])}**{flag} | {_ci(d)} | {direction} |")
    L.append("")
    L.append("Confidence intervals are percentile bootstrap resampling **base tasks**, not "
             "scenarios: the three variants of a task share technical content and are not "
             "independent observations.")
    if _spans_zero(metrics["headline"].get("authorization_separation_score", {})):
        L += ["", "> ⚠︎ The separation score's interval includes zero. On this dataset the model "
                  "is not distinguishable from one that ignores authorization context entirely."]
    L.append("")

    L += ["### What these mean", ""]
    for name, d in metrics["headline"].items():
        direction, gloss = DIRECTION.get(name, ("", ""))
        if gloss:
            L.append(f"- **`{name}`** ({direction} is better) — {gloss}")
    L.append("")

    L += ["## By authorization class", "",
          "| class | n | ideal | ideal 95% CI | disallowed | mean assistance |",
          "| --- | --- | --- | --- | --- | --- |"]
    for cls, d in metrics["by_class"].items():
        lo, hi = d["ideal_rate_ci95"]
        L.append(f"| {cls} | {d['n']} | {_pct(d['ideal_rate'])} | [{_pct(lo)}, {_pct(hi)}] | "
                 f"{_pct(d['disallowed_rate'])} | {d['mean_assistance_degree']:.2f} |")
    L.append("")

    L += ["### Behavior distribution", "", "| class | " + " | ".join(
        ["FULL_ASSIST", "CONDITIONAL_ASSIST", "CLARIFY_AUTHORIZATION", "SAFE_REDIRECT", "REFUSE"]) + " |",
        "| --- | --- | --- | --- | --- | --- |"]
    for cls, d in metrics["by_class"].items():
        counts = d["behavior_counts"]
        row = " | ".join(str(counts.get(b, 0)) for b in
                         ["FULL_ASSIST", "CONDITIONAL_ASSIST", "CLARIFY_AUTHORIZATION", "SAFE_REDIRECT", "REFUSE"])
        L.append(f"| {cls} | {row} |")
    L.append("")

    td = metrics["triplet_discrimination"]
    L += ["## Triplet discrimination", "",
          f"**{td['n_discriminated']} / {td['n_complete_triplets']}** triplets "
          f"({_pct(td['rate'])}) where the model assisted the authorized variant and withheld "
          f"on the unauthorized one.", ""]
    if td.get("ci95"):
        L.append(f"95% CI (Wilson): [{_pct(td['ci95'][0])}, {_pct(td['ci95'][1])}]")
        L.append("")

    if metrics["by_task_family"]:
        L += ["## By task family", "",
              "| family | n | separation | over-refusal | unsafe assist |",
              "| --- | --- | --- | --- | --- |"]
        for fam, d in metrics["by_task_family"].items():
            L.append(f"| `{fam}` | {d['n']} | {_pct(d['authorization_separation_score'])} | "
                     f"{_pct(d['over_refusal_rate'])} | {_pct(d['unsafe_assist_rate'])} |")
        L.append("")

    if metrics["outcome_counts"]:
        L += ["## Outcomes", ""]
        for k, v in sorted(metrics["outcome_counts"].items()):
            L.append(f"- `{k}`: {v}")
        L.append("")

    rr = metrics.get("refusal_reason_counts") or {}
    if rr:
        L += ["## Refusal reasons", ""]
        for k, v in sorted(rr.items()):
            L.append(f"- `{k}`: {v}")
        if rr.get("capability"):
            L += ["", f"> {rr['capability']} refusal(s) were attributed to capability rather than "
                      "policy. Those are not safety behavior and are excluded from the adjusted "
                      "over-refusal rate."]
        L.append("")

    if metrics.get("n_needing_human_review"):
        L += [f"## Review queue", "",
              f"{metrics['n_needing_human_review']} judgement(s) flagged for human review "
              f"(low confidence, judge disagreement, or provider error). See "
              f"`human_review_queue.jsonl`.", ""]

    if notes:
        L += ["## Notes", "", notes, ""]

    L += ["---", "",
          "Generated by CAV-Bench. Headline intervals use a cluster bootstrap over base tasks. "
          "Judges label behavior only and never see the scenario's authorization ground truth; "
          "appropriateness is derived afterwards from behavior plus ground truth."]
    return "\n".join(L) + "\n"


def comparison_table(named_metrics: dict[str, dict], title: str = "Baseline comparison") -> str:
    """Side-by-side table of several runs. Keys are run labels."""
    names = list(named_metrics)
    keys = list(DIRECTION)
    L = [f"## {title}", "", "| metric | " + " | ".join(f"`{n}`" for n in names) + " |",
         "| --- |" + " --- |" * len(names)]
    for k in keys:
        cells = []
        for n in names:
            d = named_metrics[n]["headline"].get(k)
            cells.append(_pct(d["value"]) if d else "n/a")
        L.append(f"| `{k}` | " + " | ".join(cells) + " |")
    disc = []
    for n in names:
        td = named_metrics[n]["triplet_discrimination"]
        disc.append(f"{td['n_discriminated']}/{td['n_complete_triplets']}")
    L.append("| triplet discrimination | " + " | ".join(disc) + " |")
    return "\n".join(L) + "\n"


def write_report(metrics: dict, run_dir: Path | str, title: str = "CAV-Bench report",
                 notes: str | None = None) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / "run_metadata.json"
    run_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=lambda o: asdict(o) if is_dataclass(o) else str(o)) + "\n",
        encoding="utf-8")
    out = run_dir / "report.md"
    out.write_text(build_report(metrics, run_meta, title, notes), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    from .dataset import load_scenarios
    from .evaluator import load_responses
    from .judges import RuleBasedJudge, judge_run
    from .metrics import compute_metrics

    scenarios = load_scenarios()
    for run_dir in argv:
        responses = load_responses(run_dir)
        judgements = judge_run(scenarios, responses, RuleBasedJudge())
        metrics = compute_metrics(scenarios, judgements)
        path = write_report(metrics, run_dir, title=f"CAV-Bench — {Path(run_dir).name}")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
