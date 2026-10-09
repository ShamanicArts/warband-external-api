import tempfile
import unittest
from pathlib import Path

from module_system.build_mcp_module import OPS, build, callback


class ModuleBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.native = self.root / "Native"
        self.native.mkdir()
        files = {
            "module.ini": "module_name = Native\nload_resource = test\n",
            "scripts.txt": (
                "scriptsfile version 1\n2\ngame_receive_url_response -1\n"
                " 0 \nother -1\n 0 \n"
            ),
            "strings.txt": "stringsfile version 1\n2\nstr_zero zero\nstr_one one\x97\n",
            "mission_templates.txt": (
                "missionsfile version 1\n1\n"
                "mst_tutorial_training_ground tutorial_training_ground 1 -1\n"
                "Description.\n\n1 0 0 0\n1\n0.000000 0.000000 0.000000 0 0\n"
            ),
            "simple_triggers.txt": "simple_triggers_file version 1\n1\n1.000000 0\n",
            "menus.txt": "menusfile version 1\n1\nmenu_test 0 Test. none 0 1\n"
            " mno_leave 0 Leave. 1 2040 0 .\n",
            "untouched.bin": "assets",
            "dialog_states.txt": "start\nparty_encounter\nprisoner_liberated\n"
            "enemy_defeated\nparty_relieved\nevent_triggered\nclose_window\n",
            "conversation.txt": "dialogsfile version 2\n1\n"
            "dlga_start:close_window 4095 0 0 test 6 0 NO_VOICEOVER\n",
        }
        for name, text in files.items():
            (self.native / name).write_bytes(text.encode("latin-1"))
        self.before = {p.name: p.read_bytes() for p in self.native.iterdir()}

    def tearDown(self):
        self.temp.cleanup()

    def test_additive_copy_preserves_native_and_non_utf8_strings(self):
        output = self.root / "WarbandMCP"
        build(self.native, output, "http://127.0.0.1", "a" * 64)
        self.assertEqual(
            self.before, {p.name: p.read_bytes() for p in self.native.iterdir()}
        )
        self.assertEqual((output / "untouched.bin").read_bytes(), b"assets")
        self.assertIn(b"one\x97", (output / "strings.txt").read_bytes())
        url_lines = [
            line.split(" ", 1)[1]
            for line in (output / "strings.txt")
            .read_text(encoding="latin-1")
            .splitlines()
            if line.startswith("str_mcp_")
        ]
        self.assertTrue(all("_" not in value for value in url_lines))
        self.assertTrue(any("/agents-end?" in value for value in url_lines))
        dialogue = (output / "conversation.txt").read_text(encoding="latin-1")
        self.assertIn("{s60}", dialogue)
        self.assertNotIn("{s126}", dialogue)
        self.assertEqual((output / "strings.txt").read_bytes().splitlines()[1], b"11")
        self.assertEqual(
            (output / "simple_triggers.txt").read_text().splitlines()[1], "2"
        )
        self.assertIn("other -1\n 0 ", (output / "scripts.txt").read_text())
        self.assertIn(
            "2.000000 0.000000 0.000000 0 ",
            (output / "mission_templates.txt").read_text(),
        )

    def test_callback_control_blocks_are_balanced(self):
        self.assert_balanced(callback())

    def test_battle_dispatch_contains_engine_readbacks_and_own_team(self):
        compiled = callback(battle_result_url=123)
        self.assert_balanced(compiled)
        for name in (
            "agent_get_team",
            "team_give_order",
            "team_get_movement_order",
            "team_get_hold_fire_order",
            "team_get_riding_order",
            "team_get_weapon_usage_order",
            "team_get_order_position",
        ):
            self.assertIn(f"{OPS[name]} ", compiled)

    def test_actual_poll_chain_blocks_are_balanced(self):
        self.assert_balanced(
            callback(poll_urls=(1, 2, 3), quest_count=91, skill_count=42)
        )

    def test_menu_bootstrap_preserves_native_register_inputs(self):
        output = self.root / "MenuGuard"
        build(self.native, output, "http://127.0.0.1", "a" * 64)
        menu = (output / "menus.txt").read_text().splitlines()[2].split()
        tokens = list(map(int, menu[4:-1]))
        operations = []
        cursor = 1
        for _ in range(tokens[0]):
            opcode, arity = tokens[cursor : cursor + 2]
            operations.append((opcode, tokens[cursor + 2 : cursor + 2 + arity]))
            cursor += 2 + arity
        self.assertEqual(cursor, len(tokens))
        for register in range(21):
            self.assertIn(
                (OPS["assign"], [(17 << 56) + 32 + register, (1 << 56) + register]),
                operations,
            )
            self.assertIn(
                (OPS["assign"], [(1 << 56) + register, (17 << 56) + 32 + register]),
                operations,
            )
        self.assertIn((OPS["copy_position"], [47, 1]), operations)
        self.assertIn((OPS["copy_position"], [1, 47]), operations)
        for register in range(32):
            self.assertIn(
                (
                    OPS["troop_set_slot"],
                    [5 << 56, 99940 + register, (1 << 56) + register],
                ),
                operations,
            )

    def test_menu_dispatch_blocks_are_balanced(self):
        self.assert_balanced(
            callback(
                poll_urls=(1, 2, 3),
                menu_actions=[
                    {
                        "id": 0,
                        "menu_id": 23,
                        "condition_script": 100,
                        "consequence_script": 101,
                    },
                    {
                        "id": 1,
                        "menu_id": 80,
                        "condition_script": 102,
                        "consequence_script": 103,
                    },
                ],
            )
        )

    def assert_balanced(self, bytecode):
        tokens = list(map(int, bytecode.split()))
        cursor, depth = 1, 0
        while cursor < len(tokens):
            opcode, arity = tokens[cursor : cursor + 2]
            if opcode in (
                OPS["try_begin"],
                OPS["try_for_agents"],
                OPS["try_for_range"],
                OPS["try_for_parties"],
            ):
                depth += 1
            elif opcode == OPS["try_end"]:
                depth -= 1
            elif opcode == OPS["else_try"]:
                self.assertGreater(depth, 0)
            self.assertGreaterEqual(depth, 0)
            cursor += 2 + arity
        self.assertEqual(depth, 0)

    def test_refuses_existing_output(self):
        output = self.root / "WarbandMCP"
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "new directory"):
            build(self.native, output, "http://127.0.0.1", "a" * 64)

    def test_refuses_nonempty_url_callback(self):
        (self.native / "scripts.txt").write_text(
            "game_receive_url_response -1\n 1 1106 1 0\n"
        )
        with self.assertRaisesRegex(ValueError, "empty Native URL callback"):
            build(self.native, self.root / "WarbandMCP", "http://127.0.0.1", "a" * 64)
        self.assertFalse((self.root / "WarbandMCP").exists())

    def test_refuses_custom_game_http_port(self):
        with self.assertRaisesRegex(ValueError, "port 80"):
            build(
                self.native, self.root / "WarbandMCP", "http://127.0.0.1:8765", "a" * 64
            )


if __name__ == "__main__":
    unittest.main()
