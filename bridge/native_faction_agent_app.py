"""Production constrained faction application over campaign world controls."""

import json
import secrets
import threading
import time
from dataclasses import dataclass

from warband_agentic import (
    PARTY_STRATEGIC_ORDERS,
    ActionOutcome,
    ActionState,
    ActorKind,
    ActorRef,
    AuthorityClass,
    CapabilityRegistry,
    ConstrainedAgentSession,
    ContextKind,
    Evidence,
    EvidenceLevel,
    Fact,
    FactSource,
    LeaseBook,
    LeaseMode,
    ObservationEnvelope,
    ObservationFilter,
    RoleGrant,
    RoleId,
    context_from_snapshot,
    default_perception_policies,
    issue_party_order_affordance,
    party_facts_from_world_result,
    party_operation_from_validated,
    register_party_order_capabilities,
)


def _entity_id(name, value):
    if type(value) is not int or not 0 <= value < 1_000_000:
        raise ValueError(f"{name} must be a bounded non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class PartyOrderOption:
    """One host-reviewed strategic choice available during a faction epoch."""

    party_id: int
    order: str
    target_party_id: int
    title: str

    def __post_init__(self):
        _entity_id("party_id", self.party_id)
        _entity_id("target_party_id", self.target_party_id)
        if self.order not in PARTY_STRATEGIC_ORDERS:
            raise ValueError("Unknown strategic party order")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be a non-empty string")


class NativeFactionAgentApplication:
    """Bind a faction-scoped session to reviewed options and live Store truth."""

    def __init__(
        self,
        store,
        session_id,
        *,
        faction_id,
        controlled_party_ids,
        order_options,
        event_log=None,
        clock_ms=None,
        token_factory=None,
        action_id_factory=None,
        grant_ttl_ms=30 * 60 * 1000,
        affordance_ttl_ms=60_000,
    ):
        for name in ("snapshot", "enqueue_operation", "command", "world_result"):
            if not callable(getattr(store, name, None)):
                raise TypeError(f"store must provide {name}()")
        self.store = store
        self.faction_id = _entity_id("faction_id", faction_id)
        parties = tuple(controlled_party_ids)
        if not parties or len(parties) != len(set(parties)):
            raise ValueError("controlled_party_ids must be non-empty and unique")
        for party_id in parties:
            _entity_id("controlled party ID", party_id)
        options = tuple(order_options)
        if not options or any(
            not isinstance(item, PartyOrderOption) for item in options
        ):
            raise TypeError("order_options must contain PartyOrderOption values")
        if len(options) != len(
            {(item.party_id, item.order, item.target_party_id) for item in options}
        ):
            raise ValueError("order_options contain duplicate choices")
        if any(item.party_id not in parties for item in options):
            raise ValueError("Every order option must use a controlled party")
        if type(grant_ttl_ms) is not int or grant_ttl_ms <= 0:
            raise ValueError("grant_ttl_ms must be a positive integer")
        if type(affordance_ttl_ms) is not int or affordance_ttl_ms <= 0:
            raise ValueError("affordance_ttl_ms must be a positive integer")

        self.controlled_party_ids = parties
        self.order_options = options
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._affordance_ttl_ms = affordance_ttl_ms
        self._revision = 0
        self._snapshot_fingerprint = None
        self._refresh_commands = {}
        self._commands_by_action_id = {}
        self._lock = threading.RLock()
        now_ms = self._now()
        expires_at_ms = now_ms + grant_ttl_ms
        self.controller = ActorRef(f"controller:{session_id}", ActorKind.SYSTEM)
        self.faction = ActorRef(
            f"faction:{self.faction_id}", ActorKind.FACTION, self.faction_id
        )
        self.parties = {
            party_id: ActorRef(f"party:{party_id}", ActorKind.PARTY, party_id)
            for party_id in parties
        }
        self.grant = RoleGrant(
            "grant:" + secrets.token_urlsafe(18),
            RoleId.FACTION_SOVEREIGN,
            self.controller,
            (AuthorityClass.OBSERVE, AuthorityClass.PARTY_COMMAND),
            "faction.sovereign",
            ("party.strategy",),
            now_ms,
            expires_at_ms,
        )
        self.leases = LeaseBook()
        self.party_leases = {
            party_id: self.leases.acquire(
                self.controller,
                party,
                ("party.strategy",),
                LeaseMode.EXCLUSIVE,
                now_ms,
                expires_at_ms,
            )
            for party_id, party in self.parties.items()
        }
        self.registry = CapabilityRegistry(token_factory, self.leases.resolve)
        register_party_order_capabilities(self.registry)
        filters = ObservationFilter()
        for policy in default_perception_policies():
            filters.register(policy)
        self.session = ConstrainedAgentSession(
            session_id,
            self.grant,
            self.registry,
            filters,
            self._canonical_observation,
            self._issue_affordances,
            self._dispatch,
            self._select_lease,
            event_log,
            clock_ms=self._clock_ms,
            action_id_factory=action_id_factory,
            outcome_refresher=self._refresh_outcome,
        )

    @property
    def refresh_command_ids(self):
        with self._lock:
            return tuple(self._refresh_commands.values())

    def _now(self):
        value = self._clock_ms()
        if type(value) is not int or value < 0:
            raise ValueError("clock must return a non-negative integer")
        return value

    def _campaign_snapshot(self):
        snapshot = self.store.snapshot()
        if (
            not snapshot.get("connected")
            or snapshot.get("protocol") != 2
            or snapshot.get("context") != "campaign"
        ):
            raise ValueError(
                "Faction agents require live protocol-2 campaign telemetry"
            )
        return snapshot

    def queue_observation_refresh(self):
        """Queue exact engine getter reads for every party in this decision view."""
        self._campaign_snapshot()
        party_ids = sorted(
            set(self.controlled_party_ids)
            | {item.target_party_id for item in self.order_options}
        )
        if len(party_ids) > 32:
            raise ValueError("Faction decision view exceeds the bridge queue bound")
        commands = {}
        for party_id in party_ids:
            command = self.store.enqueue_operation(
                "world_query",
                {"entity": "party", "entity_id": party_id, "other_id": 0},
            )
            commands[party_id] = command["id"]
        with self._lock:
            self._refresh_commands = commands
            self._snapshot_fingerprint = None
        return dict(commands)

    def _current_world_results(self):
        with self._lock:
            commands = dict(self._refresh_commands)
        expected = set(self.controlled_party_ids) | {
            item.target_party_id for item in self.order_options
        }
        if set(commands) != expected:
            raise RuntimeError("Fresh faction observation has not been requested")
        results = {}
        for party_id, command_id in commands.items():
            command = self.store.command(command_id)
            result = self.store.world_result(command_id)
            if command["status"] != "acknowledged" or not result.get("complete"):
                raise RuntimeError("Fresh faction observation is still pending")
            facts = result.get("facts", {})
            if facts.get("party_id") != party_id:
                raise ValueError("Faction observation returned another party")
            if (
                party_id in self.parties
                and facts.get("faction_id") != self.faction_id
            ):
                raise ValueError(
                    f"Controlled party {party_id} does not belong to faction "
                    f"{self.faction_id}"
                )
            results[party_id] = result
        return results

    def _canonical_observation(self):
        snapshot = self._campaign_snapshot()
        results = self._current_world_results()
        fingerprint = json.dumps(
            {
                "context": snapshot["context"],
                "clock": snapshot.get("clock"),
                "captive": snapshot.get("player_is_captive"),
                "faction_id": self.faction_id,
                "world": {
                    str(party_id): result["facts"]
                    for party_id, result in sorted(results.items())
                },
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._lock:
            if fingerprint != self._snapshot_fingerprint:
                self._revision += 1
                self._snapshot_fingerprint = fingerprint
            revision = self._revision
        context = context_from_snapshot(snapshot, revision)
        if context.kind is not ContextKind.CAMPAIGN:
            raise ValueError("Faction observation escaped campaign context")
        facts = [
            Fact(
                "self.faction_id",
                self.faction_id,
                FactSource.APPLICATION_MEMORY,
                revision,
            )
        ]
        faction_name = self.store.module_catalog.get("factions", {}).get(
            str(self.faction_id)
        )
        if faction_name:
            facts.append(
                Fact(
                    "faction.name",
                    faction_name,
                    FactSource.DEFINITION_METADATA,
                    revision,
                )
            )
        for party_id, result in sorted(results.items()):
            party_name = self.store.module_catalog.get("parties", {}).get(str(party_id))
            if party_name:
                facts.append(
                    Fact(
                        f"parties.{party_id}.name",
                        party_name,
                        FactSource.DEFINITION_METADATA,
                        revision,
                    )
                )
            facts.extend(party_facts_from_world_result(result, revision))
            if party_id in self.parties:
                facts.append(
                    Fact(
                        f"parties.{party_id}.controlled",
                        True,
                        FactSource.APPLICATION_MEMORY,
                        revision,
                    )
                )
        return ObservationEnvelope(
            f"faction:{self.faction_id}:revision:{revision}",
            self.controller,
            RoleId.OPERATOR_FULL,
            context,
            tuple(facts),
            (),
            self._now(),
        )

    def _issue_affordances(self, registry, grant, observation, now_ms):
        expires_at_ms = min(
            now_ms + self._affordance_ttl_ms,
            grant.expires_at_ms,
            *(lease.expires_at_ms for lease in self.party_leases.values()),
        )
        return tuple(
            issue_party_order_affordance(
                registry,
                self.controller,
                self.parties[option.party_id],
                ActorRef(
                    f"party:{option.target_party_id}",
                    ActorKind.PARTY,
                    option.target_party_id,
                ),
                option.order,
                option.title,
                observation.context,
                grant,
                now_ms,
                expires_at_ms,
            )
            for option in self.order_options
        )

    def _select_lease(self, affordance):
        party_id = affordance.targets[0].game_id
        return self.party_leases[party_id].lease_id

    def _dispatch(self, validated):
        operation = party_operation_from_validated(validated)
        command = self.store.enqueue_operation(
            operation["operation"], dict(operation["arguments"])
        )
        self._commands_by_action_id[validated.submission.action_id] = command["id"]
        return ActionOutcome(
            validated.submission.action_id,
            ActionState.ACCEPTED,
            validated.affordance.context,
            None,
            {"status": command["status"]},
            (),
            (
                Evidence(
                    EvidenceLevel.DECLARED,
                    "Warband bridge command queue",
                    "The exact faction party order was queued",
                ),
            ),
            None,
            self._now(),
        )

    def _refresh_outcome(self, _request_id, previous):
        if previous.state is ActionState.OBSERVED:
            return previous
        command_id = self._commands_by_action_id[previous.action_id]
        command = self.store.command(command_id)
        result = self.store.world_result(command_id)
        if result.get("complete"):
            revision = max(previous.context.revision + 1, self._revision + 1)
            facts = party_facts_from_world_result(result, revision)
            return ActionOutcome(
                previous.action_id,
                ActionState.OBSERVED,
                previous.context,
                revision,
                {
                    "status": command["status"],
                    "result": command["result"],
                    "readback": result["facts"],
                },
                facts,
                (
                    Evidence(
                        EvidenceLevel.ENGINE_OBSERVED,
                        "Warband party getters",
                        "Party AI behavior and target were read back after the order",
                    ),
                ),
                None,
                self._now(),
            )
        states = {
            "queued": ActionState.ACCEPTED,
            "dispatched": ActionState.DISPATCHED,
            "acknowledged": ActionState.ACKNOWLEDGED,
            "rejected": ActionState.REJECTED,
            "expired": ActionState.EXPIRED,
            "interrupted": ActionState.INTERRUPTED,
        }
        state = states[command["status"]]
        engine_acknowledged = state is ActionState.ACKNOWLEDGED or (
            state is ActionState.REJECTED and command["result"] not in (None, -2, -3)
        )
        engine_result = {"status": command["status"]}
        if command["result"] is not None:
            engine_result["result"] = command["result"]
        if state is previous.state and dict(previous.engine_result) == engine_result:
            return previous
        return ActionOutcome(
            previous.action_id,
            state,
            previous.context,
            None,
            engine_result,
            (),
            (
                Evidence(
                    EvidenceLevel.ENGINE_ACKNOWLEDGED
                    if engine_acknowledged
                    else EvidenceLevel.DECLARED,
                    "Warband protocol-2 acknowledgement"
                    if engine_acknowledged
                    else "Warband bridge command lifecycle",
                    "The game returned the command ID and result"
                    if engine_acknowledged
                    else f"The bridge reports command status {command['status']}",
                ),
            ),
            f"Bridge command became {command['status']}"
            if state
            in (ActionState.REJECTED, ActionState.EXPIRED, ActionState.INTERRUPTED)
            else None,
            self._now(),
        )
