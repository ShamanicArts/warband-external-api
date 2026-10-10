# Mechanical proposals from dialogue

`MechanicalProposalBroker` is the provider-neutral safety boundary between an
NPC saying that something should happen and the game actually doing it. A trusted
application offers an option only by binding it to one exact, current affordance
from the constrained session that owns the mechanic.

The NPC-facing option contains an opaque proposal token, title, capability,
already-validated arguments, risk, warning, required acceptors and expiry. It
does not contain the target session's affordance token or authority credentials.
The speech affordance may accept that proposal token alongside `text`.

The lifecycle is deliberately split:

1. A trusted application advances the NPC application revision, then binds a
   current target affordance with `broker.offer()`.
2. The refreshed NPC turn exposes the safe option and constrains
   `proposal_token` to one of its currently offered opaque values.
3. The NPC may attach one opaque token to an otherwise ordinary speech
   submission.
4. Only after Warband observes that speech does the application call
   `broker.commit()` to create a pending proposal.
5. Every named participant independently accepts or one rejects through
   `broker.decide()`.
6. `broker.execute()` submits the original exact token, arguments and revision
   through the target `ConstrainedAgentSession`. It refuses an expired, replaced
   or context-stale affordance.

Free text is never parsed as an action, approval does not widen the original
authority, and the broker cannot remap a stale proposal to a newer affordance.
Repeated commit, decision and execution calls are idempotent when their inputs
agree; conflicting reuse is rejected.

Example application composition:

```python
option = broker.offer(
    source_session_id="village-elder",
    source_context=npc_turn.observation.context,
    title="Ask the patrol to defend Praven",
    target_session_id="swadia",
    target_session=swadia_application.session,
    affordance_token=defend_affordance.token,
    arguments={"order": "defend", "target_id": 2},
    required_acceptors=("player", "swadia-sovereign"),
)

# After the NPC line carrying option["proposal_token"] is engine-observed:
proposal = broker.commit(
    option["proposal_token"], observed_action.action_id, npc_context
)
broker.decide(proposal["proposal_id"], "player", accept=True)
broker.decide(proposal["proposal_id"], "swadia-sovereign", accept=True)
outcome = broker.execute(proposal["proposal_id"])
```

## Packaged-host control API

The application host owns one broker and attaches it to every compatible NPC
application. A trusted loopback integration can offer a current target-session
affordance with:

```text
POST /v1/host/sessions/{source_session_id}/proposal-options
```

The exact body contains `title`, `target_session_id`, `affordance_token`,
`arguments` and a non-empty `required_acceptors` array. The response and the NPC
turn contain only the opaque proposal token and safe affordance metadata, never
the target's private token or credential.

Committed proposals are available only after the selected NPC line becomes
engine-observed:

```text
GET  /v1/host/sessions/{source_session_id}/proposals
GET  /v1/host/proposals/{proposal_id}
POST /v1/host/proposals/{proposal_id}/decisions
POST /v1/host/proposals/{proposal_id}/execute
```

The decision body is exactly `{"acceptor_id":"...","accept":true}`. Execution
has an empty body. All routes use the host operator bearer token. In this first
reference API, `acceptor_id` is therefore a trusted integration assertion; there
is not yet a distinct credential proving that the named player or faction
principal made the request.

The application and host route lifecycle is covered in
`test_native_npc_speech_app.py` and `test_agent_host.py`: unobserved or expired
options cannot create mechanics, failed proposal bookkeeping cannot falsify an
observed speech outcome, and approved execution preserves the exact original
target token, arguments and revision.

Committed proposal lifecycle snapshots and participant decisions are written to
the host-only semantic event log. On restart, rejected and submitted records
retain their terminal audit state. Pending or approved records are restored as
`stale`: the original private target affordance belonged to the old process and
is never rebound to a freshly issued token. Recovered records can be listed and
inspected but cannot accept decisions or execute.

Offered options that were never committed by engine-observed speech are not
restored. Action recovery retains a selected opaque option token, but if the host
failed before the broker committed it, reconciliation records a bounded proposal
failure while preserving the observed speech outcome. Fully resumable proposal
authority would require durable capability-token semantics; silently matching a
new affordance by name and arguments is intentionally forbidden. A live Warband
consequence remains to be built and recorded.
