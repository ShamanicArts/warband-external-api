# Restricted-agent usability evidence

`faction-order-v1-model-results.json` records the first announced external-model
evaluation of the deterministic faction fixture. Luna, Muse 1.3 Contributor and
Grok 4.6 each returned the correct bounded action on the first attempt; the real
fixture evaluator accepted all three at 100/100. The initial DeepSeek lookup used
the wrong provider surface. A corrective run through Pi with
`opencode-go/deepseek-v4.1-flash` also passed the revision-recovery fixture at
100/100.

This supports `agent-usable` for the restricted fixture shape only. It does not
prove that the fixture's simulated party order is wired to Warband, nor does it
promote every semantic capability to `agent-usable`. Luna and Grok independently
identified an ambiguity in where `expected_revision` comes from.

`faction-revision-recovery-v2-model-results.json` records the announced recovery
retest after that binding was made explicit. The same three available models
each abandoned the rejected revision-7 token and selected the current revision-8
defense affordance; all three responses passed the real evaluator at 100/100.
The original three-model run did not silently substitute DeepSeek. Grok's
critique also led to explicit manifest and guide rules for required `const`
arguments and same-session affordance timestamps. The later DeepSeek V4.1 Flash
result is recorded separately and does not rewrite the original run. This
remains fixture evidence, not live game evidence.
