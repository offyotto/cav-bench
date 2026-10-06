"""Command line interface.

    cavbench validate                     check the shipped dataset
    cavbench run --provider mock --policy oracle
    cavbench judge runs/<id>              label behaviors
    cavbench report runs/<id> ...         write report.md + metrics.json
    cavbench compare runs/<a> runs/<b>    paired McNemar comparison
    cavbench baselines                    run every mock policy end to end

Stages are separate on purpose: `run` spends the API budget, everything after
it is free and re-runnable. Re-judging a run with a better judge never costs
another token.

A config file (TOML) may supply the provider block instead of flags:

    [provider]
    provider = "anthropic"
    model = "claude-sonnet-5-5"
    api_key_env = "ANTHROPIC_API_KEY"
    temperature = 0.0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dataset import check_integrity, load_scenarios
from .evaluator import EvalConfig, load_responses, run_evaluation
from .judges import EnsembleJudge, LLMJudge, RuleBasedJudge, judge_run, write_judgements
from .metrics import compare_runs, compute_metrics, format_report
from .providers import build_provider
from .report import comparison_table, write_report

MOCK_POLICIES = ["oracle", "always_comply", "always_refuse", "always_clarify", "keyword", "random"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _provider_spec(args) -> dict:
    if getattr(args, "config", None):
        import tomllib
        with open(args.config, "rb") as f:
            spec = dict(tomllib.load(f).get("provider", {}))
        if not spec:
            raise SystemExit(f"{args.config}: no [provider] table found")
        return spec
    spec = {"provider": args.provider, "model": args.model}
    for flag in ("api_key_env", "base_url", "temperature", "max_tokens", "system_prompt"):
        v = getattr(args, flag, None)
        if v is not None:
            spec[flag] = v
    if args.provider == "mock":
        spec["policy"] = args.policy
    return spec


def _load(args) -> list:
    scenarios = load_scenarios(version=getattr(args, "version", "v0.1"))
    if getattr(args, "limit", None):
        scenarios = scenarios[:args.limit]
    if not scenarios:
        raise SystemExit("no scenarios loaded")
    return scenarios


def _build_judge(args):
    kind = getattr(args, "judge", "rule")
    if kind == "rule":
        return RuleBasedJudge()
    spec = {"provider": args.judge_provider, "model": args.judge_model,
            "api_key_env": args.judge_api_key_env, "temperature": 0.0}
    llm = LLMJudge(build_provider({k: v for k, v in spec.items() if v is not None}))
    if kind == "llm":
        return llm
    return EnsembleJudge([RuleBasedJudge(), llm], require_unanimous=args.require_unanimous)


def _judgements_for(run_dir: Path, scenarios: list, args):
    """Reuse judgements.jsonl when present, otherwise judge now."""
    path = run_dir / "judgements.jsonl"
    if path.exists() and not getattr(args, "rejudge", False):
        from .judges import Judgement
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        return [Judgement(**r) for r in rows]
    js = judge_run(scenarios, load_responses(run_dir), _build_judge(args))
    write_judgements(js, run_dir)
    return js


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_validate(args) -> int:
    scenarios = _load(args)
    rep = check_integrity(scenarios)
    d = rep.diagnostics
    print(f"{d['n_scenarios']} scenarios, {d['n_core_triplets']} core triplets")
    print(f"by class: {d['by_class']}")
    for e in rep.errors:
        print(f"  ERROR   {e}", file=sys.stderr)
    for w in rep.warnings:
        print(f"  warning {w}", file=sys.stderr)
    if args.show_leakage:
        print("\nkeyword leakage (authorized/ambiguous/unauthorized):")
        for kw, row in sorted(d["keyword_leakage"].items()):
            print(f"  {kw:18} {row['authorized']:2} {row['ambiguous']:2} {row['unauthorized']:2}")
    print("OK" if rep.ok else "FAILED", file=sys.stderr)
    return 0 if rep.ok else 1


def cmd_run(args) -> int:
    scenarios = _load(args)
    provider = build_provider(_provider_spec(args))
    cfg = EvalConfig(run_id=args.run_id, output_dir=args.output_dir,
                     max_retries=args.max_retries, min_interval_s=args.min_interval,
                     overwrite=args.overwrite, stop_on_error=args.stop_on_error)
    out = run_evaluation(scenarios, provider, cfg)
    meta = json.loads((out / "run_metadata.json").read_text())
    print(f"{out}  evaluated={meta['n_evaluated_this_run']} "
          f"skipped={meta['n_skipped_resumed']} errors={meta['n_errors']}")
    if meta["n_errors"]:
        print("re-run the same command to retry failed scenarios", file=sys.stderr)
    return 0


def cmd_judge(args) -> int:
    scenarios = _load(args)
    for run_dir in args.run_dirs:
        forced = argparse.Namespace(**{**vars(args), "rejudge": True})
        js = _judgements_for(Path(run_dir), scenarios, forced)
        n_human = sum(1 for j in js if j.needs_human)
        print(f"{run_dir}  judged={len(js)} flagged_for_review={n_human}")
    return 0


def cmd_report(args) -> int:
    scenarios = _load(args)
    collected = {}
    for run_dir in args.run_dirs:
        p = Path(run_dir)
        js = _judgements_for(p, scenarios, args)
        m = compute_metrics(scenarios, js, n_boot=args.n_boot, seed=args.seed)
        collected[p.name] = m
        path = write_report(m, p, title=f"CAV-Bench — {p.name}")
        print(f"wrote {path}")
        if args.stdout:
            print()
            print(format_report(m, p.name))
            print()
    if len(collected) > 1 and args.compare_out:
        Path(args.compare_out).write_text(comparison_table(collected), encoding="utf-8")
        print(f"wrote {args.compare_out}")
    return 0


def cmd_compare(args) -> int:
    scenarios = _load(args)
    a, b = Path(args.run_a), Path(args.run_b)
    ja = _judgements_for(a, scenarios, args)
    jb = _judgements_for(b, scenarios, args)
    out = compare_runs(scenarios, ja, jb, criterion=args.criterion)
    print(f"{a.name} vs {b.name}  (criterion: {out['criterion']})")
    print(f"  paired scenarios      {out['n_paired']}")
    print(f"  both correct          {out['both_correct']}")
    print(f"  {a.name} only correct   {out['a_only_correct']}")
    print(f"  {b.name} only correct   {out['b_only_correct']}")
    print(f"  neither correct       {out['neither_correct']}")
    print(f"  McNemar exact p       {out['p_value']:.6g}")
    if out["p_value"] >= 0.05:
        print("  -> no significant difference at alpha=0.05")
    return 0


def cmd_baselines(args) -> int:
    scenarios = _load(args)
    collected = {}
    for policy in MOCK_POLICIES:
        provider = build_provider({"provider": "mock", "model": "mock", "policy": policy})
        out = run_evaluation(scenarios, provider,
                             EvalConfig(run_id=f"mock-{policy}", overwrite=True, progress=False))
        js = judge_run(scenarios, load_responses(out), RuleBasedJudge())
        write_judgements(js, out)
        m = compute_metrics(scenarios, js, n_boot=args.n_boot, seed=args.seed)
        collected[policy] = m
        write_report(m, out, title=f"CAV-Bench — mock baseline `{policy}`")
    table = comparison_table(collected, "Mock baselines")
    Path(args.out).write_text(
        "# CAV-Bench reference baselines\n\n"
        "Mock policies scored by the rule-based judge. These are not model results;\n"
        "they establish that the headline metric cannot be won by a fixed strategy.\n\n"
        + table, encoding="utf-8")
    print(table)
    print(f"wrote {args.out}")
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def _add_dataset_flags(p):
    p.add_argument("--version", default="v0.1", help="dataset version directory")
    p.add_argument("--limit", type=int, help="use only the first N scenarios")


def _add_judge_flags(p):
    p.add_argument("--judge", choices=["rule", "llm", "ensemble"], default="rule")
    p.add_argument("--judge-provider", default="anthropic")
    p.add_argument("--judge-model", default=None)
    p.add_argument("--judge-api-key-env", default="ANTHROPIC_API_KEY")
    p.add_argument("--require-unanimous", action="store_true",
                   help="ensemble: flag anything not unanimous for human review")
    p.add_argument("--rejudge", action="store_true", help="ignore existing judgements.jsonl")


def _add_metric_flags(p):
    p.add_argument("--n-boot", type=int, default=2000, help="bootstrap resamples")
    p.add_argument("--seed", type=int, default=0)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cavbench", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check dataset integrity")
    _add_dataset_flags(p)
    p.add_argument("--show-leakage", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="evaluate scenarios against a provider")
    _add_dataset_flags(p)
    p.add_argument("--config", help="TOML file with a [provider] table")
    p.add_argument("--provider", default="mock",
                   choices=["mock", "anthropic", "openai", "openai_compatible"])
    p.add_argument("--model", default="mock")
    p.add_argument("--policy", default="oracle", choices=MOCK_POLICIES, help="mock provider only")
    p.add_argument("--api-key-env")
    p.add_argument("--base-url")
    p.add_argument("--temperature", type=float)
    p.add_argument("--max-tokens", type=int)
    p.add_argument("--system-prompt")
    p.add_argument("--run-id")
    p.add_argument("--output-dir")
    p.add_argument("--max-retries", type=int, default=4)
    p.add_argument("--min-interval", type=float, default=0.0,
                   help="seconds between requests (client-side rate limit)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--stop-on-error", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("judge", help="label behaviors for one or more runs")
    _add_dataset_flags(p)
    _add_judge_flags(p)
    p.add_argument("run_dirs", nargs="+")
    p.set_defaults(func=cmd_judge)

    p = sub.add_parser("report", help="write report.md and metrics.json")
    _add_dataset_flags(p)
    _add_judge_flags(p)
    _add_metric_flags(p)
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--stdout", action="store_true", help="also print a text summary")
    p.add_argument("--compare-out", help="write a comparison table across the runs")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("compare", help="paired McNemar comparison of two runs")
    _add_dataset_flags(p)
    _add_judge_flags(p)
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--criterion", default="is_ideal",
                   choices=["is_ideal", "is_acceptable", "complies", "declines"])
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("baselines", help="run every mock policy end to end")
    _add_dataset_flags(p)
    _add_metric_flags(p)
    p.add_argument("--out", default="BASELINES.md")
    p.set_defaults(func=cmd_baselines)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except (SystemExit, BrokenPipeError):
        raise
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
