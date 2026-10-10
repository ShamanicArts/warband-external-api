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

Each affordance's `parameters.required` list is literal: every named argument
must be submitted. A property with `const` is a server-bound required value to
copy exactly, not permission to omit that property. `issued_at_ms` and
`expires_at_ms` use the session runtime's millisecond clock. Clients should treat
them only as same-session validity metadata and fetch a fresh turn after expiry
or any conflict; fixture clocks may intentionally be synthetic.

`ConstrainedAgentSession` receives application callbacks for canonical
observation, affordance issuance and validated dispatch. It applies the named
perception policy before returning a turn. Turns are cached for an unchanged
semantic context so polling does not mint endless duplicate affordances.

Applications may also supply a trusted outcome refresher. Public outcome lookup
then reconciles queued work with engine-owned lifecycle state while preserving
the original action and context identity, enforcing legal state transitions and
emitting a distinct action event for every observed transition.
Late engine evidence may promote an expired or interrupted action to observed;
the runtime never replays the uncertain mutation to obtain that evidence.

`warband-agent-host` loads four reviewed built-in application kinds from a
versioned JSON configuration, gives every session a separate loopback port/token,
and exposes explicit trusted faction/NPC refresh through a distinct operator
control listener. See [the application-host guide](application-host.md).
Trusted launchers can add declared application kinds through the
[Python extension SDK](extension-sdk.md); agent-facing session semantics remain
the same.

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

## Native faction application

`bridge.native_faction_agent_app.NativeFactionAgentApplication` composes the
same constrained session around the proven campaign party getter and order
paths. The host or benchmark defines the faction, controlled party IDs and a
reviewed set of exact `PartyOrderOption` choices. Those bindings are private;
the agent receives semantic party-order affordances, not `world_control`, bridge
operation names or arbitrary entity-ID authority.

Each decision epoch begins with `queue_observation_refresh()`. The host waits for
those normal Store commands to finish before requesting `application.session.turn()`.
The application then:

- builds the sovereign observation from fresh engine party getters;
- refuses all affordances unless every controlled party's observed faction
  matches the granted faction;
- owns one exclusive `party.strategy` lease per controlled party;
- marks movement orders reversible and attack orders consequential;
- reports queueing as declared, game acknowledgement as acknowledged, and only
  party getter read-back as observed.

The current read-back proves assigned Native AI behavior and target at that
instant. It does not prove arrival, battle victory or that Native AI will not
later replace the order. See [the faction application guide](faction-agent.md)
for host orchestration and boundaries.

## Native NPC speech application

`bridge.native_npc_speech_app.NativeNpcSpeechApplication` binds an `npc.self`
session to one live scene agent. A host first calls
`queue_observation_refresh()` and completes the normal scene census. The
application refuses player agents, dead/missing agents, stale or changed mission
scope, battle missions and already-active dialogue before issuing a bounded
`dialogue.speak` affordance.

The agent supplies only 1–200 characters of safe printable text. Agent identity,
scene/session scope, lease and the private `npc_say` operation remain
server-owned. Queueing is declared evidence; only Warband's matching dialogue
open/close event produces an observed outcome.

After that observed outcome, `application.voice_request(...)` creates a
deterministic `SpeechRequest` for the existing host voice API. Synthesis or
playback remains a separate application effect and cannot promote, alter or roll
back game evidence. A trusted host-config policy may dispatch that request
asynchronously and exactly once after reconciliation; the agent cannot choose its
voice profile or delivery. See [the NPC speech guide](npc-speech.md).

The `native-npc-dialogue` variant gates the same response affordance behind one
trusted host-supplied player utterance and adds bounded durable conversation
memory to the NPC observation. The player-input endpoint remains on the separate
operator listener; it does not expand the NPC agent's authority.

`MechanicalProposalBroker` supplies the separate consequence boundary for
dialogue applications. It binds an opaque NPC-visible proposal option to an exact
current affordance in its owning constrained session, waits for engine-observed
speech and all named acceptors, then submits that unchanged affordance. See the
[mechanical-proposal guide](mechanical-proposals.md). The packaged NPC host does
expose trusted option, listing, decision and execution routes. The NPC sees only
safe option manifests and a current enum-bounded `proposal_token`; it never sees
the target session's private affordance token. Proposal state is not yet durable,
and the operator credential—not a participant-specific credential—authenticates
decisions.

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
  "arguments": {"order": "travel", "target_id": 26},
  "expected_revision": 7
}
```

Conflicting request-ID reuse and stale/consumed affordances return HTTP 409.
Malformed envelopes return 400. Auth failures return 403. Dispatcher exceptions
become explicit `interrupted` outcomes rather than prompting unsafe automatic
replay. Successful action events retain the strongest supplied evidence level;
acknowledgement is not promoted to observed outcome.

## Current limitations

- The stock CLI covers the three static built-in applications. Explicit trusted
  extension registration and named installed entry points are supported, while
  automatic loading, hot reload and dynamic session creation are not implemented.
- When a `SemanticEventLog` is supplied, new action records durably reconstruct
  exact request idempotency, the latest public outcome and private
  application-owned bridge correlation after restart. Recovery never dispatches
  an action. Older action events that predate the recovery envelope are retained
  but their request IDs are blocked from replay and their outcome lookup remains
  unavailable.
- The default event view exposes this session's action events and its bounded
  player/NPC conversation events. Role-filtered delivery of broader world or
  foreign dialogue events needs an explicit audience policy and must not expose
  the shared log wholesale.
- Production composition currently covers Native menus, reviewed faction party
  orders, one-turn NPC speech and host-fed persistent NPC dialogue, including
  their command-correlation recovery. Diplomacy, synchronized multi-faction
  epochs, autonomous faction options, in-game player text/speech capture,
  NPC-to-NPC conversations, durable mechanical-proposal recovery and
  participant-specific decision authentication remain to be wired.
