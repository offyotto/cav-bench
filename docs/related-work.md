# Related work

CAV-Bench sits between two literatures that rarely meet: over-refusal measurement,
which is general-domain and binary, and cyber safety evaluation, which is
cyber-specific and binary. The contribution is the three-way matched design and the
theater condition, not the observation that over-refusal exists.

## Over-refusal benchmarks

**XSTest** (Röttger et al., 2024) pairs 250 benign prompts that look unsafe with 200
contrast unsafe prompts. The structural pairing is the closest precedent for matched
sets. It is general-domain and two-way, and reported results indicate it has become
easy for frontier models.

**OR-Bench** (Cui et al., 2024, [arXiv:2405.20947](https://arxiv.org/abs/2405.20947))
scales to roughly 80,000 seemingly toxic prompts, a hard subset of about 1,000, and
600 genuinely toxic prompts, evaluated across 25 models. Its axis is semantic
ambiguity rather than context, and each prompt is judged in isolation.

**FalseReject** ([arXiv:2505.08054](https://arxiv.org/abs/2505.08054)) and related
resources such as PHTest and OKTest supply further over-refusal material. Reported
refusal rates vary widely by suite for the same model, which indicates these
benchmarks measure different aspects of the same phenomenon.

Common limitation: each prompt is scored alone. These suites establish how often a
model over-refuses, not where the boundary sits or whether it moves with context.

## Context-aware safety evaluation

**CASE-Bench** (Sun et al., ICML 2025,
[arXiv:2501.14940](https://arxiv.org/abs/2501.14940)) is the closest conceptual
neighbour and the most important work to distinguish from. It attaches 900 formally
described contexts to queries drawn from 45 categories, grounding context in
Contextual Integrity theory, and collects non-binary safety ratings from more than
2,000 annotators sized by power analysis. It finds context significantly influences
human judgement, and that commercial models diverge from human judgement
particularly in safe contexts.

Differences from CAV-Bench:

- CASE-Bench is general-domain. CAV-Bench is confined to dual-use security tasks,
  where the authorization question is the operative one and where vendors deploy
  dedicated classifiers.
- CASE-Bench varies context along the Contextual Integrity dimensions of sender,
  recipient and transmission principle. CAV-Bench varies a single axis — evidence
  that the user may act on the target — and annotates that evidence by type,
  polarity and strength.
- CASE-Bench contexts are attached to queries. CAV-Bench holds the technical request
  byte-identical across conditions and enforces that invariant at load time.
- CASE-Bench has no analogue of the theater condition.

## Cyber safety and capability evaluation

**CyberSecEval 2** (Meta, [arXiv:2404.13161](https://arxiv.org/abs/2404.13161))
introduced False Refusal Rate, defined as the share of benign prompts refused, over
roughly 750 borderline-benign cyber prompts. It is plotted against compliance on a
separate malicious-prompt set, so the safety-utility trade-off is visible.

This is the nearest prior art on the cyber axis, and the difference is structural.
CyberSecEval pairs two *separate datasets*: a benign set and a malicious set, built
independently. Nothing holds the technical request constant between them, so a
difference in behavior across the two sets confounds authorization with topic,
phrasing and difficulty. CAV-Bench measures the same comparison within a task.

**PurpCode** ([arXiv:2507.19060](https://arxiv.org/abs/2507.19060)) observes that
CyberSecEval's FRR prompts are verbose and framed around malicious activity, and
builds XSCode, 589 concise benign code-generation prompts, following the XSTest
method. The criticism applies to CAV-Bench too and informed the length and intensity
controls here.

**CyberSecEval 3** ([arXiv:2408.01605](https://arxiv.org/abs/2408.01605)) extends the
capability side. Capability suites such as Cybench, NYU CTF Bench and InterCode-CTF
measure what a model can do, not what it should agree to do, and are orthogonal to
this work.

## Deployed verification programmes

Anthropic documents real-time cyber safeguards on its Opus and Sonnet models and
operates a Cyber Verification Program that adjusts those safeguards for vetted
organizations
([support documentation](https://support.claude.com/en/articles/14604842-real-time-cyber-safeguards-on-claude-opus-and-sonnet)).
The programme distinguishes dual-use activities, which are adjustable, from
prohibited ones, which are not. OpenAI operates a comparable trusted-access
programme for cyber.

These programmes are the practical motivation. They exist because the default
classifier cannot separate authorized from unauthorized work reliably enough, so
vendors fall back to verifying the *organization* instead of reading the *request*.
A benchmark that measures the request-level decision gives a way to tell whether
that fallback is becoming less necessary over time. CAV-Bench reserves a
verified-access track for this comparison; it is specified but not yet populated.

## Summary of the claim

CAV-Bench does not claim that cyber over-refusal is unmeasured. CyberSecEval has
reported it since 2024. The claim is narrower:

1. a three-way design with an explicit ambiguous class, where prior cyber work is
   binary;
2. matched sets holding the technical request constant, where CyberSecEval pairs
   independent datasets;
3. an annotated authorization-evidence taxonomy by type, polarity and strength;
4. an authorization-theater condition measuring susceptibility to unsupported
   claims, which no suite above measures.
