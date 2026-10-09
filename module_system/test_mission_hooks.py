import unittest

from module_system.mission_hooks import instrument_missions


class MissionHookTests(unittest.TestCase):
    def mission(self, name, spawns=1):
        return [
            f"mst_{name} {name} 2 -1",
            "Description.",
            "",
            "0" if spawns == 0 else "1 0 0 0",
            "1",
            "0.000000 0.000000 0.000000 0 0",
            "",
        ]

    def test_instruments_all_single_player_and_preserves_multiplayer(self):
        lines = (
            self.mission("town_center")
            + self.mission("multiplayer_dm")
            + self.mission("lead_charge", 0)
        )
        output, names = instrument_missions(
            lines, lambda mid, flags: [f"2.000000 0.000000 0.000000 0 1 2133 2 0 {mid}"]
        )
        self.assertEqual(names, ["town_center", "lead_charge"])
        self.assertEqual(output[4], "2")
        index = output.index("mst_multiplayer_dm multiplayer_dm 2 -1")
        self.assertEqual(output[index : index + 7], self.mission("multiplayer_dm"))
        self.assertIn("2.000000 0.000000 0.000000 0 1 2133 2 0 2", output)

    def test_bad_seam_does_not_mutate_source(self):
        lines = self.mission("town_center")
        lines[4] = "999"
        before = list(lines)
        with self.assertRaisesRegex(ValueError, "town_center"):
            instrument_missions(lines, lambda mid, flags: [])
        self.assertEqual(lines, before)

    def test_actual_native_zero_spawn_camera_format(self):
        lines = [
            "mst_camera_test camera_test 0 -1",
            "camera_Test.",
            "",
            "0 2",
            "1.000000 0.000000 0.000000 3 2001 1 1 1780 2 3 3 2011 1 3 0",
            "-21.000000 0.000000 0.000000 0 1 1907 1 0",
            "",
        ]
        output, names = instrument_missions(
            lines, lambda mid, flags: ["2.000000 0.000000 0.000000 0 0"]
        )
        self.assertEqual(output[3], "0 3")
        self.assertEqual(output[4:6], lines[4:6])
        self.assertEqual(names, ["camera_test"])

    def test_only_multiplayer_refuses_empty_instrumentation(self):
        with self.assertRaisesRegex(ValueError, "No single-player"):
            instrument_missions(self.mission("multiplayer_dm"), lambda mid, flags: [])


if __name__ == "__main__":
    unittest.main()
