import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.protocol import validate_operation, wire_arguments
from bridge.test_game_bridge import mission_telemetry


class WorldControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bridge.sqlite"
        self.store = Store(self.path)
        self.query = {
            **mission_telemetry(),
            "context": "campaign",
            "scene": "-1",
            "session": "-1",
            "build": "8",
            "captive": "0",
        }
        self.store.poll(self.query)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_world_control_permission_is_explicit_on_wire(self):
        args = {
            "party_id": 500,
            "order": "travel",
            "target_party_id": 26,
            "world_control": False,
        }
        with self.assertRaises(ValueError):
            self.store.enqueue_operation("party_order", args)
        args["world_control"] = True
        validate_operation("party_order", args, self.store.snapshot())
        self.assertEqual(wire_arguments("party_order", args), [1000500, 1, 26, 0])
        cmd = self.store.enqueue_operation("party_order", args)
        self.assertIn(
            f"|{cmd['id']}|15|1000500|1|26|-1|-1|", self.store.poll(self.query)
        )

    def test_faction_getters_and_results_are_durable(self):
        cmd = self.store.enqueue_operation(
            "world_query",
            {
                "entity": "faction",
                "entity_id": 15,
                "other_id": 16,
            },
        )
        self.store.poll(self.query)
        self.store.event(
            "/world-result",
            {
                "v": "2",
                "job": str(cmd["id"]),
                "kind": "1",
                "id": "15",
                "other": "16",
                "a": "-40",
                "b": "400",
                "c": "0",
                "d": "16711680",
                "e": "401",
                "f": "0",
            },
        )
        result = self.store.world_result(cmd["id"])
        self.assertEqual(result["facts"]["relation"], -40)
        self.assertEqual(result["facts"]["leader_troop_id"], 400)
        self.store.db.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.world_result(cmd["id"])["facts"], result["facts"])

    def test_world_read_allowed_in_menu_but_mutations_are_not(self):
        self.store.poll({**self.query, "context": "menu", "menu": "23"})
        cmd = self.store.enqueue_operation(
            "world_query", {"entity": "party", "entity_id": 0, "other_id": 0}
        )
        self.assertIn(
            f"|{cmd['id']}|13|2|0|0|",
            self.store.poll({**self.query, "context": "menu", "menu": "23"}),
        )
        with self.assertRaises(ValueError):
            self.store.enqueue_operation(
                "party_order",
                {
                    "party_id": 0,
                    "order": "hold",
                    "target_party_id": 0,
                    "world_control": False,
                },
            )

    def test_game_rejection_is_not_diplomacy_success(self):
        cmd = self.store.enqueue_operation(
            "diplomacy",
            {
                "faction_a": 15,
                "faction_b": 16,
                "action": "war",
                "world_control": False,
            },
        )
        self.assertEqual(wire_arguments("diplomacy", cmd["arguments"]), [15, 16, 1, 0])
        self.store.poll(self.query)
        self.store.poll({**self.query, "ack": str(cmd["id"]), "result": "-1"})
        self.assertEqual(
            self.store.world_result(cmd["id"])["command"]["status"], "rejected"
        )

    def test_world_result_cannot_claim_another_entity(self):
        cmd = self.store.enqueue_operation(
            "world_query", {"entity": "party", "entity_id": 0, "other_id": 0}
        )
        self.store.poll(self.query)
        with self.assertRaises(ValueError):
            self.store.event(
                "/world-result",
                {
                    "v": "2",
                    "job": str(cmd["id"]),
                    "kind": "2",
                    "id": "500",
                    "other": "-1",
                    **{field: "0" for field in "abcdef"},
                },
            )

    def test_stale_build_captivity_and_bool_ids_rejected(self):
        args = {
            "party_id": 0,
            "order": "hold",
            "target_party_id": 0,
            "world_control": False,
        }
        for changes in (
            {"integration_revision": 7},
            {"player_is_captive": True},
            {"context": "mission"},
        ):
            with self.assertRaises(ValueError):
                validate_operation(
                    "party_order", args, {**self.store.snapshot(), **changes}
                )
        for changes in (
            {"party_id": True},
            {"world_control": 1},
            {"order": "teleport"},
        ):
            with self.assertRaises(ValueError):
                validate_operation(
                    "party_order", {**args, **changes}, self.store.snapshot()
                )

    def test_wait_is_bounded_attackable_time_control_not_teleport(self):
        cmd = self.store.enqueue_operation("campaign_wait", {"hours": 1, "speed": 2})
        self.assertIn(f"|{cmd['id']}|16|1|2|0|-1|-1|", self.store.poll(self.query))
        for args in (
            {"hours": True, "speed": 1},
            {"hours": 25, "speed": 1},
            {"hours": -1, "speed": 1},
            {"hours": 1, "speed": 6},
        ):
            with self.assertRaises(ValueError):
                validate_operation("campaign_wait", args, self.store.snapshot())
        validate_operation(
            "campaign_wait", {"hours": 0, "speed": 1}, self.store.snapshot()
        )
