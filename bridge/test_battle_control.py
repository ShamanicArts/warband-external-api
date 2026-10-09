import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.test_game_bridge import mission_telemetry


class BattleControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bridge.sqlite"
        self.store = Store(self.path)
        self.query = {**mission_telemetry(), "build": "6", "flags": "2"}
        self.store.poll(self.query)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def event(self, job, formation):
        return {
            "v": "2",
            "job": str(job),
            "team": "0",
            "formation": str(formation),
            "movement": "2",
            "fire": "0",
            "riding": "1",
            "weapon": "0",
            "x": "1200",
            "y": "3400",
            "scene": self.query["scene"],
            "session": self.query["session"],
        }

    def test_own_formation_order_and_durable_readback(self):
        command = self.store.enqueue_operation(
            "battle_order",
            {
                "formation": 0,
                "order": "charge",
            },
        )
        fields = self.store.poll(self.query).split("|")
        self.assertEqual(fields[3:7], ["7", "0", "2", "0"])
        self.store.event("/battle-order", self.event(command["id"], 0))
        result = self.store.battle_result(command["id"])
        self.assertTrue(result["complete"])
        self.assertEqual(result["formations"][0]["movement"], 2)
        self.store.db.close()
        self.store = Store(self.path)
        self.assertEqual(
            self.store.battle_result(command["id"])["formations"], result["formations"]
        )

    def test_everyone_needs_nine_unique_readbacks(self):
        command = self.store.enqueue_operation(
            "battle_order",
            {
                "formation": 9,
                "order": "hold_fire",
            },
        )
        self.store.poll(self.query)
        for formation in range(8):
            self.store.event("/battle-order", self.event(command["id"], formation))
        self.assertFalse(self.store.battle_result(command["id"])["complete"])
        self.store.event("/battle-order", self.event(command["id"], 8))
        self.assertTrue(self.store.battle_result(command["id"])["complete"])

    def test_bad_arguments_and_nonbattle_are_rejected(self):
        for formation, order in [
            (True, "hold"),
            (10, "hold"),
            (-1, "hold"),
            (0, "kill"),
        ]:
            with self.assertRaises(ValueError):
                self.store.enqueue_operation(
                    "battle_order",
                    {
                        "formation": formation,
                        "order": order,
                    },
                )
        for change in ({"flags": "0"}, {"build": "5"}, {"hp": "0"}, {"dialogue": "1"}):
            self.store.poll({**self.query, **change})
            with self.assertRaises(ValueError):
                self.store.enqueue_operation(
                    "battle_order",
                    {
                        "formation": 0,
                        "order": "hold",
                    },
                )

    def test_wrong_scope_readback_is_rejected(self):
        command = self.store.enqueue_operation(
            "battle_order",
            {
                "formation": 0,
                "order": "hold",
            },
        )
        self.store.poll(self.query)
        event = self.event(command["id"], 0)
        for change in (
            {"scene": "999"},
            {"session": "999"},
            {"formation": "1"},
            {"team": "99"},
        ):
            with self.assertRaises(ValueError):
                self.store.event("/battle-order", {**event, **change})
