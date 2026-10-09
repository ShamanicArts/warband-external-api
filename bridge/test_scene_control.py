import unittest

from bridge.protocol import validate_operation, wire_arguments


class SceneControlTests(unittest.TestCase):
    def test_native_dialogue_is_scoped_without_injected_text_or_world_override(self):
        state = {
            **self.state,
            "integration_revision": 15,
            "mission_flags": 0,
            "mission_template": "village_center",
        }
        validate_operation("native_dialogue", {"agent_id": 7}, state)
        self.assertEqual(
            wire_arguments("native_dialogue", {"agent_id": 7}), [7, 0, 0, 0]
        )
        for change in (
            {"text": "injected"},
            {"world_control": True},
            {"agent_id": True},
        ):
            with self.assertRaises(ValueError):
                validate_operation("native_dialogue", {"agent_id": 7, **change}, state)
        for change in (
            {"integration_revision": 14},
            {"mission_flags": 2},
            {"mission_template": "tutorial_training_ground"},
            {"dialogue_active": True},
            {"player_hit_points": 0},
        ):
            with self.assertRaises(ValueError):
                validate_operation(
                    "native_dialogue", {"agent_id": 7}, {**state, **change}
                )

    def setUp(self):
        self.state = {
            "connected": True,
            "protocol": 2,
            "context": "mission",
            "integration_revision": 7,
            "mission_flags": 2,
            "dialogue_active": False,
            "player_hit_points": 75,
            "player_agent_id": 0,
            "position": {"x": 12, "y": 20},
        }

    def test_combat_encoding_preserves_direction_and_world_permission(self):
        args = {
            "agent_id": 0,
            "action": "attack_hold",
            "direction": "up",
            "duration_ms": 0,
            "world_control": False,
        }
        validate_operation("agent_combat", args, self.state)
        self.assertEqual(wire_arguments("agent_combat", args), [0, 7, 0, 0])
        args.update(agent_id=3, world_control=True, action="block", duration_ms=1000)
        validate_operation("agent_combat", args, self.state)
        self.assertEqual(wire_arguments("agent_combat", args), [10003, 15, 1000, 0])

    def test_walking_is_not_player_input_or_teleport(self):
        args = {"agent_id": 3, "x": 20.25, "y": -3, "world_control": False}
        validate_operation("agent_move", args, self.state)
        self.assertEqual(wire_arguments("agent_move", args), [3, 2025, -300, 0])
        with self.assertRaisesRegex(ValueError, "NPC"):
            validate_operation("agent_move", {**args, "agent_id": 0}, self.state)

    def test_release_has_explicit_world_control(self):
        args = {"agent_id": 4, "world_control": True}
        validate_operation("agent_release", args, self.state)
        self.assertEqual(wire_arguments("agent_release", args), [10004, 0, 0, 0])

    def test_wield_requires_item_id_and_encodes_no_spawning(self):
        args = {"agent_id": 0, "item_id": 380, "world_control": False}
        validate_operation("agent_wield", args, self.state)
        self.assertEqual(wire_arguments("agent_wield", args), [0, 380, 0, 0])
        for item in (True, -1, 10000, "380"):
            with self.assertRaises(ValueError):
                validate_operation("agent_wield", {**args, "item_id": item}, self.state)

    def test_formation_position_fixed_point_and_battle_guard(self):
        args = {"formation": 9, "x": 18.5, "y": 24}
        validate_operation("formation_position", args, self.state)
        self.assertEqual(wire_arguments("formation_position", args), [9, 1850, 2400, 0])
        with self.assertRaises(ValueError):
            validate_operation(
                "formation_position", args, {**self.state, "mission_flags": 0}
            )

    def test_malformed_and_unbounded_combat_actions_rejected(self):
        valid = {
            "agent_id": 0,
            "action": "block",
            "direction": "left",
            "duration_ms": 1000,
            "world_control": False,
        }
        for change in (
            {"agent_id": True},
            {"world_control": 1},
            {"direction": "north"},
            {"action": "kill"},
            {"duration_ms": 10001},
            {"duration_ms": -1},
        ):
            with self.assertRaises(ValueError):
                validate_operation("agent_combat", {**valid, **change}, self.state)

    def test_old_build_dialogue_and_dead_player_rejected(self):
        args = {"agent_id": 3, "world_control": False}
        for change in (
            {"integration_revision": 6},
            {"dialogue_active": True},
            {"player_hit_points": 0},
            {"context": "campaign"},
        ):
            with self.assertRaises(ValueError):
                validate_operation("agent_release", args, {**self.state, **change})

    def test_scene_coordinates_are_bounded_finite_not_bools(self):
        for x in (True, float("nan"), float("inf"), 10001, "20"):
            with self.assertRaises(ValueError):
                validate_operation(
                    "agent_move",
                    {
                        "agent_id": 3,
                        "x": x,
                        "y": 10,
                        "world_control": False,
                    },
                    self.state,
                )
