import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.game_bridge import Store
from bridge.native_npc_speech_app import NativeNpcSpeechApplication
from bridge.test_game_bridge import mission_telemetry
from warband_agentic import (
    ActionState,
    EvidenceLevel,
    RiskClass,
    SemanticEventLog,
    VoiceDelivery,
    to_wire,
)


class NativeNpcSpeechApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(
            Path(self.temp.name) / "bridge.sqlite3",
            {"troops": {"0": "Player", "1": "Trainer"}},
        )
        self.query = mission_telemetry()
        self.store.poll(self.query)
        self.app = NativeNpcSpeechApplication(
            self.store,
            "session:trainer:1",
            agent_id=1,
            clock_ms=lambda: 1000,
            token_factory=lambda: "affordance:speak",
            action_id_factory=lambda request_id: f"action:{request_id}",
        )

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def _complete_agent_refresh(self):
        command_id = self.app.queue_observation_refresh()
        fields = self.store.poll(self.query).split("|")
        self.assertEqual(int(fields[2]), command_id)
        self.assertEqual(fields[3], "2")
        event = {"v": "2", "job": str(command_id), "scene": "42", "session": "1"}
        self.store.event("/agents_end", {**event, "count": "2"})
        for agent_id in (0, 1):
            self.store.event(
                "/agent",
                {
                    **event,
                    "id": str(agent_id),
                    "troop": str(agent_id),
                    "team": "0",
                    "hp": "50",
                    "x": "1234",
                    "y": "-500",
                    "z": "0",
                    "player": str(int(agent_id == 0)),
                },
            )
        self.store.poll({**self.query, "ack": str(command_id)})
        return command_id

    def test_turn_is_self_scoped_and_exposes_only_bounded_speech(self):
        refresh_id = self._complete_agent_refresh()

        turn = self.app.session.turn()
        wire = to_wire(turn)
        encoded = json.dumps(wire)
        facts = {fact["key"]: fact["value"] for fact in wire["observation"]["facts"]}
        self.assertEqual(wire["observation"]["role"], "npc.self")
        self.assertEqual(facts["self.agent_id"], 1)
        self.assertEqual(facts["self.troop_id"], 1)
        self.assertEqual(facts["self.name"], "Trainer")
        self.assertEqual(len(turn.affordances), 1)
        self.assertIs(turn.affordances[0].risk, RiskClass.CONSEQUENTIAL)
        text_schema = turn.affordances[0].parameters["properties"]["text"]
        self.assertEqual(text_schema["maxLength"], 200)
        self.assertNotIn("npc_say", encoded)
        self.assertNotIn(str(refresh_id), encoded)

    def test_conversation_mode_answers_one_player_utterance_at_a_time(self):
        tokens = iter(("affordance:conversation:1", "affordance:conversation:2"))
        self.app = NativeNpcSpeechApplication(
            self.store,
            "session:trainer:conversation",
            agent_id=1,
            conversation_mode=True,
            clock_ms=lambda: 1000,
            token_factory=lambda: next(tokens),
            action_id_factory=lambda request_id: f"action:{request_id}",
        )
        self._complete_agent_refresh()
        self.assertEqual(self.app.session.turn().affordances, ())

        receipt = self.app.receive_player_utterance(
            "player-turn:1", "Have you heard any rumours?"
        )

        self.assertEqual(
            receipt,
            {
                "schema": "warband.agentic/npc-utterance/v1",
                "utterance_id": "player-turn:1",
                "status": "pending",
                "inserted": True,
            },
        )
        self.assertFalse(
            self.app.receive_player_utterance(
                "player-turn:1", "Have you heard any rumours?"
            )["inserted"]
        )
        with self.assertRaisesRegex(ValueError, "different text"):
            self.app.receive_player_utterance("player-turn:1", "Changed input")
        turn = self.app.session.turn()
        facts = {
            fact["key"]: fact["value"] for fact in to_wire(turn.observation)["facts"]
        }
        self.assertEqual(
            facts["dialogue.pending_utterance"],
            {
                "utterance_id": "player-turn:1",
                "speaker": "player",
                "text": "Have you heard any rumours?",
            },
        )
        self.assertEqual(len(turn.affordances), 1)
        self.app.session.submit(
            {
                "request_id": "npc-turn:1",
                "affordance_token": turn.affordances[0].token,
                "arguments": {"text": "Caravans have gone missing near Suno."},
                "expected_revision": turn.observation.context.revision,
            }
        )
        with self.assertRaisesRegex(RuntimeError, "response is still pending"):
            self.app.receive_player_utterance("player-turn:2", "Where exactly?")

        command_id = int(self.store.poll(self.query).split("|")[2])
        self.store.event(
            "/dialogue",
            {"v": "2", "job": str(command_id), "event": "1"},
        )
        self.assertIs(
            self.app.session.outcome("npc-turn:1").state,
            ActionState.OBSERVED,
        )
        self.app.receive_player_utterance("player-turn:2", "Where exactly?")
        next_turn = self.app.session.turn()
        next_facts = {
            fact["key"]: fact["value"]
            for fact in to_wire(next_turn.observation)["facts"]
        }
        self.assertEqual(
            next_facts["dialogue.pending_utterance"]["text"], "Where exactly?"
        )
        self.assertEqual(
            next_facts["memory.conversation"][-2:],
            [
                {"speaker": "player", "text": "Have you heard any rumours?"},
                {
                    "speaker": "npc",
                    "text": "Caravans have gone missing near Suno.",
                },
            ],
        )
        self.assertGreater(
            next_turn.observation.context.revision,
            turn.observation.context.revision,
        )

    def test_conversation_memory_recovers_without_replaying_speech(self):
        events_path = Path(self.temp.name) / "conversation-events.sqlite3"
        event_log = SemanticEventLog(events_path)
        self.app = NativeNpcSpeechApplication(
            self.store,
            "session:trainer:persistent-conversation",
            agent_id=1,
            conversation_mode=True,
            event_log=event_log,
            clock_ms=lambda: 1000,
            token_factory=lambda: "affordance:persistent:1",
            action_id_factory=lambda request_id: f"action:{request_id}",
        )
        self._complete_agent_refresh()
        self.app.receive_player_utterance("player-turn:1", "What is your name?")
        turn = self.app.session.turn()
        self.app.session.submit(
            {
                "request_id": "npc-turn:1",
                "affordance_token": turn.affordances[0].token,
                "arguments": {"text": "I am the trainer."},
                "expected_revision": turn.observation.context.revision,
            }
        )
        command_id = int(self.store.poll(self.query).split("|")[2])
        self.store.event(
            "/dialogue",
            {"v": "2", "job": str(command_id), "event": "1"},
        )
        self.assertIs(
            self.app.session.outcome("npc-turn:1").state,
            ActionState.OBSERVED,
        )
        event_types = {event.event_type for event in self.app.session.events().events}
        self.assertIn("dialogue.player-utterance", event_types)
        self.assertIn("dialogue.npc-utterance", event_types)
        self.store.poll({**self.query, "ack": str(command_id)})
        event_log.close()

        reopened_log = SemanticEventLog(events_path)
        try:
            self.app = NativeNpcSpeechApplication(
                self.store,
                "session:trainer:persistent-conversation",
                agent_id=1,
                conversation_mode=True,
                event_log=reopened_log,
                clock_ms=lambda: 1000,
                token_factory=lambda: "affordance:persistent:2",
                action_id_factory=lambda request_id: f"action:{request_id}",
            )
            self._complete_agent_refresh()

            self.app.receive_player_utterance("player-turn:2", "Can you train me?")

            recovered = self.app.session.turn()
            facts = {
                fact["key"]: fact["value"]
                for fact in to_wire(recovered.observation)["facts"]
            }
            self.assertEqual(
                facts["memory.conversation"],
                [
                    {"speaker": "player", "text": "What is your name?"},
                    {"speaker": "npc", "text": "I am the trainer."},
                ],
            )
            self.assertEqual(len(recovered.affordances), 1)
        finally:
            reopened_log.close()

    def test_rejected_conversation_response_can_be_retried_safely(self):
        tokens = iter(("affordance:retry:1", "affordance:retry:2"))
        events_path = Path(self.temp.name) / "rejected-response-events.sqlite3"
        event_log = SemanticEventLog(events_path)
        self.app = NativeNpcSpeechApplication(
            self.store,
            "session:trainer:retry",
            agent_id=1,
            conversation_mode=True,
            event_log=event_log,
            clock_ms=lambda: 1000,
            token_factory=lambda: next(tokens),
            action_id_factory=lambda request_id: f"action:{request_id}",
        )
        self._complete_agent_refresh()
        self.app.receive_player_utterance("player-turn:1", "Can you help me?")
        first_turn = self.app.session.turn()
        self.app.session.submit(
            {
                "request_id": "npc-turn:rejected",
                "affordance_token": first_turn.affordances[0].token,
                "arguments": {"text": "Not now."},
                "expected_revision": first_turn.observation.context.revision,
            }
        )
        command_id = int(self.store.poll(self.query).split("|")[2])
        rejected = self.app.session.outcome("npc-turn:rejected")
        self.assertIs(rejected.state, ActionState.DISPATCHED)
        self.store.poll({**self.query, "ack": str(command_id), "result": "-1"})

        rejected = self.app.session.outcome("npc-turn:rejected")
        self.assertIs(rejected.state, ActionState.REJECTED)
        event_log.close()

        reopened_log = SemanticEventLog(events_path)
        try:
            self.app = NativeNpcSpeechApplication(
                self.store,
                "session:trainer:retry",
                agent_id=1,
                conversation_mode=True,
                event_log=reopened_log,
                clock_ms=lambda: 1000,
                token_factory=lambda: next(tokens),
                action_id_factory=lambda request_id: f"action:{request_id}",
            )
            self._complete_agent_refresh()
            retry_turn = self.app.session.turn()

            self.assertEqual(len(retry_turn.affordances), 1)
            retry = self.app.session.submit(
                {
                    "request_id": "npc-turn:retry",
                    "affordance_token": retry_turn.affordances[0].token,
                    "arguments": {"text": "Yes. What do you need?"},
                    "expected_revision": retry_turn.observation.context.revision,
                }
            )
            self.assertIs(retry.state, ActionState.ACCEPTED)
        finally:
            reopened_log.close()

    def test_speech_reaches_engine_observed_dialogue_event(self):
        self._complete_agent_refresh()
        turn = self.app.session.turn()
        accepted = self.app.session.submit(
            {
                "request_id": "utterance:1",
                "affordance_token": turn.affordances[0].token,
                "arguments": {"text": "You have my attention."},
                "expected_revision": turn.observation.context.revision,
            }
        )
        self.assertIs(accepted.state, ActionState.ACCEPTED)
        self.assertEqual(to_wire(accepted.engine_result), {"status": "queued"})

        fields = self.store.poll(self.query).split("|")
        command_id = int(fields[2])
        self.assertEqual(fields[3:9], ["4", "1", "0", "0", "1", "42"])
        self.assertEqual(fields[-1], "You have my attention.")
        self.store.event(
            "/dialogue",
            {"v": "2", "job": str(command_id), "event": "1"},
        )

        observed = self.app.session.outcome("utterance:1")
        result = to_wire(observed)
        self.assertIs(observed.state, ActionState.OBSERVED)
        self.assertEqual(observed.evidence[0].level, EvidenceLevel.ENGINE_OBSERVED)
        self.assertEqual(result["engine_result"]["dialogue_event"], "opened")
        self.assertEqual(
            result["facts"][0],
            {
                "key": "dialogue.state",
                "value": "opened",
                "source": "engine-observed",
                "observed_revision": turn.observation.context.revision + 1,
            },
        )

        voice_request = self.app.voice_request(
            "utterance:1",
            "trainer.default",
            delivery=VoiceDelivery.PLAY_HOST,
        )
        self.assertEqual(
            to_wire(voice_request),
            {
                "request_id": "speech:action:utterance:1",
                "text": "You have my attention.",
                "profile_id": "trainer.default",
                "delivery": "play-host",
                "speed": 1.0,
                "output_format": "wav",
                "correlation_id": "action:utterance:1",
                "schema": "warband.agentic/v1",
            },
        )

    def test_observed_speech_handler_is_exactly_once_and_cannot_falsify_outcome(self):
        notifications = []

        def handler(action_id, text, context):
            notifications.append((action_id, text, context))
            raise RuntimeError("voice service is offline")

        self.app.set_observed_speech_handler(handler)
        with self.assertRaisesRegex(RuntimeError, "already configured"):
            self.app.set_observed_speech_handler(handler)
        self._complete_agent_refresh()
        turn = self.app.session.turn()
        self.app.session.submit(
            {
                "request_id": "utterance:auto-voice",
                "affordance_token": turn.affordances[0].token,
                "arguments": {"text": "The game result remains authoritative."},
                "expected_revision": turn.observation.context.revision,
            }
        )
        command_id = int(self.store.poll(self.query).split("|")[2])
        self.store.event(
            "/dialogue",
            {"v": "2", "job": str(command_id), "event": "1"},
        )

        first = self.app.session.outcome("utterance:auto-voice")
        repeated = self.app.session.outcome("utterance:auto-voice")

        self.assertIs(first.state, ActionState.OBSERVED)
        self.assertEqual(repeated, first)
        self.assertEqual(
            notifications,
            [
                (
                    "action:utterance:auto-voice",
                    "The game result remains authoritative.",
                    turn.observation.context,
                )
            ],
        )
        self.assertEqual(
            self.app.speech_notification_failures(),
            {"action:utterance:auto-voice": "RuntimeError"},
        )

    def test_player_agent_cannot_be_recast_as_an_npc(self):
        player_app = NativeNpcSpeechApplication(
            self.store,
            "session:not-an-npc",
            agent_id=0,
            clock_ms=lambda: 1000,
        )
        command_id = player_app.queue_observation_refresh()
        self.store.poll(self.query)
        event = {"v": "2", "job": str(command_id), "scene": "42", "session": "1"}
        self.store.event("/agents_end", {**event, "count": "1"})
        self.store.event(
            "/agent",
            {
                **event,
                "id": "0",
                "troop": "0",
                "team": "0",
                "hp": "50",
                "x": "0",
                "y": "0",
                "z": "0",
                "player": "1",
            },
        )
        self.store.poll({**self.query, "ack": str(command_id)})

        with self.assertRaisesRegex(ValueError, "player"):
            player_app.session.turn()

    def test_late_dialogue_event_promotes_expired_action_to_observed(self):
        self._complete_agent_refresh()
        turn = self.app.session.turn()
        self.app.session.submit(
            {
                "request_id": "utterance:late",
                "affordance_token": turn.affordances[0].token,
                "arguments": {"text": "I was delayed, not lost."},
                "expected_revision": turn.observation.context.revision,
            }
        )
        command_id = int(self.store.poll(self.query).split("|")[2])
        command = self.store.command(command_id)
        with patch(
            "bridge.game_bridge.time.time",
            return_value=command["created"] + 31,
        ):
            expired = self.app.session.outcome("utterance:late")
        self.assertIs(expired.state, ActionState.EXPIRED)

        self.store.event(
            "/dialogue",
            {"v": "2", "job": str(command_id), "event": "1"},
        )
        observed = self.app.session.outcome("utterance:late")
        self.assertIs(observed.state, ActionState.OBSERVED)

    def test_restart_recovers_speech_for_outcome_and_voice_handoff(self):
        events_path = Path(self.temp.name) / "speech-events.sqlite3"
        event_log = SemanticEventLog(events_path)
        self.app = NativeNpcSpeechApplication(
            self.store,
            "session:trainer:restart",
            agent_id=1,
            event_log=event_log,
            clock_ms=lambda: 1000,
            token_factory=lambda: "affordance:speech:first",
            action_id_factory=lambda request_id: f"action:{request_id}",
        )
        self._complete_agent_refresh()
        turn = self.app.session.turn()
        accepted = self.app.session.submit(
            {
                "request_id": "utterance:restart",
                "affordance_token": turn.affordances[0].token,
                "arguments": {"text": "I remember where we left off."},
                "expected_revision": turn.observation.context.revision,
            }
        )
        event_log.close()

        reopened_log = SemanticEventLog(events_path)
        try:
            self.app = NativeNpcSpeechApplication(
                self.store,
                "session:trainer:restart",
                agent_id=1,
                event_log=reopened_log,
                clock_ms=lambda: 1000,
                token_factory=lambda: "affordance:speech:second",
                action_id_factory=lambda request_id: f"action:{request_id}",
            )
            self.assertEqual(self.app.session.outcome("utterance:restart"), accepted)
            command_id = int(self.store.poll(self.query).split("|")[2])
            self.store.event(
                "/dialogue",
                {"v": "2", "job": str(command_id), "event": "1"},
            )
            observed = self.app.session.outcome("utterance:restart")
            self.assertIs(observed.state, ActionState.OBSERVED)
            voice = self.app.voice_request("utterance:restart", "trainer.default")
            self.assertEqual(voice.text, "I remember where we left off.")
        finally:
            reopened_log.close()


if __name__ == "__main__":
    unittest.main()
