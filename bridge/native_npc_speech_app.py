"""Constrained one-turn NPC speech over the proven Native dialogue UI seam."""

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
    SpeechRequest,
    VoiceDelivery,
    context_from_snapshot,
    default_perception_policies,
    issue_npc_speech_affordance,
    npc_speech_operation_from_validated,
    register_npc_speech_capability,
)


class NativeNpcSpeechApplication:
    """Bind an npc.self session to one live, freshly scanned scene agent."""

    def __init__(
        self,
        store,
        session_id,
        *,
        agent_id,
        event_log=None,
        clock_ms=None,
        token_factory=None,
        action_id_factory=None,
        grant_ttl_ms=30 * 60 * 1000,
        affordance_ttl_ms=15_000,
    ):
        for name in (
            "snapshot",
            "enqueue_operation",
            "command",
            "scan_result",
            "dialogue_result",
        ):
            if not callable(getattr(store, name, None)):
                raise TypeError(f"store must provide {name}()")
        if type(agent_id) is not int or not 0 <= agent_id < 10_000:
            raise ValueError("agent_id must be a bounded non-negative integer")
        if type(grant_ttl_ms) is not int or grant_ttl_ms <= 0:
            raise ValueError("grant_ttl_ms must be a positive integer")
        if type(affordance_ttl_ms) is not int or affordance_ttl_ms <= 0:
            raise ValueError("affordance_ttl_ms must be a positive integer")
        self.store = store
        self.agent_id = agent_id
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._affordance_ttl_ms = affordance_ttl_ms
        self._revision = 0
        self._snapshot_fingerprint = None
        self._refresh_command_id = None
        self._commands_by_action_id = {}
        self._lock = threading.RLock()
        now_ms = self._now()
        expires_at_ms = now_ms + grant_ttl_ms
        self.controller = ActorRef(f"controller:{session_id}", ActorKind.SYSTEM)
        self.npc = ActorRef(f"agent:{agent_id}", ActorKind.AGENT, agent_id)
        self.grant = RoleGrant(
            "grant:" + secrets.token_urlsafe(18),
            RoleId.NPC_SELF,
            self.controller,
            (AuthorityClass.OBSERVE, AuthorityClass.ACTOR_CONTROL),
            "npc.self",
            ("npc.dialogue",),
            now_ms,
            expires_at_ms,
        )
        self.leases = LeaseBook()
        self.lease = self.leases.acquire(
            self.controller,
            self.npc,
            ("npc.dialogue",),
            LeaseMode.EXCLUSIVE,
            now_ms,
            expires_at_ms,
        )
        self.registry = CapabilityRegistry(token_factory, self.leases.resolve)
        register_npc_speech_capability(self.registry)
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

    def voice_request(
        self,
        request_id,
        profile_id,
        *,
        delivery=VoiceDelivery.SYNTHESIZE_ONLY,
        speed=1.0,
    ):
        """Build a voice request only after Warband observed the utterance."""
        outcome = self.session.outcome(request_id)
        if outcome.state is not ActionState.OBSERVED:
            raise RuntimeError("NPC speech is not yet observed in Warband")
        command_id = self._commands_by_action_id[outcome.action_id]
        command = self.store.command(command_id)
        return SpeechRequest(
            f"speech:{outcome.action_id}",
            command["arguments"]["text"],
            profile_id,
            delivery,
            speed,
            "wav",
            outcome.action_id,
        )

    def _now(self):
        value = self._clock_ms()
        if type(value) is not int or value < 0:
            raise ValueError("clock must return a non-negative integer")
        return value

    def _mission_snapshot(self):
        snapshot = self.store.snapshot()
        if (
            not snapshot.get("connected")
            or snapshot.get("protocol") != 2
            or snapshot.get("context") != "mission"
        ):
            raise ValueError("NPC speech requires live protocol-2 mission telemetry")
        if snapshot.get("dialogue_active"):
            raise ValueError("NPC speech is unavailable during active dialogue")
        if (snapshot.get("mission_flags") or 0) & 2:
            raise ValueError("NPC speech is unavailable during battle missions")
        return snapshot

    def queue_observation_refresh(self):
        """Queue the normal scene census required before targeting an NPC."""
        self._mission_snapshot()
        command = self.store.enqueue_operation("scan_agents", {})
        with self._lock:
            self._refresh_command_id = command["id"]
            self._snapshot_fingerprint = None
        return command["id"]

    def _current_agent(self, snapshot):
        with self._lock:
            command_id = self._refresh_command_id
        if command_id is None:
            raise RuntimeError("Fresh scene-agent observation has not been requested")
        command = self.store.command(command_id)
        scan = self.store.scan_result(command_id)
        if command["status"] != "acknowledged" or not scan.get("complete"):
            raise RuntimeError("Fresh scene-agent observation is still pending")
        if (
            scan.get("scene_id") != snapshot.get("scene_id")
            or scan.get("mission_session") != snapshot.get("mission_session")
            or scan.get("age_seconds", 31) >= 30
        ):
            raise ValueError("Scene-agent observation is stale or out of scope")
        agent = next(
            (item for item in scan["agents"] if item.get("agent_id") == self.agent_id),
            None,
        )
        if agent is None:
            raise ValueError("Controlled NPC is not present in the fresh scene census")
        if agent.get("is_player"):
            raise ValueError("The player agent cannot be controlled as an NPC")
        if agent.get("hit_points", 0) <= 0:
            raise ValueError("A dead NPC cannot speak")
        return agent

    def _canonical_observation(self):
        snapshot = self._mission_snapshot()
        agent = self._current_agent(snapshot)
        fingerprint = json.dumps(
            {
                "scene": snapshot.get("scene_id"),
                "session": snapshot.get("mission_session"),
                "dialogue": snapshot.get("dialogue_active"),
                "agent": agent,
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
        if context.kind is not ContextKind.MISSION:
            raise ValueError("NPC observation escaped mission context")
        facts = []
        for name in ("agent_id", "troop_id", "name", "team", "hit_points", "position"):
            if agent.get(name) is not None:
                facts.append(
                    Fact(
                        f"self.{name}",
                        agent[name],
                        FactSource.DEFINITION_METADATA
                        if name == "name"
                        else FactSource.ENGINE_OBSERVED,
                        revision,
                    )
                )
        facts.append(
            Fact(
                "scene.id",
                snapshot["scene_id"],
                FactSource.ENGINE_OBSERVED,
                revision,
            )
        )
        return ObservationEnvelope(
            f"npc:{self.agent_id}:revision:{revision}",
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
            self.lease.expires_at_ms,
        )
        return (
            issue_npc_speech_affordance(
                registry,
                self.controller,
                self.npc,
                observation.context,
                grant,
                now_ms,
                expires_at_ms,
            ),
        )

    def _dispatch(self, validated):
        operation = npc_speech_operation_from_validated(validated)
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
                    "The bounded NPC utterance was queued",
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
        dialogue = self.store.dialogue_result(command_id)
        if dialogue.get("event") in ("opened", "closed"):
            revision = max(previous.context.revision + 1, self._revision + 1)
            event = dialogue["event"]
            return ActionOutcome(
                previous.action_id,
                ActionState.OBSERVED,
                previous.context,
                revision,
                {"status": command["status"], "dialogue_event": event},
                (
                    Fact(
                        "dialogue.state",
                        event,
                        FactSource.ENGINE_OBSERVED,
                        revision,
                    ),
                ),
                (
                    Evidence(
                        EvidenceLevel.ENGINE_OBSERVED,
                        "Warband dialogue event",
                        f"The one-turn NPC dialogue was {event}",
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
