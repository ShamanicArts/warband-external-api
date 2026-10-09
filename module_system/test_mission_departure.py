import unittest

from module_system.mission_departure import leave_town_ops, recognize_town_permission


class MissionDepartureTests(unittest.TestCase):
    def test_enabled_departure_compiles_with_balanced_callback_scope(self):
        from module_system import test_build_mcp_module as build_tests
        from module_system.build_mcp_module import callback

        build_tests.ModuleBuildTests.assert_balanced(
            self,
            callback(
                native_globals={"g_main_attacker_agent": (2 << 56) + 137},
                town_departure_id=0,
            ),
        )

    def setUp(self):
        self.global_id = (2 << 56) + 137
        self.globals = {"g_main_attacker_agent": self.global_id}
        self.tab = (
            f"-21.000000 0.000000 0.000000 4 4 0 31 2 {self.global_id} 0 2075 1 1 3 0 0"
        )
        self.lines = ["mst_town_default 0 0", "Town", "0", "0 1", self.tab]

    def test_only_exact_original_town_permission_is_recognized(self):
        self.assertEqual(recognize_town_permission(self.lines, self.globals), 0)
        self.assertIsNone(
            recognize_town_permission(["mst_village_center 0 0"], self.globals)
        )
        for tab in (
            self.tab.replace("2075 1 1", "2075 1 0"),
            self.tab.replace(f"{self.global_id} 0", f"{self.global_id} 1"),
            self.tab + " 2133 2 0 1",
        ):
            with self.assertRaises(ValueError):
                recognize_town_permission([*self.lines[:-1], tab], self.globals)
        with self.assertRaises(ValueError):
            recognize_town_permission([*self.lines, self.tab], self.globals)

    def test_departure_keeps_permission_battle_living_player_and_dialogue_guards(self):
        ops = leave_town_ops(0, self.globals, 1, 2, 3)
        self.assertEqual(ops[-1], ("finish_mission", 0))
        self.assertIn(("eq", self.global_id, 0), ops[:-1])
        self.assertIn("agent_is_alive", [op[0] for op in ops[:-1]])
        self.assertIn("val_and", [op[0] for op in ops[:-1]])
        self.assertEqual(leave_town_ops(None, {}, 1, 2, 3), [("eq", 0, 1)])
