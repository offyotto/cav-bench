"""Dataset loading, integrity checks, and confound diagnostics."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .schema import load_schema, validate
from .taxonomy import AuthorizationClass

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Words that a naive safeguard could key on. They must NOT be confined to a
# single authorization class, or the benchmark becomes trivially solvable.
AUTH_KEYWORDS = [
    "authorized", "authorization", "permission", "pentest", "penetration test",
    "ctf", "lab", "educational", "research", "scope", "my own", "i own",
    "localhost", "127.0.0.1", "docker",
]

# Tone/intensity markers. Matched variants should not differ on these.
INTENSITY_MARKERS = [
    "hack", "destroy", "immediately", "asap", "urgent", "revenge", "take down",
    "steal", "dump everything", "own them", "pwn", "!!",
]


@dataclass
class Scenario:
    raw: dict

    def __getattr__(self, item):  # convenience: s.scenario_id etc.
        # Guard against recursion: copy/pickle probe dunders such as
        # __setstate__ before `raw` exists, and looking `raw` up here would
        # re-enter __getattr__ forever.
        if item == "raw" or item.startswith("__"):
            raise AttributeError(item)
        try:
            return self.raw[item]
        except KeyError as e:
            raise AttributeError(item) from e

    def messages(self) -> list[dict]:
        """Chat messages to send to a model (final turn must be 'user')."""
        if self.raw.get("is_multiturn"):
            return [dict(m) for m in self.raw["conversation"]]
        return [{"role": "user", "content": self.raw["prompt"]}]

    def full_text(self) -> str:
        return "\n".join(m["content"] for m in self.messages())


@dataclass
class IntegrityReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n}: invalid JSON: {e}") from e
    return rows


def load_scenarios(paths: Iterable[Path | str] | None = None, version: str = "v0.1") -> list[Scenario]:
    if paths is None:
        paths = sorted((DATA_DIR / "scenarios" / version).glob("*.jsonl"))
    out: list[Scenario] = []
    for p in paths:
        out.extend(Scenario(r) for r in read_jsonl(Path(p)))
    return out


def _wc(text: str) -> int:
    return len(re.findall(r"\S+", text))


def check_integrity(scenarios: list[Scenario], length_tolerance: float = 0.35) -> IntegrityReport:
    rep = IntegrityReport()
    schema = load_schema()

    # 1. schema + unique ids
    ids = Counter(s.raw.get("scenario_id") for s in scenarios)
    for sid, n in ids.items():
        if n > 1:
            rep.errors.append(f"duplicate scenario_id {sid}")
    for s in scenarios:
        for e in validate(s.raw, schema):
            rep.errors.append(f"{s.raw.get('scenario_id')}: {e}")
    if rep.errors:
        return rep

    for s in scenarios:
        r = s.raw
        sid = r["scenario_id"]
        ideal, acc, dis = map(set, (r["ideal_response_classes"], r["acceptable_response_classes"], r["disallowed_response_classes"]))
        if (ideal | acc) & dis:
            rep.errors.append(f"{sid}: response class both allowed and disallowed: {(ideal | acc) & dis}")
        if ideal & acc:
            rep.errors.append(f"{sid}: class listed as both ideal and acceptable: {ideal & acc}")
        if r["is_multiturn"]:
            conv = r["conversation"]
            if not conv or conv[-1]["role"] != "user":
                rep.errors.append(f"{sid}: multiturn conversation must end with a user turn")
            if r.get("prompt"):
                rep.errors.append(f"{sid}: multiturn scenario must not also set prompt")
        else:
            if not r.get("prompt"):
                rep.errors.append(f"{sid}: single-turn scenario requires prompt")
            if r["conversation"]:
                rep.errors.append(f"{sid}: single-turn scenario must have empty conversation")
        if r["theater"]:
            if r["authorization_claim"] == "none":
                rep.errors.append(f"{sid}: theater scenario must contain an authorization claim")
            if r["authorization_class"] == AuthorizationClass.AUTHORIZED.value:
                rep.errors.append(f"{sid}: theater scenario cannot be ground-truth authorized")
        if r["authorization_class"] == "authorized" and r["authorization_strength"] in ("L0", "L1"):
            rep.errors.append(f"{sid}: authorized ground truth needs strength >= L2")
        if r["authorization_class"] == "unauthorized" and not any(
            e["polarity"] == "contradicts" for e in r["authorization_evidence"]
        ):
            rep.errors.append(f"{sid}: unauthorized scenario needs at least one contradicting evidence item")
        text = s.full_text()
        for ev in r["authorization_evidence"]:
            if ev["span"].lower() not in text.lower():
                rep.warnings.append(f"{sid}: evidence span not found verbatim in prompt: {ev['span']!r}")
        if r["track"] == "paraphrase" and not r.get("paraphrase_group"):
            rep.errors.append(f"{sid}: paraphrase track requires paraphrase_group")
        if r["track"] == "verified" and not r.get("access_tier_expectations"):
            rep.errors.append(f"{sid}: verified track requires access_tier_expectations")

    # 2. triplet completeness (core track)
    core = defaultdict(list)
    for s in scenarios:
        if s.raw["track"] == "core":
            core[s.raw["base_task_id"]].append(s)
    for tid, group in core.items():
        classes = sorted(g.raw["authorization_class"] for g in group)
        if classes != ["ambiguous", "authorized", "unauthorized"]:
            rep.errors.append(f"{tid}: core triplet incomplete or duplicated: {classes}")
            continue
        fams = {g.raw["task_family"] for g in group}
        goals = {g.raw["technical_goal"] for g in group}
        arts = {g.raw["requested_artifact"] for g in group}
        if len(fams) > 1 or len(goals) > 1 or len(arts) > 1:
            rep.errors.append(f"{tid}: matched triplet differs in task_family/technical_goal/requested_artifact")
        lens = [_wc(g.full_text()) for g in group]
        lo, hi = min(lens), max(lens)
        if hi and (hi - lo) / hi > length_tolerance:
            rep.warnings.append(f"{tid}: word-count spread {lens} exceeds {length_tolerance:.0%}")
        for marker in INTENSITY_MARKERS:
            has = [marker in g.full_text().lower() for g in group]
            if any(has) and not all(has):
                rep.warnings.append(f"{tid}: intensity marker {marker!r} present in only some variants")

    rep.diagnostics["n_scenarios"] = len(scenarios)
    rep.diagnostics["n_core_triplets"] = len(core)
    rep.diagnostics["by_track"] = dict(Counter(s.raw["track"] for s in scenarios))
    rep.diagnostics["by_class"] = dict(Counter(s.raw["authorization_class"] for s in scenarios))
    rep.diagnostics["keyword_leakage"] = keyword_leakage(scenarios)
    for kw, row in rep.diagnostics["keyword_leakage"].items():
        present = [c for c, n in row.items() if n > 0]
        if len(present) == 1 and sum(row.values()) >= 3:
            rep.warnings.append(f"keyword leakage: {kw!r} appears only in class {present[0]}")
    return rep


def keyword_leakage(scenarios: list[Scenario]) -> dict:
    """Count, per keyword, how many scenarios of each class contain it."""
    table: dict[str, dict[str, int]] = {}
    for kw in AUTH_KEYWORDS:
        row = {c.value: 0 for c in AuthorizationClass}
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", re.I)
        for s in scenarios:
            if pat.search(s.full_text()):
                row[s.raw["authorization_class"]] += 1
        if sum(row.values()):
            table[kw] = row
    return table
