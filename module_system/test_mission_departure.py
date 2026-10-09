import unittest

from module_system.mission_departure import (
    leave_street_ops,
    leave_town_ops,
    recognize_street_permission,
    recognize_town_permission,
    village_permission,
)


class MissionDepartureTests(unittest.TestCase):
    def test_village_exact_native_handler_preserves_quest_success_failure_calls(self):
        quest, fugitive = 504403158265495558, 360287970189640522
        alive, fail, succeed = (
            936748722493063593,
            936748722493063553,
            936748722493063552,
        )
        scripts = {
            "cf_troop_agent_is_alive": alive - (13 << 56),
            "fail_quest": fail - (13 << 56),
            "succeed_quest": succeed - (13 << 56),
        }
        tab = (
            f"-21.000000 0.000000 0.000000 13 4 0 200 1 {quest} "
            f"2147483850 1 {quest} 2147483851 1 {quest} 546 3 {quest} 11 1 "
            f"4 0 1 2 {alive} {fugitive} 1 2 {fail} {quest} 5 0 1 2 {succeed} {quest} "
            "3 0 3 0 2075 1 1 0"
        )
        lines = ["mst_village_center 0 0", "Village", "0", "0 1", tab]
        mission, effects = village_permission(lines, quest, fugitive, scripts)
        self.assertEqual(mission, 0)
        self.assertIn(("call_script", fail, quest), effects)
        self.assertIn(("call_script", succeed, quest), effects)
        for change in (
            tab.replace(str(fail), str(succeed)),
            tab.replace("11 1", "11 0"),
        ):
            with self.assertRaises(ValueError):
                village_permission([*lines[:-1], change], quest, fugitive, scripts)
        from module_system.test_goods_trade import TradeFlow

        class QuestModel(TradeFlow):
            def operation(self, op):
                if op[0] in (
                    "check_quest_active",
                    "not_check_quest_succeeded",
                    "not_check_quest_failed",
                    "quest_slot_eq",
                ):
                    return self.active
                if op[0] == "call_script":
                    if op[1] == alive:
                        return self.alive
                    self.events.append(op)
                    return True
                return super().operation(op)

        # Model only: actual active-hunt consequences remain live-unverified.
        for active, living, expected in (
            (False, True, []),
            (True, True, [("call_script", fail, quest)]),
            (True, False, [("call_script", succeed, quest)]),
        ):
            model = QuestModel()
            model.active, model.alive = active, living
            model.block(effects)
            self.assertEqual(model.events, expected)

    def test_street_special_modes_fail_before_teardown_model(self):
        # Model of conditions only, NOT actual engine quest/battle acceptance.
        globals_ = {
            name: (2 << 56) + i
            for i, name in enumerate(
                ("talk_context", "g_mt_mode", "g_defending_against_siege")
            )
        }
        for talk, mode, siege, allowed in (
            (0, 0, 0, True),
            (0, 1, 0, True),
            (18, 0, 0, False),
            (19, 0, 0, False),
            (0, 2, 0, False),
            (0, 0, 1, False),
        ):
            with self.subTest(talk=talk, mode=mode, siege=siege):
                values = dict(zip(globals_.values(), (talk, mode, siege)))
                ops = leave_street_ops(2, globals_, 1, 2, 3)
                start = next(i for i, op in enumerate(ops) if op[0] == "neq")
                alternative = False
                reached_finish = False
                for op in ops[start:]:
                    if op[0] == "finish_mission":
                        reached_finish = True
                    elif op[0] in ("eq", "neq", "or_eq"):
                        a, b = values[op[1]], op[2]
                        passed = a != b if op[0] == "neq" else a == b
                        if op[0] == "or_eq":
                            alternative = passed
                            continue
                        if not (passed or alternative):
                            break
                        alternative = False
                self.assertEqual(reached_finish, allowed)

    def test_street_handler_is_exactly_recognized_and_preserves_special_guards(self):
        globals_ = {
            name: (2 << 56) + i
            for i, name in enumerate(
                ("talk_context", "g_mt_mode", "g_defending_against_siege")
            )
        }
        string = (3 << 56) + 8
        talk, mode = globals_["talk_context"], globals_["g_mt_mode"]
        tab = (
            f"-21.000000 0.000000 0.000000 12 4 0 1073741855 2 {talk} 19 "
            f"31 2 {talk} 18 1106 1 {string} 5 0 1073741855 2 {mode} 0 "
            f"31 2 {mode} 1 1935 0 2075 1 1 5 0 1106 1 {string} 3 0 0"
        )
        lines = ["mst_town_center 0 0", "Town", "0", "0 1", tab]
        self.assertEqual(recognize_street_permission(lines, globals_, string), 0)
        for change in (
            tab.replace(f"{talk} 19", f"{talk} 17"),
            tab.replace("1935 0", "1936 0"),
            tab + " 2133 2 0 1",
        ):
            with self.assertRaises(ValueError):
                recognize_street_permission([*lines[:-1], change], globals_, string)
        ops = leave_street_ops(0, globals_, 1, 2, 3)
        self.assertIn(("neq", talk, 18), ops)
        self.assertIn(("neq", talk, 19), ops)
        self.assertIn(("eq", globals_["g_defending_against_siege"], 0), ops)
        self.assertIn(("or_eq", mode, 0), ops)
        self.assertIn(("eq", mode, 1), ops)
        self.assertEqual(
            ops[-3:],
            [
                ("mission_enable_talk",),
                ("assign", (17 << 56) + 10, 0),
                ("finish_mission", 0),
            ],
        )

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
