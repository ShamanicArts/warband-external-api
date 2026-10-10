"""Production composition for constrained Native menu agents."""

import json
import secrets
import threading
import time

from warband_agentic import (
    ActionOutcome,
    ActionState,
    ActorKind,
    ActorRef,
    AuthorityClass,
    CapabilityRegistry,
    ConstrainedAgentSession,
    Evidence,
    EvidenceLevel,
    LeaseBook,
    LeaseMode,
    ObservationFilter,
    RoleGrant,
    RoleId,
    canonical_observation_from_snapshot,
    default_perception_policies,
    issue_menu_affordances,
    menu_operation_from_validated,
    register_menu_capability,
)


class NativeMenuAgentApplication:
    """Bind one constrained player-strategic session to a live bridge Store."""

    def __init__(
        self,
        store,
        session_id,
        *,
        event_log=None,
        clock_ms=None,
        token_factory=None,
        action_id_factory=None,
        grant_ttl_ms=30 * 60 * 1000,
        affordance_ttl_ms=15_000,
    ):
        for name in ("snapshot", "menu_options", "enqueue_operation"):
            if not callable(getattr(store, name, None)):
                raise TypeError(f"store must provide {name}()")
        if type(grant_ttl_ms) is not int or grant_ttl_ms <= 0:
            raise ValueError("grant_ttl_ms must be a positive integer")
        if type(affordance_ttl_ms) is not int or affordance_ttl_ms <= 0:
            raise ValueError("affordance_ttl_ms must be a positive integer")

        self.store = store
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._affordance_ttl_ms = affordance_ttl_ms
        self._revision = 0
        self._snapshot_fingerprint = None
        self._commands_by_action_id = {}
        self._lock = threading.RLock()
        now_ms = self._now()
        initial = self._canonical_observation()
        self.controller = ActorRef(
            f"controller:{session_id}", ActorKind.SYSTEM
        )
        self.player = initial.actor
        expires_at_ms = now_ms + grant_ttl_ms
        self.grant = RoleGrant(
            "grant:" + secrets.token_urlsafe(18),
            RoleId.PLAYER_STRATEGIC,
            self.controller,
            (AuthorityClass.OBSERVE, AuthorityClass.ACTOR_CONTROL),
            "player.strategic",
            ("player.menu",),
            now_ms,
            expires_at_ms,
        )
        self.leases = LeaseBook()
        self.lease = self.leases.acquire(
            self.controller,
            self.player,
            ("player.menu",),
            LeaseMode.EXCLUSIVE,
            now_ms,
            expires_at_ms,
        )
        self.registry = CapabilityRegistry(token_factory, self.leases.resolve)
        register_menu_capability(self.registry)
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
            lambda _affordance: self.lease.lease_id,
            event_log,
            clock_ms=self._clock_ms,
            action_id_factory=action_id_factory,
            outcome_refresher=self._refresh_outcome,
        )

    def _now(self):
        value = self._clock_ms()
        if type(value) is not int or value < 0:
            raise ValueError("clock must return a non-negative integer")
        return value

    def _canonical_observation(self):
        snapshot = self.store.snapshot()
        fingerprint_payload = {
            key: value
            for key, value in snapshot.items()
            if key
            not in ("age_seconds", "http_diagnostics", "received_at", "source")
        }
        fingerprint = json.dumps(
            fingerprint_payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._lock:
            if fingerprint != self._snapshot_fingerprint:
                self._revision += 1
                self._snapshot_fingerprint = fingerprint
            revision = self._revision
        observation = canonical_observation_from_snapshot(
            snapshot,
            revision,
            f"native-menu:{revision}",
            self._now(),
        )
        if hasattr(self, "player") and observation.actor != self.player:
            raise ValueError("Player identity changed during the agent session")
        return observation

    def _issue_affordances(self, registry, grant, observation, now_ms):
        expires_at_ms = min(
            now_ms + self._affordance_ttl_ms,
            grant.expires_at_ms,
            self.lease.expires_at_ms,
        )
        return issue_menu_affordances(
            registry,
            self.store.menu_options(),
            self.controller,
            self.player,
            observation.context,
            grant,
            now_ms,
            expires_at_ms,
        )

    def _dispatch(self, validated):
        operation = menu_operation_from_validated(validated)
        command = self.store.enqueue_operation(
            operation["operation"], dict(operation["arguments"])
        )
        self._commands_by_action_id[
            validated.submission.action_id
        ] = command["id"]
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
                    "The exact-session Native menu attempt was queued",
                ),
            ),
            None,
            self._now(),
        )

    def _refresh_outcome(self, _request_id, previous):
        command_id = self._commands_by_action_id[previous.action_id]
        command = self.store.command(command_id)
        states = {
            "queued": ActionState.ACCEPTED,
            "dispatched": ActionState.DISPATCHED,
            "acknowledged": ActionState.ACKNOWLEDGED,
            "rejected": ActionState.REJECTED,
            "expired": ActionState.EXPIRED,
            "interrupted": ActionState.INTERRUPTED,
        }
        state = states[command["status"]]
        engine_result = {"status": command["status"]}
        if command["result"] is not None:
            engine_result["result"] = command["result"]
        if (
            state is previous.state
            and dict(previous.engine_result) == engine_result
        ):
            return previous
        engine_acknowledged = state is ActionState.ACKNOWLEDGED or (
            state is ActionState.REJECTED
            and command["result"] not in (None, -2, -3)
        )
        evidence = Evidence(
            EvidenceLevel.ENGINE_ACKNOWLEDGED
            if engine_acknowledged
            else EvidenceLevel.DECLARED,
            "Warband protocol-2 acknowledgement"
            if engine_acknowledged
            else "Warband bridge command lifecycle",
            "The game returned the command ID and result"
            if engine_acknowledged
            else f"The bridge reports command status {command['status']}",
        )
        reason = (
            f"Bridge command became {command['status']}"
            if state
            in (ActionState.REJECTED, ActionState.EXPIRED, ActionState.INTERRUPTED)
            else None
        )
        return ActionOutcome(
            previous.action_id,
            state,
            previous.context,
            None,
            engine_result,
            (),
            (evidence,),
            reason,
            self._now(),
        )
