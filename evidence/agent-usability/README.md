# Restricted-agent usability evidence

`faction-order-v1-model-results.json` records the first announced external-model
evaluation of the deterministic faction fixture. Luna, Muse 1.3 Contributor and
Grok 4.6 each returned the correct bounded action on the first attempt; the real
fixture evaluator accepted all three at 100/100. DeepSeek 4.1 was unavailable in
the OpenCode model catalog and was not silently replaced.

This supports `agent-usable` for the restricted fixture shape only. It does not
prove that the fixture's simulated party order is wired to Warband, nor does it
promote every semantic capability to `agent-usable`. Luna and Grok independently
identified an ambiguity in where `expected_revision` comes from; retain that
finding when designing the next interface revision.
