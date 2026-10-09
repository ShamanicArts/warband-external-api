import unittest

from module_system.dialogue_actions import (
    dialogue_catalog,
    instrument_dialogues,
    parse_dialogue_states,
    parse_dialogues,
    player_choice_catalog,
)


class DialogueActionTests(unittest.TestCase):
    def setUp(self):
        self.states = parse_dialogue_states(
            ["start", "elder_talk", "elder_tasks", "close_window"]
        )
        self.lines = [
            "dialogsfile version 2",
            "3",
            "dlga_start:elder_talk 4095 0  0 Welcome.  1  0 NO_VOICEOVER",
            (
                "dlga_elder_talk:elder_tasks 69631 1  "
                "1 31 2 7 7 Ask_about_tasks.  2  "
                "1 2133 2 8 9 NO_VOICEOVER"
            ),
            "dlga_elder_talk:close_window 69631 1  0 Leave.  3  0 NO_VOICEOVER",
        ]

    def test_parses_npc_lines_and_player_choices_as_static_candidates(self):
        entries = parse_dialogues(self.lines, self.states)
        self.assertEqual(len(entries), 3)
        self.assertFalse(entries[0]["player_choice"])
        self.assertTrue(entries[1]["player_choice"])
        self.assertEqual(entries[1]["input_state"], "elder_talk")
        self.assertEqual(entries[1]["output_state"], "elder_tasks")
        self.assertEqual(entries[1]["condition"], ["1", "31", "2", "7", "7"])
        self.assertEqual(
            entries[1]["consequence"], ["1", "2133", "2", "8", "9"]
        )

    def test_catalog_omits_raw_operations_and_npc_lines(self):
        catalog = player_choice_catalog(parse_dialogues(self.lines, self.states))
        self.assertEqual([row["id"] for row in catalog], [1, 2])
        self.assertEqual(catalog[0]["text_template"], "Ask about tasks.")
        self.assertNotIn("condition", catalog[0])
        self.assertNotIn("consequence", catalog[0])

        all_entries = dialogue_catalog(parse_dialogues(self.lines, self.states))
        self.assertEqual([row["id"] for row in all_entries], [0, 1, 2])
        self.assertFalse(all_entries[0]["player_choice"])
        self.assertNotIn("condition", all_entries[1])
        self.assertNotIn("consequence", all_entries[1])

    def test_instrumentation_appends_only_to_consequences(self):
        entries = parse_dialogues(self.lines, self.states)
        result = instrument_dialogues(
            self.lines,
            entries,
            lambda entry: f"1 2133 2 72057594037927956 {entry['id']}",
        )
        rewritten = parse_dialogues(result, self.states)
        for before, after in zip(entries, rewritten, strict=True):
            for key in (
                "symbol",
                "speaker",
                "input_state_id",
                "output_state_id",
                "text_template",
                "condition",
                "voiceover",
            ):
                self.assertEqual(after[key], before[key])
            self.assertEqual(
                int(after["consequence"][0]), int(before["consequence"][0]) + 1
            )
            self.assertEqual(after["consequence"][1:-4], before["consequence"][1:])
            self.assertEqual(
                after["consequence"][-4:],
                ["2133", "2", "72057594037927956", str(before["id"])],
            )

    def test_instrumentation_refuses_invalid_suffix(self):
        entries = parse_dialogues(self.lines, self.states)
        with self.assertRaisesRegex(ValueError, "instrumentation seam"):
            instrument_dialogues(self.lines, entries, lambda _entry: "1 2133 3 1")

    def test_refuses_count_and_operation_seam_mismatches(self):
        bad_count = [*self.lines]
        bad_count[1] = "4"
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            parse_dialogues(bad_count, self.states)

        bad_operation = [*self.lines]
        bad_operation[3] = bad_operation[3].replace("1 31 2 7 7", "1 31 3 7 7")
        with self.assertRaisesRegex(ValueError, "line 4"):
            parse_dialogues(bad_operation, self.states)

    def test_refuses_duplicate_state_names(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse_dialogue_states(["start", "start"])


if __name__ == "__main__":
    unittest.main()
