"""Run scenarios against a provider and record raw responses.

The evaluator is deliberately dumb: it collects responses and metadata and
writes them to disk. It assigns no labels and computes no metrics, so a run can
be re-judged later without re-spending API budget.

Layout written per run:

    runs/<run_id>/
        run_metadata.json     provider config, dataset digest, timings, versions
        responses.jsonl       one record per scenario

Re-running with the same output directory resumes: scenario ids already present
in responses.jsonl are skipped unless `overwrite=True`.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .dataset import Scenario
from .providers.base import Provider, ProviderError

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


@dataclass
class EvalConfig:
    run_id: str | None = None
    output_dir: Path | None = None
    # Provenance. A provider account may sit in an organization whose cyber
    # safeguards have been adjusted (for example under a vendor verification
    # programme). That changes what is being measured, so it is recorded
    # explicitly rather than inferred: the API key alone does not reveal it.
    organization_id: str | None = None
    access_tier: str = "unknown"      # unknown | standard | verified
    max_retries: int = 4
    backoff_base_s: float = 2.0
    backoff_cap_s: float = 60.0
    min_interval_s: float = 0.0       # simple client-side rate limit
    overwrite: bool = False
    stop_on_error: bool = False
    progress: bool = True


@dataclass
class ResponseRecord:
    scenario_id: str
    base_task_id: str
    authorization_class: str
    track: str
    model: str
    provider: str
    response_text: str
    stop_reason: str | None
    attempts: int
    latency_s: float
    error: str | None
    usage: dict = field(default_factory=dict)
    timestamp: str = ""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dataset_digest(scenarios: list[Scenario]) -> str:
    """Stable digest of the exact prompts evaluated, for reproducibility."""
    h = hashlib.sha256()
    for s in sorted(scenarios, key=lambda x: x.raw["scenario_id"]):
        h.update(s.raw["scenario_id"].encode())
        h.update(b"\x00")
        h.update(s.full_text().encode())
        h.update(b"\x00")
    return h.hexdigest()


def _default_run_id(provider: Provider) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-._" else "-" for c in f"{provider.name}-{provider.model}")
    return f"{stamp}-{safe}"


def _load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("error") is None:
                done.add(rec["scenario_id"])
    return done


def call_with_retry(provider: Provider, scenario: Scenario, cfg: EvalConfig) -> tuple[object, int, float, str | None]:
    """Return (response_or_None, attempts, latency_s, error_or_None)."""
    kwargs = {}
    if getattr(provider, "name", "") == "mock":
        kwargs["scenario"] = scenario.raw

    delay = cfg.backoff_base_s
    started = time.monotonic()
    last_err: str | None = None
    for attempt in range(1, cfg.max_retries + 1):
        try:
            resp = provider.complete(scenario.messages(), **kwargs)
            return resp, attempt, time.monotonic() - started, None
        except ProviderError as e:
            last_err = f"{type(e).__name__}: {e}"
        except Exception as e:  # network, parse, provider-specific
            last_err = f"{type(e).__name__}: {e}"
        if attempt < cfg.max_retries:
            time.sleep(min(delay, cfg.backoff_cap_s))
            delay *= 2
    return None, cfg.max_retries, time.monotonic() - started, last_err


def run_evaluation(scenarios: list[Scenario], provider: Provider,
                   cfg: EvalConfig | None = None) -> Path:
    cfg = cfg or EvalConfig()
    run_id = cfg.run_id or _default_run_id(provider)
    out_dir = Path(cfg.output_dir) if cfg.output_dir else RUNS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    responses_path = out_dir / "responses.jsonl"

    if cfg.overwrite and responses_path.exists():
        responses_path.unlink()
    done = _load_done(responses_path)

    todo = [s for s in scenarios if s.raw["scenario_id"] not in done]
    started_at = _utcnow()
    t0 = time.monotonic()
    n_err = 0
    last_call = 0.0

    with open(responses_path, "a", encoding="utf-8") as f:
        for i, s in enumerate(todo, 1):
            if cfg.min_interval_s:
                wait = cfg.min_interval_s - (time.monotonic() - last_call)
                if wait > 0:
                    time.sleep(wait)
            last_call = time.monotonic()

            resp, attempts, latency, err = call_with_retry(provider, s, cfg)
            if err:
                n_err += 1
            rec = ResponseRecord(
                scenario_id=s.raw["scenario_id"],
                base_task_id=s.raw["base_task_id"],
                authorization_class=s.raw["authorization_class"],
                track=s.raw["track"],
                model=getattr(resp, "model", provider.model) if resp else provider.model,
                provider=provider.name,
                response_text=getattr(resp, "text", "") if resp else "",
                stop_reason=getattr(resp, "stop_reason", None) if resp else None,
                attempts=attempts,
                latency_s=round(latency, 3),
                error=err,
                usage=getattr(resp, "usage", {}) if resp else {},
                timestamp=_utcnow(),
            )
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
            f.flush()

            if cfg.progress:
                mark = "!" if err else "."
                sys.stderr.write(mark)
                sys.stderr.flush()
            if err and cfg.stop_on_error:
                raise ProviderError(f"{s.raw['scenario_id']}: {err}")

    if cfg.progress:
        sys.stderr.write("\n")

    meta = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": _utcnow(),
        "wall_seconds": round(time.monotonic() - t0, 2),
        "provider": provider.describe(),
        "organization_id": cfg.organization_id,
        "access_tier": cfg.access_tier,
        "n_scenarios_total": len(scenarios),
        "n_evaluated_this_run": len(todo),
        "n_skipped_resumed": len(scenarios) - len(todo),
        "n_errors": n_err,
        "dataset_digest_sha256": dataset_digest(scenarios),
        "scenario_ids": sorted(s.raw["scenario_id"] for s in scenarios),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "config": {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(cfg).items()},
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return out_dir


def load_responses(run_dir: Path | str) -> list[dict]:
    path = Path(run_dir) / "responses.jsonl"
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
