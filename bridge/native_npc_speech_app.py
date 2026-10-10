"""Constrained NPC speech and persistent host-fed dialogue over the Native UI."""

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
    GameEvent,
    LeaseBook,
    LeaseMode,
    ObservationEnvelope,
    ObservationFilter,
    RoleGrant,
    RoleId,
    SemanticEventLog,
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
        conversation_mode=False,
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
        if type(conversation_mode) is not bool:
            raise TypeError("conversation_mode must be boolean")
        if event_log is not None and not isinstance(event_log, SemanticEventLog):
            raise TypeError("event_log must be a SemanticEventLog")
        if type(grant_ttl_ms) is not int or grant_ttl_ms <= 0:
            raise ValueError("grant_ttl_ms must be a positive integer")
        if type(affordance_ttl_ms) is not int or affordance_ttl_ms <= 0:
            raise ValueError("affordance_ttl_ms must be a positive integer")
        self.store = store
        self.agent_id = agent_id
        self.conversation_mode = conversation_mode
        self._event_log = event_log
        self._session_id = session_id
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._affordance_ttl_ms = affordance_ttl_ms
        self._revision = 0
        self._snapshot_fingerprint = None
        self._refresh_command_id = None
        self._commands_by_action_id = {}
        self._conversation_turns = []
        self._conversation_by_id = {}
        self._pending_utterance_id = None
        self._pending_response_action_id = None
        self._utterances_by_action_id = {}
        self._rejected_response_action_ids = set()
        self._conversation_generation = 0
        self._lock = threading.RLock()
        now_ms = self._now()
        expires_at_ms = now_ms + grant_ttl_ms
        self.controller = ActorRef(f"controller:{session_id}", ActorKind.SYSTEM)
        self.npc = ActorRef(f"agent:{agent_id}", ActorKind.AGENT, agent_id)
        self.player = ActorRef("player", ActorKind.PLAYER)
        if self.conversation_mode and self._event_log is not None:
            self._restore_conversation()
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
            recovery_exporter=self._export_recovery,
            recovery_importer=self._import_recovery,
        )

    def receive_player_utterance(self, utterance_id, text):
        """Add one trusted player utterance to a bounded NPC conversation."""
        if not self.conversation_mode:
            raise RuntimeError("NPC application is not in conversation mode")
        if (
            not isinstance(utterance_id, str)
            or not utterance_id.strip()
            or len(utterance_id) > 200
            or not utterance_id.isprintable()
        ):
            raise ValueError("utterance_id must be 1-200 printable characters")
        if (
            not isinstance(text, str)
            or not 1 <= len(text) <= 500
            or not text.isprintable()
            or any(character in text for character in "\r\n\x00")
        ):
            raise ValueError("player utterance must be 1-500 printable characters")
        snapshot = self._mission_snapshot()
        self._current_agent(snapshot)
        with self._lock:
            existing = self._conversation_by_id.get(utterance_id)
            if existing is not None:
                if existing["player_text"] != text:
                    raise ValueError("utterance_id was reused with different text")
                return self._utterance_receipt(existing, inserted=False)
            if self._pending_utterance_id is not None:
                raise RuntimeError("The previous NPC response is still pending")
            if len(self._conversation_turns) >= 64:
                raise RuntimeError("NPC conversation reached its 64-turn limit")
            turn = {
                "utterance_id": utterance_id,
                "player_text": text,
                "npc_text": None,
            }
            if self._event_log is not None:
                context = context_from_snapshot(snapshot, self._revision + 1)
                self._event_log.append(
                    GameEvent(
                        0,
                        "dialogue.player-utterance",
                        context,
                        (self.player, self.npc),
                        {
                            "agent_session_id": self._session_id,
                            "utterance_id": utterance_id,
                            "speaker": "player",
                            "text": text,
                        },
                        Evidence(
                            EvidenceLevel.DECLARED,
                            "authenticated host conversation input",
                            "A trusted host supplied the player's bounded utterance",
                        ),
                        self._now(),
                    ),
                    f"npc-conversation:{self._session_id}:player:{utterance_id}",
                )
            self._conversation_turns.append(turn)
            self._conversation_by_id[utterance_id] = turn
            self._pending_utterance_id = utterance_id
            return self._utterance_receipt(turn, inserted=True)

    @staticmethod
    def _utterance_receipt(turn, *, inserted):
        return {
            "schema": "warband.agentic/npc-utterance/v1",
            "utterance_id": turn["utterance_id"],
            "status": "responded" if turn["npc_text"] is not None else "pending",
            "inserted": inserted,
        }

    def _restore_conversation(self):
        cursor = 0
        while True:
            page = self._event_log.read(cursor, 1000)
            for event in page.events:
                payload = event.payload
                if payload.get("agent_session_id") != self._session_id:
                    continue
                if event.event_type == "dialogue.player-utterance":
                    if (
                        set(payload)
                        != {
                            "agent_session_id",
                            "utterance_id",
                            "speaker",
                            "text",
                        }
                        or payload.get("speaker") != "player"
                    ):
                        raise ValueError("Invalid recovered player utterance")
                    utterance_id = payload["utterance_id"]
                    text = payload["text"]
                    if not isinstance(utterance_id, str) or not isinstance(text, str):
                        raise ValueError("Invalid recovered player utterance")
                    existing = self._conversation_by_id.get(utterance_id)
                    if existing is not None:
                        if existing["player_text"] != text:
                            raise ValueError("Conflicting recovered player utterance")
                        continue
                    turn = {
                        "utterance_id": utterance_id,
                        "player_text": text,
                        "npc_text": None,
                    }
                    self._conversation_turns.append(turn)
                    self._conversation_by_id[utterance_id] = turn
                elif event.event_type == "dialogue.npc-utterance":
                    if (
                        set(payload)
                        != {
                            "agent_session_id",
                            "utterance_id",
                            "speaker",
                            "text",
                        }
                        or payload.get("speaker") != "npc"
                    ):
                        raise ValueError("Invalid recovered NPC utterance")
                    turn = self._conversation_by_id.get(payload["utterance_id"])
                    if turn is None:
                        raise ValueError("Recovered NPC utterance has no player input")
                    if turn["npc_text"] not in (None, payload["text"]):
                        raise ValueError("Conflicting recovered NPC utterance")
                    turn["npc_text"] = payload["text"]
                elif event.event_type == "dialogue.npc-response-rejected":
                    if (
                        set(payload)
                        != {
                            "agent_session_id",
                            "utterance_id",
                            "status",
                        }
                        or payload.get("status") != "rejected"
                    ):
                        raise ValueError("Invalid recovered NPC response rejection")
                    if payload.get("utterance_id") not in self._conversation_by_id:
                        raise ValueError("Recovered rejection has no player input")
                    if event.cause_action_id is None:
                        raise ValueError("Recovered rejection has no action ID")
                    self._rejected_response_action_ids.add(event.cause_action_id)
            if (
                page.next_sequence == cursor
                or page.next_sequence >= page.high_watermark
            ):
                break
            cursor = page.next_sequence
        pending = [
            turn["utterance_id"]
            for turn in self._conversation_turns
            if turn["npc_text"] is None
        ]
        if len(pending) > 1 or len(self._conversation_turns) > 64:
            raise ValueError("Recovered NPC conversation violates turn bounds")
        self._pending_utterance_id = pending[0] if pending else None

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
        with self._lock:
            pending = (
                self._conversation_by_id[self._pending_utterance_id].copy()
                if self._pending_utterance_id is not None
                else None
            )
            memory = []
            for turn in self._conversation_turns[-8:]:
                if turn["npc_text"] is None:
                    continue
                memory.extend(
                    (
                        {"speaker": "player", "text": turn["player_text"]},
                        {"speaker": "npc", "text": turn["npc_text"]},
                    )
                )
            pending_response = self._pending_response_action_id is not None
            conversation_generation = self._conversation_generation
        fingerprint = json.dumps(
            {
                "scene": snapshot.get("scene_id"),
                "session": snapshot.get("mission_session"),
                "dialogue": snapshot.get("dialogue_active"),
                "agent": agent,
                "pending_utterance": pending,
                "pending_response": pending_response,
                "conversation_generation": conversation_generation,
                "conversation_memory": memory,
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
        if self.conversation_mode:
            if pending is not None:
                facts.append(
                    Fact(
                        "dialogue.pending_utterance",
                        {
                            "utterance_id": pending["utterance_id"],
                            "speaker": "player",
                            "text": pending["player_text"],
                        },
                        FactSource.APPLICATION_MEMORY,
                        revision,
                    )
                )
            facts.append(
                Fact(
                    "memory.conversation",
                    memory,
                    FactSource.APPLICATION_MEMORY,
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
        with self._lock:
            if self.conversation_mode and (
                self._pending_utterance_id is None
                or self._pending_response_action_id is not None
            ):
                return ()
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
        with self._lock:
            if self.conversation_mode and (
                self._pending_utterance_id is None
                or self._pending_response_action_id is not None
            ):
                raise RuntimeError("No player utterance awaits a new NPC response")
        operation = npc_speech_operation_from_validated(validated)
        command = self.store.enqueue_operation(
            operation["operation"], dict(operation["arguments"])
        )
        self._commands_by_action_id[validated.submission.action_id] = command["id"]
        with self._lock:
            if self.conversation_mode:
                if self._pending_utterance_id is None:
                    raise RuntimeError(
                        "No player utterance is awaiting an NPC response"
                    )
                self._utterances_by_action_id[validated.submission.action_id] = (
                    self._pending_utterance_id
                )
                self._pending_response_action_id = validated.submission.action_id
                self._conversation_generation += 1
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

    def _export_recovery(self, validated, _outcome):
        recovery = {
            "command_id": self._commands_by_action_id[validated.submission.action_id]
        }
        if self.conversation_mode:
            recovery["utterance_id"] = self._utterances_by_action_id[
                validated.submission.action_id
            ]
        return recovery

    def _import_recovery(self, action_id, recovery):
        expected = (
            {"command_id", "utterance_id"} if self.conversation_mode else {"command_id"}
        )
        if set(recovery) != expected or type(recovery["command_id"]) is not int:
            raise ValueError("Invalid NPC-speech command recovery metadata")
        command_id = recovery["command_id"]
        self.store.command(command_id)
        previous = self._commands_by_action_id.setdefault(action_id, command_id)
        if previous != command_id:
            raise ValueError("Conflicting NPC-speech command recovery metadata")
        if self.conversation_mode:
            utterance_id = recovery["utterance_id"]
            if (
                not isinstance(utterance_id, str)
                or utterance_id not in self._conversation_by_id
            ):
                raise ValueError("Invalid NPC-conversation recovery metadata")
            previous_utterance = self._utterances_by_action_id.setdefault(
                action_id, utterance_id
            )
            if previous_utterance != utterance_id:
                raise ValueError("Conflicting NPC-conversation recovery metadata")
            if (
                action_id not in self._rejected_response_action_ids
                and self._conversation_by_id[utterance_id]["npc_text"] is None
            ):
                if self._pending_response_action_id not in (None, action_id):
                    raise ValueError("Multiple recovered NPC responses are in flight")
                self._pending_response_action_id = action_id

    def _refresh_outcome(self, _request_id, previous):
        if previous.state is ActionState.OBSERVED:
            return previous
        command_id = self._commands_by_action_id[previous.action_id]
        command = self.store.command(command_id)
        dialogue = self.store.dialogue_result(command_id)
        if dialogue.get("event") in ("opened", "closed"):
            revision = max(previous.context.revision + 1, self._revision + 1)
            event = dialogue["event"]
            if self.conversation_mode:
                self._record_conversation_response(
                    previous,
                    command["arguments"]["text"],
                    event,
                )
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
        if (
            self.conversation_mode
            and state is ActionState.REJECTED
            and previous.state is not ActionState.REJECTED
        ):
            self._record_rejected_response(previous, command)
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

    def _record_conversation_response(self, previous, text, dialogue_event):
        with self._lock:
            utterance_id = self._utterances_by_action_id[previous.action_id]
            turn = self._conversation_by_id[utterance_id]
            if turn["npc_text"] not in (None, text):
                raise ValueError("NPC response conflicts with conversation memory")
            if turn["npc_text"] == text:
                if self._pending_response_action_id == previous.action_id:
                    self._pending_response_action_id = None
                    self._conversation_generation += 1
                if self._pending_utterance_id == utterance_id:
                    self._pending_utterance_id = None
                return
            if self._event_log is not None:
                self._event_log.append(
                    GameEvent(
                        0,
                        "dialogue.npc-utterance",
                        previous.context,
                        (self.npc, self.player),
                        {
                            "agent_session_id": self._session_id,
                            "utterance_id": utterance_id,
                            "speaker": "npc",
                            "text": text,
                        },
                        Evidence(
                            EvidenceLevel.ENGINE_OBSERVED,
                            "Warband dialogue event",
                            f"The bounded NPC response was {dialogue_event}",
                        ),
                        self._now(),
                        previous.action_id,
                    ),
                    f"npc-conversation:{self._session_id}:npc:{previous.action_id}",
                )
            turn["npc_text"] = text
            if self._pending_response_action_id == previous.action_id:
                self._pending_response_action_id = None
                self._conversation_generation += 1
            if self._pending_utterance_id == utterance_id:
                self._pending_utterance_id = None

    def _record_rejected_response(self, previous, command):
        with self._lock:
            utterance_id = self._utterances_by_action_id[previous.action_id]
            if self._event_log is not None:
                self._event_log.append(
                    GameEvent(
                        0,
                        "dialogue.npc-response-rejected",
                        previous.context,
                        (self.npc, self.player),
                        {
                            "agent_session_id": self._session_id,
                            "utterance_id": utterance_id,
                            "status": "rejected",
                        },
                        Evidence(
                            EvidenceLevel.ENGINE_ACKNOWLEDGED
                            if command["result"] not in (None, -2, -3)
                            else EvidenceLevel.DECLARED,
                            "Warband bridge command lifecycle",
                            "The NPC response was rejected without display evidence",
                        ),
                        self._now(),
                        previous.action_id,
                    ),
                    f"npc-conversation:{self._session_id}:rejected:"
                    f"{previous.action_id}",
                )
            self._rejected_response_action_ids.add(previous.action_id)
            if self._pending_response_action_id == previous.action_id:
                self._pending_response_action_id = None
                self._conversation_generation += 1
