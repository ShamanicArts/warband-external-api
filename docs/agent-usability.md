# Agent-usability fixture

The first model-neutral fixture tests whether an agent can understand the
restricted semantic interface without bridge commands, handler names, guessed
game IDs or operator-only facts. It presents a faction-sovereign observation and
two short-lived party-order affordances. The task asks the agent to defend a
threatened settlement with the controlled party.

Export the exact JSON briefing:

```bash
python -m warband_agentic.usability_cli export
```

Evaluate one JSON response from stdin:

```bash
python -m warband_agentic.usability_cli evaluate < response.json
```

The v2 recovery fixture makes the revision binding explicit and tests whether an
agent abandons a rejected stale token after a context refresh:

```bash
python -m warband_agentic.usability_cli export \
  --fixture faction-revision-recovery-v2
python -m warband_agentic.usability_cli evaluate \
  --fixture faction-revision-recovery-v2 < response.json
```

The response may contain only `affordance_token`, `arguments`, and
`expected_revision`. Trusted actor and lease identities are injected by the
fixture, not chosen by the agent. The normal capability registry then checks the
token, role grant, context revision, lease and exact issued parameter constants.
Raw operation names and extra fields fail.

The current deterministic export SHA-256 is
`b810f38bf41f82278e0d5aebf0a752f81754f9e03cfa95d7957bec5dabe208d5`.
The v2 recovery export SHA-256 is
`2c8bd1b6e632ebb7ad2b37f33356926f853e1a4680ae0424ac4611759dd1ac20`.

Passing unit and CLI tests establishes a reproducible evaluation harness, not the
`agent-usable` evidence level by itself. External evaluation on the exact v1 hash
was subsequently announced and run once each with GPT-6 Luna, Muse Spark 1.3
Contributor and Grok 4.6. All three responses passed the real evaluator at 100;
DeepSeek 4.1 was absent from the provider catalog and was not substituted. Results
are retained in `evidence/agent-usability/`.

Luna and Grok both noted in v1 that agents had to infer `expected_revision` from
the observation/affordance context. `faction-revision-recovery-v2` states that
binding directly and includes the rejected v1-shaped attempt, its stale-context
outcome and newly issued revision-8 affordances. A separately announced v2 run
with GPT-6 Luna, Muse Spark 1.3 Contributor and Grok 4.6 then produced the correct
fresh token, arguments and revision on the first attempt for all three models;
the real evaluator accepted every response at 100/100. DeepSeek 4.1 was absent
from the provider catalog and was not substituted.

Grok's v2 critique exposed two remaining documentation ambiguities: whether
required `const` arguments must still be sent, and how to interpret affordance
timestamps. The constrained session manifest and API guide now make both rules
explicit. The external run still establishes `agent-usable` only for the
restricted deterministic fixture, not for a live party-order backend or every
capability. Future external runs still require advance notice, raw response,
evaluation, settings, timing and the available cost record.
