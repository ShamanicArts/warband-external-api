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

1. A trusted application binds a current target affordance with `broker.offer()`.
2. The NPC may mention the opaque token in a speech submission.
3. Only after Warband observes that speech does the application call
   `broker.commit()` to create a pending proposal.
4. Every named participant independently accepts or one rejects through
   `broker.decide()`.
5. `broker.execute()` submits the original exact token, arguments and revision
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

The current slice proves the broker and the optional speech-schema field in
process. Packaged-host option management, participant-authenticated decision
routes, durable proposal recovery and a live Warband consequence remain to be
wired. Until then, this is safe application infrastructure rather than a claimed
end-to-end dialogue mechanic.
