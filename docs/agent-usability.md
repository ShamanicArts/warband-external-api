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
`agent-usable` evidence level by itself. External evaluation on the exact v1 hash
was subsequently announced and run once each with GPT-6 Luna, Muse Spark 1.3
Contributor and Grok 4.6. All three responses passed the real evaluator at 100;
DeepSeek 4.1 was absent from the provider catalog and was not substituted. Results
are retained in `evidence/agent-usability/`.

Luna and Grok both noted that agents must infer `expected_revision` from the
observation/affordance context. The next fixture revision should state that binding
directly and then receive a separately announced retest. This v1 result establishes
`agent-usable` only for the restricted fixture shape, not for a live party-order
backend or every capability. Future external runs still require the same advance
notice, raw response, evaluation, settings, timing and available cost record.
