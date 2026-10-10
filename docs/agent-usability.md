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

The response may contain only `affordance_token`, `arguments`, and
`expected_revision`. Trusted actor and lease identities are injected by the
fixture, not chosen by the agent. The normal capability registry then checks the
token, role grant, context revision, lease and exact issued parameter constants.
Raw operation names and extra fields fail.

The current deterministic export SHA-256 is
`b810f38bf41f82278e0d5aebf0a752f81754f9e03cfa95d7957bec5dabe208d5`.

Passing unit and CLI tests establishes a reproducible evaluation harness, not the
`agent-usable` evidence level. Before any external model receives the fixture,
Lucas must get a heads-up naming the model/provider, scope, expected cost/runtime
and evaluation criteria. Each run must retain the exact briefing, raw response,
evaluation result, model settings, timing and cost where available.
