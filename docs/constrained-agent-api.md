# Constrained agent API

The constrained interface is for NPC, party, faction, benchmark and limited
player-adjacent agents that must not receive operator tools or bridge internals.
It is a provider-neutral Python session with an optional authenticated loopback
HTTP adapter. Full operator MCP remains a separate diagnostic surface.

## Trust boundary

An agent supplies only:

- a client request ID for idempotency;
- one server-issued affordance token;
- arguments allowed by that affordance;
- the revision copied from `turn.observation.context.revision`.

The runtime owns action IDs, actor identity, role grants, control leases,
timestamps and handler bindings. A client cannot name a different actor, forge a
lease or submit a raw bridge operation. The capability registry rechecks grant,
lease, expiry, context, revision and arguments immediately before dispatch.

`ConstrainedAgentSession` receives application callbacks for canonical
observation, affordance issuance and validated dispatch. It applies the named
perception policy before returning a turn. Turns are cached for an unchanged
semantic context so polling does not mint endless duplicate affordances.

Applications may also supply a trusted outcome refresher. Public outcome lookup
then reconciles queued work with engine-owned lifecycle state while preserving
the original action and context identity, enforcing legal state transitions and
emitting a distinct action event for every observed transition.

## Native menu application

`bridge.native_menu_agent_app.NativeMenuAgentApplication` is the first
production composition over the live bridge `Store`. It owns a private
player-strategic grant and exclusive `player.menu` lease, derives semantic
revisions from current telemetry, and issues only exact-session affordances from
the live menu catalog.

A validated submission queues the existing `select_menu` operation without
exposing its raw opcode or bridge command ID. Initial queue acceptance is
reported as declared evidence. Subsequent public outcome lookup reconciles
`dispatched`, `acknowledged`, `rejected`, `expired` and `interrupted` states from
the Store; only a matching Warband acknowledgement is promoted to
engine-acknowledged evidence. Menu or session changes invalidate stale
affordances. Pass `application.session` to `make_agent_server` to expose the same
boundary over HTTP.

## HTTP adapter

`make_agent_server(session, token)` binds only to `127.0.0.1` and requires a
Bearer token of at least 32 characters.

- `GET /v1/agent/manifest` — role, public actor and submission contract.
- `GET /v1/agent/turn` — filtered observation, discoverable capabilities,
  current affordances and event cursor.
- `POST /v1/agent/actions` — validate and dispatch one constrained action.
- `GET /v1/agent/actions/{request_id}` — idempotent in-session outcome lookup.
- `GET /v1/agent/events?after={sequence}&limit={n}` — session-owned action events.

Example submission:

```json
{
  "request_id": "decision:epoch-12:party-17",
  "affordance_token": "opaque-token-from-current-turn",
  "arguments": {"order": "defend", "target_id": 2},
  "expected_revision": 7
}
```

Conflicting request-ID reuse and stale/consumed affordances return HTTP 409.
Malformed envelopes return 400. Auth failures return 403. Dispatcher exceptions
become explicit `interrupted` outcomes rather than prompting unsafe automatic
replay. Successful action events retain the strongest supplied evidence level;
acknowledgement is not promoted to observed outcome.

## Current limitations

- Construction is Python-first; packaged application loading and multi-session
  lifecycle management are not implemented yet.
- Outcome idempotency is in-memory for the running session. Action events are
  durable when a `SemanticEventLog` is supplied and live Native-menu outcomes
  reconcile against the Store, but full request/outcome reconstruction after an
  application restart remains pending.
- The default event view exposes only action events emitted for this session.
  Role-filtered delivery of broader world/dialogue events needs an explicit event
  audience policy and must not expose the shared log wholesale.
- Production composition currently covers the Native menu path only. Campaign
  faction, party, NPC and dialogue applications remain to be wired.
