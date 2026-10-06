# CAV-Bench reference baselines

Mock policies scored by the rule-based judge. These are not model results;
they establish that the headline metric cannot be won by a fixed strategy.

## Mock baselines

| metric | `oracle` | `always_comply` | `always_refuse` | `always_clarify` | `keyword` | `random` |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_separation_score` | 100.0% | 0.0% | 0.0% | 0.0% | 20.0% | -40.0% |
| `over_refusal_rate` | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 50.0% |
| `over_refusal_rate_adjusted` | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% | 50.0% |
| `unsafe_assist_rate` | 0.0% | 100.0% | 0.0% | 0.0% | 80.0% | 60.0% |
| `clarification_rate_ambiguous` | 100.0% | 0.0% | 0.0% | 100.0% | 0.0% | 20.0% |
| `theater_susceptibility` | 0.0% | 100.0% | 0.0% | 0.0% | 100.0% | 66.7% |
| `ideal_match_rate` | 100.0% | 33.3% | 33.3% | 33.3% | 40.0% | 30.0% |
| triplet discrimination | 10/10 | 0/10 | 0/10 | 0/10 | 2/10 | 0/10 |
