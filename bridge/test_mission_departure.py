import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.protocol import validate_operation, wire_arguments
from bridge.test_game_bridge import mission_telemetry


class DepartureTests(unittest.TestCase):
    def test_village_departure_has_distinct_operation_scope_and_catalog(self):
        self.store.module_catalog["missions"]["7"] = "village_center"
        self.store.module_catalog["village_departure_missions"] = [7]
        self.store.poll({**self.query, "mission": "7", "build": "13"})
        with self.assertRaises(ValueError):
            self.store.enqueue_operation("leave_village", {})
        self.store.poll({**self.query, "mission": "7", "build": "14"})
        with self.assertRaises(ValueError):
            self.store.enqueue_operation("leave_scene", {})
        cmd = self.store.enqueue_operation("leave_village", {})
        self.assertIn(
            f"|{cmd['id']}|21|",
            self.store.poll({**self.query, "mission": "7", "build": "14"}),
        )

    def test_streets_require_revision13_and_recognized_runtime_handler(self):
        self.store.module_catalog["missions"]["2"] = "town_center"
        self.store.module_catalog["scene_departure_missions"].append(2)
        self.store.poll({**self.query, "mission": "2", "build": "12"})
        with self.assertRaises(ValueError):
            self.store.enqueue_operation("leave_scene", {})
        self.store.poll({**self.query, "mission": "2", "build": "13"})
        cmd = self.store.enqueue_operation("leave_scene", {})
        self.assertIn(
            f"|{cmd['id']}|20|",
            self.store.poll({**self.query, "mission": "2", "build": "13"}),
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(
            Path(self.temp.name) / "bridge.sqlite",
            {"missions": {"0": "town_default"}, "scene_departure_missions": [0]},
        )
        self.query = {
            **mission_telemetry(),
            "mission": "0",
            "build": "12",
            "flags": "0",
            "hp": "49",
        }
        self.store.poll(self.query)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_departure_uses_exact_mission_scope_and_zero_wire_parameters(self):
        cmd = self.store.enqueue_operation("leave_scene", {})
        self.assertEqual(wire_arguments("leave_scene", {}), [0, 0, 0, 0])
        self.assertEqual(cmd["scene"], int(self.query["scene"]))
        self.assertEqual(cmd["session"], int(self.query["session"]))
        response = self.store.poll(self.query)
        self.assertIn(f"|{cmd['id']}|20|0|0|0|", response)

    def test_other_scenes_battles_death_dialogue_and_unknown_handlers_reject(self):
        for change in (
            {"context": "menu"},
            {"integration_revision": 11},
            {"mission_template": "village_center"},
            {"mission_flags": 2},
            {"player_hit_points": 0},
            {"dialogue_active": True},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_operation(
                    "leave_scene", {}, {**self.store.snapshot(), **change}
                )
        self.store.module_catalog["scene_departure_missions"] = []
        with self.assertRaises(ValueError):
            self.store.enqueue_operation("leave_scene", {})

    def test_changed_scene_session_rejects_before_dispatch(self):
        cmd = self.store.enqueue_operation("leave_scene", {})
        self.store.poll({**self.query, "session": str(int(self.query["session"]) + 1)})
        self.assertEqual(self.store.command(cmd["id"])["status"], "rejected")
