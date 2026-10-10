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

## Direct constrained-MCP fixture

`serve-mcp` exposes the same decision shape through a real authenticated
constrained session. It intentionally advances from revision 7 to revision 8
between the first turn and first submission, forcing clients to recover from a
409 conflict instead of succeeding on a static happy path. It never launches or
connects to Warband.

Create a private 64-character hexadecimal token, then start the fixture:

```bash
openssl rand -hex -out runtime/usability-token 32
chmod 600 runtime/usability-token
warband-agent-usability serve-mcp \
  --fixture faction-revision-recovery-v2 \
  --token-file runtime/usability-token \
  --port 0
```

The first JSON line reports the selected loopback endpoint and agent task without
printing the token. Configure `warband-agent-mcp` with that endpoint and token
file. A correct client must use only the five constrained tools, receive one stale
action rejection, fetch the revision-8 turn, submit a new request ID with the
fresh exact defense affordance, and reconcile the observed outcome.

The reproducible model-neutral transport command is:

```bash
python -m bridge.smoke_constrained_agent_mcp \
  --endpoint http://127.0.0.1:PORT \
  --token-file runtime/usability-token \
  --evidence evidence/agent-usability/direct-mcp-fixture-smoke.json
```

The current deterministic export SHA-256 is
`b810f38bf41f82278e0d5aebf0a752f81754f9e03cfa95d7957bec5dabe208d5`.
The v2 recovery export SHA-256 is
`2c8bd1b6e632ebb7ad2b37f33356926f853e1a4680ae0424ac4611759dd1ac20`.

Passing unit and CLI tests establishes a reproducible evaluation harness, not the
`agent-usable` evidence level by itself. External evaluation on the exact v1 hash
was subsequently announced and run once each with GPT-6 Luna, Muse Spark 1.3
Contributor and Grok 4.6. All three responses passed the real evaluator at 100;
DeepSeek was not run in that batch because the initial catalog query inspected
the wrong provider surface. A later correction found exact DeepSeek V4.1 Flash
routes through Pi. Results and the correction are retained in
`evidence/agent-usability/`.

Luna and Grok both noted in v1 that agents had to infer `expected_revision` from
the observation/affordance context. `faction-revision-recovery-v2` states that
binding directly and includes the rejected v1-shaped attempt, its stale-context
outcome and newly issued revision-8 affordances. A separately announced v2 run
with GPT-6 Luna, Muse Spark 1.3 Contributor and Grok 4.6 then produced the correct
fresh token, arguments and revision on the first attempt for all three models;
the real evaluator accepted every response at 100/100. The missing DeepSeek run
was subsequently completed over this same fixture using the exact
`opencode-go/deepseek-v4.1-flash` model through Pi, also scoring 100/100.

Grok's v2 critique exposed two remaining documentation ambiguities: whether
required `const` arguments must still be sent, and how to interpret affordance
timestamps. The constrained session manifest and API guide now make both rules
explicit. The external run still establishes `agent-usable` only for the
restricted deterministic fixture, not for a live party-order backend or every
capability. Future external runs still require advance notice, raw response,
evaluation, settings, timing and the available cost record.

The constrained MCP v3 evaluation then asked the model families to read the MCP
contract, recover the v2 stale context, choose the
submission, name the `turn` → `act` → `outcome` sequence, and critique the
interface. Luna, Muse, Grok and the corrective DeepSeek V4.1 Flash run all
returned strict JSON, selected the fresh defense affordance and passed the real
evaluator at 100/100. Luna and Grok independently called out the omitted
`request_id`; Grok also noted that a broad capability schema can look like
authority to compose arguments. The manifest, MCP tool description and API guide
now define a stable client-chosen request-ID convention and state that only a
current affordance authorizes action. DeepSeek separately called out missing
outcome-poll timing and queued-versus-observed examples; those are now explicit
in the same contract surfaces.

This v3 run is contract-comprehension evidence, not a claim that the external
models were attached to the MCP server. The exact prompt and raw outputs are in
`evidence/agent-usability/constrained-mcp-v3-*`; the separate
`constrained-mcp-smoke.json` proves a real local stdio handshake and action/outcome
round trip.

The next acceptance attached GPT-6 Luna directly to those five MCP tools over the
deterministic stale-transition backend. Luna read the manifest and revision-7
turn, received the forced 409 conflict, fetched revision 8, chose a new request ID
and current defense token, then reconciled an `observed` outcome proving
`parties.17.order = defend` at revision 9. No shell, file or browser tool was
called. The raw bounded trace is
`evidence/agent-usability/direct-mcp-luna-v1.json`; the model-neutral transport
run is `direct-mcp-fixture-smoke.json`. This proves direct model-over-MCP use of
the constrained interface, but the backend was deterministic rather than a live
Warband process. Live model-over-MCP game control remains open.
