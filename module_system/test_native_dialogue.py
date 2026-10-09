"""Candidate structure tests only; not live Native dialogue acceptance."""

import unittest

from module_system.native_dialogue import dialogue_sampler, native_entry
from module_system.scene_ops import LOCAL


class NativeDialogueTests(unittest.TestCase):
    def test_predicate_is_separate_from_callback_entry(self):
        sample = dialogue_sampler(99986)
        entry = native_entry(99986, 99996, 99990, 1000)
        self.assertIn(("conversation_screen_is_active",), sample)
        self.assertNotIn("conversation_screen_is_active", [op[0] for op in entry])
        self.assertNotIn("str_store_string", [op[0] for op in entry])
        self.assertEqual(entry[-1], ("start_mission_conversation", LOCAL + 26))

    def test_distance_and_unique_troop_guards_precede_engine_start(self):
        entry = native_entry(99986, 99996, 99990, 1000)
        self.assertIn(("eq", LOCAL + 27, 1), entry[:-1])
        self.assertIn(("le", LOCAL + 29, 400), entry[:-1])
        self.assertIn("agent_is_alive", [op[0] for op in entry[:-1]])
        self.assertIn("agent_is_human", [op[0] for op in entry[:-1]])
        self.assertNotIn("agent_set_position", [op[0] for op in entry])
