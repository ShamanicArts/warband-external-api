# Deterministic faction arena evidence

`luna-vs-deepseek-epoch-1.json` records the first external-model use of the
two-faction arena. Each model received only a compact rendering of its own
role-filtered task. Both returned an exact current `defend` affordance, and the
arena's normal action validator accepted and resolved both decisions.

The same artifact also records the deliberately separate provider-budget path.
BB's provider wrappers pushed both calls over the frozen 8,192 input-token cap,
and DeepSeek also exceeded the 512 output-token cap once hidden reasoning was
included. The equal-budget audit therefore discarded both otherwise-valid
responses, substituted `no-decision`, and left the simulated world unchanged.

That distinction is the point: this is positive evidence that external agents
can understand and drive the bounded faction interface, and positive evidence
that accounting fails closed. It is not a successful equal-budget comparative
score, a persistent campaign, or a live Warband run.

The two outcomes are reproducible from the retained inputs:

```bash
uv run warband-faction-arena resolve \
  evidence/faction-arena/luna-vs-deepseek-decisions.json
uv run warband-faction-arena resolve-providers \
  evidence/faction-arena/luna-vs-deepseek-provider-results.json
```

`three-epoch-replay.json` records a persistent authored campaign replay. The
stream emitted turns at revisions 1, 2 and 3 and a final report at campaign hour
103. Reproduce it with:

```bash
uv run warband-faction-arena campaign \
  evidence/faction-arena/three-epoch-decisions.jsonl --epochs 3
```
