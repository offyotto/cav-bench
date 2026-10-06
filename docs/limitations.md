# Limitations

Read this before citing any number from this repository.

## No model results exist

Version 0.1 contains an evaluation harness and a dataset. No model has been run. The
baseline table reports mock policies and says nothing about any deployed system.

## The dataset is small

Ten base tasks, thirty scenarios. Intervals computed by resampling ten clusters are
wide. The keyword baseline's separation interval is [0%, 50%].

This is the honest uncertainty at this size, not a defect in the estimator. It does
mean v0.1 can distinguish a model that ignores authorization from one that tracks it
closely, and cannot resolve moderate differences between similar models. The planned
40-task set addresses this.

## Single-turn only

Every scenario is one user turn. Real refusals are negotiated across several turns,
and authorization is often established after the first request. The multi-turn track
is specified and unpopulated.

## Paraphrase stability is unmeasured

A model may respond differently to semantically identical prompts. Without the
paraphrase track, no result here separates a genuine authorization judgement from
sensitivity to specific wording. This is the largest outstanding threat to the
construct.

## The ambiguous class encodes a normative choice

Treating `CLARIFY_AUTHORIZATION` as the ideal response to an underspecified request
is a position, not a fact. A reasonable alternative holds that most such requests are
legitimate and that demanding justification imposes a cost on ordinary users.

Scenario files carry per-scenario expectation fields, so the alternative can be
encoded and scored without changing code. A result's interpretation depends on which
convention was used, and reports must state it.

## Residual keyword leakage

The controls require that no authorization keyword be confined to one class. They do
not require balance. In v0.1 the most class-predictive single keyword is `research`,
which reaches 75% purity, concentrated in the ambiguous class with four occurrences.

The keyword baseline reaches only 20% separation, so the leakage is not currently
exploitable at a level that threatens the design, but it should narrow as the
dataset grows. A trained classifier was not tested; only the single-keyword baseline
was.

## Judge quality bounds every number

The rule-based judge is a transparent heuristic over regular expressions. It
recovers the five mock templates exactly, which says more about the templates than
about real responses. Real model output is longer, hedged, and mixes behaviors —
partial assistance with an embedded question is common and the taxonomy forces it
into one label.

No human-annotated gold set exists yet, so judge accuracy against human judgement is
unknown. Report inter-judge agreement with any LLM-judged result, and treat
rule-based-only results as triage.

## Scenarios are fictional and written by one author

All scenarios were authored for this benchmark rather than drawn from real traffic.
They may not reflect how practitioners actually phrase requests, and single
authorship risks a consistent unexamined style. Prompts derived from real logs, with
consent, would be stronger evidence.

## Provider routing can misattribute results

Several vendors now serve higher-risk cyber requests from a different model than the
one requested. A result attributed to the requested model may describe a fallback.
Log the served model where the provider exposes it, and treat results as describing
a serving configuration rather than a model.

## Coverage is narrow by design

Ten task families drawn from standard penetration-testing curricula. Prohibited-use
categories are excluded deliberately, so the benchmark says nothing about behavior on
command-and-control, mass exfiltration or ransomware, where the correct answer is to
decline regardless of authorization.

Defensive-only tasks are also under-represented. For work such as writing detection
rules or analysing your own logs the authorization axis barely applies, which is why
the first ten tasks all have a meaningful unauthorized variant. Expanding to 40 tasks
will require either accepting weaker contrasts or restricting the catalogue to tasks
where authorization genuinely changes the answer.

## English only

Refusal behavior is known to vary across languages. All scenarios are English.
