import json
import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.native_faction_agent_app import (
    NativeFactionAgentApplication,
    PartyOrderOption,
)
from warband_agentic import (
    ActionState,
    EvidenceLevel,
    RiskClass,
    SemanticEventLog,
    to_wire,
)


def campaign_telemetry(ack=0, result=0, clock=90):
    return {
        "v": "2",
        "context": "campaign",
        "ack": str(ack),
        "gold": "355",
        "troop": "0",
        "hp": "0",
        "x": "0",
        "y": "0",
        "z": "0",
        "clock": str(clock),
        "scene": "-1",
        "session": "-1",
        "agent": "-1",
        "result": str(result),
        "build": "16",
        "menu": "-1",
        "menu-session": "0",
        "dialogue": "0",
        "captive": "0",
    }


class NativeFactionAgentApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(
            Path(self.temp.name) / "bridge.sqlite3",
            {
                "factions": {"15": "Kingdom of Swadia"},
                "parties": {
                    "26": "Praven",
                    "99": "Enemy War Party",
                    "500": "Count Delinard's Party",
                },
            },
        )
        self.query = campaign_telemetry()
        self.store.poll(self.query)
        tokens = iter(f"affordance:{index}" for index in range(10))
        self.app = NativeFactionAgentApplication(
            self.store,
            "session:swadia:1",
            faction_id=15,
            controlled_party_ids=(500,),
            order_options=(
                PartyOrderOption(500, "travel", 26, "Defend Praven"),
                PartyOrderOption(500, "attack", 99, "Attack enemy party"),
            ),
            clock_ms=lambda: 1000,
            token_factory=lambda: next(tokens),
            action_id_factory=lambda request_id: f"action:{request_id}",
        )

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def _complete_refresh(self, controlled_faction_id=15):
        jobs = self.app.queue_observation_refresh()
        self.assertEqual(set(jobs), {26, 99, 500})
        ack = 0
        while True:
            fields = self.store.poll(campaign_telemetry(ack=ack)).split("|")
            command_id = int(fields[2])
            if command_id == 0:
                break
            command = self.store.command(command_id)
            party_id = command["arguments"]["entity_id"]
            behavior = 1 if party_id == 500 else 0
            self.store.event(
                "/world-result",
                {
                    "v": "2",
                    "job": str(command_id),
                    "kind": "2",
                    "id": str(party_id),
                    "other": "-1",
                    "a": str(behavior),
                    "b": "26" if party_id == 500 else "-1",
                    "c": "100",
                    "d": str(controlled_faction_id)
                    if party_id == 500
                    else "15"
                    if party_id != 99
                    else "16",
                    "e": str(party_id * 10),
                    "f": str(party_id * -5),
                },
            )
            ack = command_id
        return jobs

    def test_controlled_party_must_belong_to_the_granted_faction(self):
        self._complete_refresh(controlled_faction_id=16)

        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.app.session.turn()

    def test_refresh_turn_and_affordances_are_faction_scoped(self):
        self._complete_refresh()

        turn = self.app.session.turn()
        wire = to_wire(turn)
        encoded = json.dumps(wire)
        facts = {fact["key"]: fact["value"] for fact in wire["observation"]["facts"]}
        self.assertEqual(wire["observation"]["role"], "faction.sovereign")
        self.assertEqual(facts["self.faction_id"], 15)
        self.assertEqual(facts["faction.name"], "Kingdom of Swadia")
        self.assertEqual(facts["parties.500.ai_behavior"], 1)
        self.assertEqual(facts["parties.99.faction_id"], 16)
        self.assertEqual(len(turn.affordances), 2)
        attack = next(
            item
            for item in turn.affordances
            if item.parameters["properties"]["order"]["const"] == "attack"
        )
        self.assertIs(attack.risk, RiskClass.CONSEQUENTIAL)
        self.assertNotIn("world_control", encoded)
        self.assertNotIn("party_order", encoded)
        self.assertNotIn(str(max(self.app.refresh_command_ids)), encoded)

    def test_exact_party_order_reaches_engine_observed_readback(self):
        self._complete_refresh()
        turn = self.app.session.turn()
        travel = next(
            item
            for item in turn.affordances
            if item.parameters["properties"]["order"]["const"] == "travel"
        )

        accepted = self.app.session.submit(
            {
                "request_id": "defend-praven:1",
                "affordance_token": travel.token,
                "arguments": {"order": "travel", "target_id": 26},
                "expected_revision": turn.observation.context.revision,
            }
        )
        self.assertIs(accepted.state, ActionState.ACCEPTED)
        self.assertNotIn("id", to_wire(accepted.engine_result))

        fields = self.store.poll(self.query).split("|")
        command_id = int(fields[2])
        self.assertEqual(fields[3:7], ["15", "1000500", "1", "26"])
        self.store.event(
            "/world-result",
            {
                "v": "2",
                "job": str(command_id),
                "kind": "2",
                "id": "500",
                "other": "-1",
                "a": "1",
                "b": "26",
                "c": "100",
                "d": "15",
                "e": "1200",
                "f": "3400",
            },
        )
        self.store.poll(campaign_telemetry(ack=command_id))

        observed = self.app.session.outcome("defend-praven:1")
        result = to_wire(observed)
        self.assertIs(observed.state, ActionState.OBSERVED)
        self.assertEqual(observed.evidence[0].level, EvidenceLevel.ENGINE_OBSERVED)
        self.assertEqual(result["engine_result"]["status"], "acknowledged")
        self.assertEqual(result["facts"][0]["key"], "parties.500.ai_behavior")
        self.assertEqual(result["facts"][0]["value"], 1)

        ticks = iter((2000, 2001))
        self.app._clock_ms = lambda: next(ticks)
        repeated = self.app.session.outcome("defend-praven:1")
        self.assertIs(repeated, observed)

    def test_restart_recovers_faction_command_correlation(self):
        events_path = Path(self.temp.name) / "faction-events.sqlite3"
        event_log = SemanticEventLog(events_path)
        tokens = iter(("affordance:faction:travel", "affordance:faction:attack"))
        options = (
            PartyOrderOption(500, "travel", 26, "Defend Praven"),
            PartyOrderOption(500, "attack", 99, "Attack enemy party"),
        )
        self.app = NativeFactionAgentApplication(
            self.store,
            "session:swadia:restart",
            faction_id=15,
            controlled_party_ids=(500,),
            order_options=options,
            event_log=event_log,
            clock_ms=lambda: 1000,
            token_factory=lambda: next(tokens),
            action_id_factory=lambda request_id: f"action:{request_id}",
        )
        self._complete_refresh()
        turn = self.app.session.turn()
        travel = next(
            item
            for item in turn.affordances
            if item.parameters["properties"]["order"]["const"] == "travel"
        )
        request = {
            "request_id": "defend:restart",
            "affordance_token": travel.token,
            "arguments": {"order": "travel", "target_id": 26},
            "expected_revision": turn.observation.context.revision,
        }
        accepted = self.app.session.submit(request)
        command_count = self.store.db.execute(
            "SELECT count(*) FROM commands"
        ).fetchone()[0]
        event_log.close()

        reopened_log = SemanticEventLog(events_path)
        try:
            self.app = NativeFactionAgentApplication(
                self.store,
                "session:swadia:restart",
                faction_id=15,
                controlled_party_ids=(500,),
                order_options=options,
                event_log=reopened_log,
                clock_ms=lambda: 1000,
                token_factory=lambda: "affordance:faction:second",
                action_id_factory=lambda request_id: f"action:{request_id}",
            )
            self.assertEqual(
                self.app.session.outcome("defend:restart"), accepted
            )
            self.assertEqual(
                self.store.db.execute("SELECT count(*) FROM commands").fetchone()[0],
                command_count,
            )
            self.store.poll(self.query)
            self.assertIs(
                self.app.session.outcome("defend:restart").state,
                ActionState.DISPATCHED,
            )
        finally:
            reopened_log.close()


if __name__ == "__main__":
    unittest.main()
