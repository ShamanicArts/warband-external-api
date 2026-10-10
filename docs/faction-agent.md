# Native faction agent application

`NativeFactionAgentApplication` is the first faction-scoped reference
application. It connects a `faction.sovereign` session to real campaign party
getters and the allowlisted Native party-order operation without granting the
agent direct bridge or world-control access.

## Host lifecycle

The host owns scenario policy and synchronization:

```python
from bridge.native_faction_agent_app import (
    NativeFactionAgentApplication,
    PartyOrderOption,
)

application = NativeFactionAgentApplication(
    store,
    "benchmark:epoch-12:swadia",
    faction_id=15,
    controlled_party_ids=(500,),
    order_options=(
        PartyOrderOption(500, "travel", 26, "Move to defend Praven"),
        PartyOrderOption(500, "attack", 99, "Attack the reported enemy party"),
    ),
    event_log=semantic_event_log,
)

refresh_jobs = application.queue_observation_refresh()
# Drive the normal Warband/Store loop until every refresh job is acknowledged.
turn = application.session.turn()
```

The application deliberately does not advance campaign time or wait for model
responses. A future benchmark runner must collect all faction decisions under
equal budgets, commit non-conflicting orders, then advance one fixed epoch.

`application.session` may be passed directly to `make_agent_server` for the
authenticated loopback HTTP surface. Agents only submit request ID, opaque
affordance token, exact bounded arguments and observation revision.

## Trust and evidence boundary

- The host must review the controlled parties and offered options.
- Fresh engine getter facts must prove each controlled party belongs to the
  granted faction; mismatch fails closed before affordance issuance.
- The private adapter injects `world_control=True` only after grant, lease,
  context, revision, token and exact-argument validation.
- Attack is a separate consequential, non-reversible capability. Other current
  AI orders are labelled reversible but still replace the party's prior order.
- Queue insertion is declared evidence. Protocol acknowledgement is not outcome
  proof. A complete `/world-result` party read-back raises the action to
  engine-observed evidence.
- AI behavior/object read-back is not proof of travel, arrival, combat success or
  persistence after Native AI runs again.

The application currently refreshes only parties referenced by its reviewed
options. Faction treasury, settlements, reports, diplomacy, fog of war,
hierarchical lord agents, automatic option generation and synchronized benchmark
epochs remain future layers.
