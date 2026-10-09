import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.test_game_bridge import mission_telemetry


class MenuControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(
            Path(self.temp.name) / "bridge.sqlite",
            {
                "menu_actions": [
                    {
                        "id": 0,
                        "menu_id": 23,
                        "menu": "camp",
                        "option": "resume_travelling",
                        "condition_script": 100,
                    },
                    {
                        "id": 1,
                        "menu_id": 80,
                        "menu": "village",
                        "option": "recruit_volunteers",
                    },
                ]
            },
        )
        self.query = {
            **mission_telemetry(),
            "context": "menu",
            "scene": "-1",
            "session": "-1",
            "build": "5",
            "menu": "23",
            "menu-session": "10",
        }
        self.store.poll(self.query)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_menu_catalog_is_not_a_claim_of_visibility(self):
        catalog = self.store.menu_options()
        self.assertEqual([a["id"] for a in catalog["actions"]], [0])
        self.assertNotIn("condition_script", catalog["actions"][0])
        self.assertIn("Native conditions", catalog["availability"])

    def test_scoped_native_selection_on_wire(self):
        command = self.store.enqueue_operation("select_menu", {"action_id": 0})
        fields = self.store.poll(self.query).split("|")
        self.assertEqual(fields[3:9], ["6", "0", "0", "0", "10", "23"])
        self.store.poll({**self.query, "ack": str(command["id"]), "result": "0"})
        self.assertEqual(self.store.command(command["id"])["status"], "acknowledged")

    def test_revisit_same_menu_does_not_replay_action(self):
        cmd = self.store.enqueue_operation("select_menu", {"action_id": 0})
        self.store.poll({**self.query, "menu-session": "11"})
        self.assertEqual(self.store.command(cmd["id"])["status"], "rejected")

    def test_wrong_menu_and_unknown_ids_are_rejected(self):
        for action in (1, 999, True, -1):
            with self.assertRaises(ValueError):
                self.store.enqueue_operation("select_menu", {"action_id": action})

    def test_native_failed_condition_propagates_result(self):
        cmd = self.store.enqueue_operation("select_menu", {"action_id": 0})
        self.store.poll(self.query)
        self.store.poll({**self.query, "ack": str(cmd["id"]), "result": "-3"})
        self.assertEqual(self.store.command(cmd["id"])["status"], "rejected")

    def test_old_integration_cannot_select_menu(self):
        self.store.poll({**self.query, "build": "4"})
        with self.assertRaisesRegex(ValueError, "revision 5"):
            self.store.enqueue_operation("select_menu", {"action_id": 0})


if __name__ == "__main__":
    unittest.main()
