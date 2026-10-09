import unittest

from module_system.build_mcp_module import compile_ops
from module_system.menu_actions import append_actions, parse_menus


class MenuActionTests(unittest.TestCase):
    def setUp(self):
        self.lines = [
            "menusfile version 1",
            "1",
            "menu_village 0 Village. none 0 2",
            " mno_recruit_volunteers 1 31 2 1 1 Recruit. 1 2060 1 99 . "
            "mno_village_reports 0 CHEAT. 1 2133 2 0 42 .",
        ]

    def test_only_reviewed_native_options_get_scripts(self):
        scripts, actions = append_actions(self.lines, 100, compile_ops, 99984)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["condition_script"], 100)
        self.assertEqual(actions[0]["consequence_script"], 101)
        self.assertEqual(actions[0]["menu"], "village")
        self.assertEqual(scripts[3], "1 2060 1 99")
        self.assertIn("31 2 1 1", scripts[1])
        self.assertNotIn("42", " ".join(scripts))

    def test_conditions_and_consequences_use_separate_local_namespaces(self):
        self.lines[3] = (
            " mno_recruit_volunteers 1 2133 2 1224979098644774912 1 Recruit. "
            "1 2133 2 1224979098644774912 2 ."
        )
        scripts, actions = append_actions(self.lines, 100, compile_ops, 99984)
        self.assertIn("1224979098644774912 1", scripts[1])
        self.assertIn("1224979098644774912 2", scripts[3])
        self.assertEqual(
            actions[0]["consequence_script"], actions[0]["condition_script"] + 1
        )

    def test_parser_keeps_native_initializer_and_option_ids(self):
        menu = parse_menus(self.lines)[0]
        self.assertEqual(menu["initializer"], ["0"])
        self.assertEqual(menu["options"][1]["name"], "village_reports")


if __name__ == "__main__":
    unittest.main()
