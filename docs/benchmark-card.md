# Benchmark card: CAV-Bench v0.1

## Summary

| field | value |
| --- | --- |
| name | CAV-Bench (Contextual Authorization Verification Benchmark) |
| version | 0.1 |
| measures | whether a cyber safeguard separates authorized from unauthorized security work |
| does not measure | model security capability, jailbreak resistance, general over-refusal |
| scenarios | 30 (10 base tasks x 3 authorization conditions) |
| tracks present | core |
| tracks specified but empty | paraphrase, multi-turn, verified-access |
| languages | English |
| judging | rule-based, LLM, or ensemble; behavior labels only |
| code licence | MIT |
| data licence | CC BY 4.0 |

## Composition

| authorization class | n | evidence strength range |
| --- | --- | --- |
| authorized | 10 | L3–L4 |
| ambiguous | 10 | L0–L1 |
| unauthorized | 10 | L0–L1 |

Six unauthorized scenarios are authorization theater: an explicit claim contradicted
by structural evidence.

### Task families

Web application testing, credential recovery, network enumeration, social
engineering, malware analysis, wireless security, binary exploitation,
authentication testing, mobile security, Active Directory.

Each family contributes one base task and therefore one triplet. Risk levels are
annotated per task: one high, eight medium, one low.

### Target types

Loopback addresses, lab environments, retired CTF challenges, synthetic
repositories, and fictional third parties. No scenario names a real system, and no
scenario contains an operational payload. The JSON Schema pins
`contains_operational_payload` to `false`, so a payload-bearing scenario cannot
validate.

## Intended use

Comparing safeguard configurations on the authorization decision: across model
versions, across providers, or across access tiers such as a standard account versus
a verified cyber-research account.

Diagnosing which failure mode dominates. A deployment may be tuned so tightly that
it refuses authorized work, or so loosely that unsupported claims unlock it. The
suite distinguishes these, where a single refusal-rate number cannot.

## Out of scope

Capability measurement. Prohibited-use categories, which are excluded. Any claim
about a model's real-world misuse rate — scenarios are constructed, not sampled from
traffic.

Not suitable as a training or fine-tuning target. Thirty scenarios with public
ground truth would be memorised, and optimising against the controls would defeat
their purpose.

## Known biases

Single author, constructed prompts, English only. Residual keyword leakage: the most
class-predictive term reaches 75% purity. Defensive-only tasks are under-represented
because the authorization axis barely applies to them.

See [limitations](limitations.md) for the full list.

## Validation performed

- Dataset validates against the schema with zero errors and zero warnings.
- 114 tests pass, including the matched-set, keyword-balance, length-balance and
  intensity-balance invariants.
- An oracle policy scores 100% separation, confirming the judge recovers intended
  labels without access to ground truth.
- Three constant policies score exactly 0% separation.
- A keyword policy reaches 20% separation, interval [0%, 50%], and 100% theater
  susceptibility.

## Validation not performed

Human annotation of judge accuracy. Paraphrase stability. Any evaluation of a
deployed model.

## Maintenance

The dataset is generated from `tools/build_core_scenarios.py`. Matched-set
invariants are enforced in the loader and asserted in tests, so a scenario edit that
breaks a triplet fails CI rather than silently degrading the benchmark.

Dataset versions are directories under `data/scenarios/`. Results carry the SHA-256
digest of the exact prompts evaluated.

## Citation

See `CITATION.cff`.
