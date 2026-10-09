import unittest

from module_system.menu_hooks import instrument_menus


class MenuHookTests(unittest.TestCase):
    def test_preserves_ids_conditions_and_prefixes_returns(self):
        lines = [
            "menusfile version 1",
            "1",
            "menu_test 0 Test. none 1 2133 2 0 42 2",
            " mno_leave 1 31 2 1 1 Leave. 1 2040 0 . mno_stay 0 Stay. 1 2060 1 99 .",
        ]
        output, names = instrument_menus(
            lines, lambda mid: "1 500 3 0 99989 0", "1 500 3 0 99994 0"
        )
        self.assertEqual(names, ["test"])
        self.assertEqual(
            output[2], "menu_test 0 Test. none 2 500 3 0 99989 0 2133 2 0 42 2"
        )
        self.assertIn(
            "mno_leave 1 31 2 1 1 Leave. 2 500 3 0 99994 0 2040 0 .", output[3]
        )
        self.assertIn("mno_stay 0 Stay. 1 2060 1 99 .", output[3])

    def test_malformed_menu_does_not_mutate_source(self):
        lines = ["menu_test 0 Test. none 1 2133 2 0"]
        before = list(lines)
        with self.assertRaisesRegex(ValueError, "menu_test"):
            instrument_menus(lines, lambda mid: "0")
        self.assertEqual(lines, before)

    def test_malformed_option_refuses_build(self):
        lines = ["menu_test 0 Test. none 0 1", " mno_leave 0 Leave. 1 2040 0"]
        with self.assertRaisesRegex(ValueError, "option seam"):
            instrument_menus(lines, lambda mid: "0", "1 500 3 0 99994 0")

    def test_actual_native_door_option_preserves_tooltip(self):
        lines = [
            "menu_zendar 16 Zendar. none 0 1",
            " mno_zendar_enter 0 _ 1 2040 0 Door_to_the_town_center.",
        ]
        output, _ = instrument_menus(lines, lambda mid: "0", "1 500 3 0 99994 0")
        self.assertIn("2 500 3 0 99994 0 2040 0 Door_to_the_town_center.", output[1])


if __name__ == "__main__":
    unittest.main()
