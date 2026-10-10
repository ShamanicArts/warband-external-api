import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.native_menu_agent_app import NativeMenuAgentApplication
from warband_agentic import ActionState, EvidenceLevel, SemanticEventLog, to_wire


def menu_telemetry(ack=0, result=0, menu_session=10):
    return {
        "v": "2",
        "context": "menu",
        "ack": str(ack),
        "gold": "355",
        "troop": "0",
        "hp": "0",
        "x": "0",
        "y": "0",
        "z": "0",
        "clock": "90",
        "scene": "-1",
        "session": "-1",
        "agent": "-1",
        "result": str(result),
        "build": "16",
        "menu": "23",
        "menu-session": str(menu_session),
        "dialogue": "0",
        "captive": "0",
    }


class NativeMenuAgentApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(
            Path(self.temp.name) / "bridge.sqlite3",
            {
                "menus": {"23": "camp"},
                "menu_actions": [
                    {
                        "id": 0,
                        "menu_id": 23,
                        "menu": "camp",
                        "option": "resume_travelling",
                        "text_template": "Resume travelling.",
                    }
                ],
            },
        )
        self.query = menu_telemetry()
        self.store.poll(self.query)
        self.app = NativeMenuAgentApplication(
            self.store,
            "session:player-menu:1",
            clock_ms=lambda: 1000,
            token_factory=lambda: "affordance:resume",
            action_id_factory=lambda request_id: f"action:{request_id}",
        )

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_constrained_submission_queues_exact_native_menu_operation(self):
        turn = self.app.session.turn()
        self.assertEqual(turn.observation.context.scope_id, "menu:23")
        self.assertEqual(len(turn.affordances), 1)
        affordance = turn.affordances[0]

        outcome = self.app.session.submit(
            {
                "request_id": "resume:1",
                "affordance_token": affordance.token,
                "arguments": {"action_id": 0},
                "expected_revision": turn.observation.context.revision,
            }
        )

        self.assertIs(outcome.state, ActionState.ACCEPTED)
        self.assertEqual(outcome.evidence[0].level, EvidenceLevel.DECLARED)
        self.assertEqual(to_wire(outcome.engine_result), {"status": "queued"})
        fields = self.store.poll(self.query).split("|")
        self.assertGreater(int(fields[2]), 0)
        self.assertEqual(fields[3:9], ["6", "0", "0", "0", "10", "23"])

    def test_public_outcome_lookup_reconciles_game_dispatch_and_ack(self):
        turn = self.app.session.turn()
        accepted = self.app.session.submit(
            {
                "request_id": "resume:1",
                "affordance_token": turn.affordances[0].token,
                "arguments": {"action_id": 0},
                "expected_revision": turn.observation.context.revision,
            }
        )
        self.assertIs(accepted.state, ActionState.ACCEPTED)

        command_id = int(self.store.poll(self.query).split("|")[2])
        dispatched = self.app.session.outcome("resume:1")
        self.assertIs(dispatched.state, ActionState.DISPATCHED)
        self.assertEqual(to_wire(dispatched.engine_result), {"status": "dispatched"})

        self.store.poll(menu_telemetry(ack=command_id, result=0))
        acknowledged = self.app.session.outcome("resume:1")
        self.assertIs(acknowledged.state, ActionState.ACKNOWLEDGED)
        self.assertEqual(
            acknowledged.evidence[0].level,
            EvidenceLevel.ENGINE_ACKNOWLEDGED,
        )
        self.assertEqual(
            to_wire(acknowledged.engine_result),
            {"result": 0, "status": "acknowledged"},
        )

    def test_game_rejection_is_acknowledged_even_when_dispatch_poll_is_skipped(self):
        turn = self.app.session.turn()
        self.app.session.submit(
            {
                "request_id": "resume:1",
                "affordance_token": turn.affordances[0].token,
                "arguments": {"action_id": 0},
                "expected_revision": turn.observation.context.revision,
            }
        )

        command_id = int(self.store.poll(self.query).split("|")[2])
        self.store.poll(menu_telemetry(ack=command_id, result=-1))
        rejected = self.app.session.outcome("resume:1")

        self.assertIs(rejected.state, ActionState.REJECTED)
        self.assertEqual(
            rejected.evidence[0].level,
            EvidenceLevel.ENGINE_ACKNOWLEDGED,
        )
        self.assertEqual(
            to_wire(rejected.engine_result),
            {"result": -1, "status": "rejected"},
        )

    def test_restart_restores_private_command_correlation_without_replay(self):
        events_path = Path(self.temp.name) / "events.sqlite3"
        event_log = SemanticEventLog(events_path)
        self.app = NativeMenuAgentApplication(
            self.store,
            "session:player-menu:restart",
            event_log=event_log,
            clock_ms=lambda: 1000,
            token_factory=lambda: "affordance:resume:first",
            action_id_factory=lambda request_id: f"action:{request_id}",
        )
        turn = self.app.session.turn()
        request = {
            "request_id": "resume:restart",
            "affordance_token": turn.affordances[0].token,
            "arguments": {"action_id": 0},
            "expected_revision": turn.observation.context.revision,
        }
        accepted = self.app.session.submit(request)
        command_id = self.store.db.execute(
            "SELECT id FROM commands ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(self.store.command(command_id)["status"], "queued")
        event_log.close()

        reopened_log = SemanticEventLog(events_path)
        try:
            self.app = NativeMenuAgentApplication(
                self.store,
                "session:player-menu:restart",
                event_log=reopened_log,
                clock_ms=lambda: 1000,
                token_factory=lambda: "affordance:resume:second",
                action_id_factory=lambda request_id: f"action:{request_id}",
            )
            recovered = self.app.session.outcome("resume:restart")
            self.assertEqual(recovered, accepted)
            dispatched_id = int(self.store.poll(self.query).split("|")[2])
            self.assertEqual(dispatched_id, command_id)
            self.assertIs(
                self.app.session.outcome("resume:restart").state,
                ActionState.DISPATCHED,
            )
        finally:
            reopened_log.close()


if __name__ == "__main__":
    unittest.main()
