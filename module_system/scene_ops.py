"""Typed player/NPC controls, never raw bytecode or simulated desktop input."""

REG, LOCAL, TROOP = 1 << 56, 17 << 56, 5 << 56


def living_player(dialogue_slot):
    return [
        ("troop_get_slot", LOCAL + 29, TROOP, dialogue_slot),
        ("eq", LOCAL + 29, 0),
        ("get_player_agent_no", LOCAL + 25),
        ("ge", LOCAL + 25, 0),
        ("agent_is_active", LOCAL + 25),
        ("agent_is_alive", LOCAL + 25),
    ]


def actor_guard(dialogue_slot):
    return [
        *living_player(dialogue_slot),
        ("assign", LOCAL + 30, LOCAL + 5),
        ("assign", LOCAL + 31, 0),
        ("try_begin",),
        ("ge", LOCAL + 30, 10000),
        ("val_sub", LOCAL + 30, 10000),
        ("assign", LOCAL + 31, 1),
        ("try_end",),
        ("ge", LOCAL + 30, 0),
        ("lt", LOCAL + 30, 10000),
        ("agent_is_active", LOCAL + 30),
        ("agent_is_alive", LOCAL + 30),
        ("agent_is_human", LOCAL + 30),
        ("agent_get_team", LOCAL + 26, LOCAL + 25),
        ("agent_get_team", LOCAL + 27, LOCAL + 30),
        ("try_begin",),
        ("eq", LOCAL + 31, 0),
        ("eq", LOCAL + 26, LOCAL + 27),
        ("assign", LOCAL + 31, 1),
        ("try_end",),
        ("eq", LOCAL + 31, 1),
    ]


def bounded_destination(x, y, base_agent):
    # Position scratch registers 3/4 are restored before testing the bounds.
    return [
        ("agent_get_position", 2, base_agent),
        ("copy_position", 45, 3),
        ("copy_position", 46, 4),
        ("get_scene_boundaries", 3, 4),
        ("position_get_x", LOCAL + 26, 3),
        ("position_get_y", LOCAL + 27, 3),
        ("position_get_x", LOCAL + 28, 4),
        ("position_get_y", LOCAL + 29, 4),
        ("copy_position", 3, 45),
        ("copy_position", 4, 46),
        ("ge", x, LOCAL + 26),
        ("le", x, LOCAL + 28),
        ("ge", y, LOCAL + 27),
        ("le", y, LOCAL + 29),
        ("position_set_x", 2, x),
        ("position_set_y", 2, y),
        ("position_set_z_to_ground_level", 2),
    ]


def agent_combat(dialogue_slot):
    actor, code, duration = LOCAL + 30, LOCAL + 6, LOCAL + 16
    return [
        *actor_guard(dialogue_slot),
        ("ge", duration, 0),
        ("le", duration, 10000),
        # Native tutorial takes scripted/no-auto-attack control before driving
        # an NPC's combat actions. Player input is a separate engine controller.
        ("try_begin",),
        ("neq", actor, LOCAL + 25),
        ("agent_get_position", 2, actor),
        ("agent_set_scripted_destination_no_attack", actor, 2, 1),
        ("try_end",),
        ("try_begin",),
        ("ge", code, 0),
        ("le", code, 7),
        ("assign", LOCAL + 28, code),
        ("assign", LOCAL + 29, 0),
        ("try_begin",),
        ("ge", code, 4),
        ("val_sub", LOCAL + 28, 4),
        ("assign", LOCAL + 29, 1),
        ("try_end",),
        ("agent_set_attack_action", actor, LOCAL + 28, LOCAL + 29),
        ("assign", LOCAL + 10, 0),
        ("else_try",),
        ("eq", code, 8),
        ("agent_set_attack_action", actor, -2, 0),
        ("assign", LOCAL + 10, 0),
        ("else_try",),
        ("ge", code, 12),
        ("le", code, 15),
        ("store_sub", LOCAL + 28, code, 12),
        ("agent_set_defend_action", actor, LOCAL + 28, duration),
        ("assign", LOCAL + 10, 0),
        ("else_try",),
        ("eq", code, 16),
        ("agent_set_defend_action", actor, -2, 0),
        ("assign", LOCAL + 10, 0),
        ("try_end",),
    ]


def agent_move(dialogue_slot):
    return [
        *actor_guard(dialogue_slot),
        ("neq", LOCAL + 30, LOCAL + 25),
        *bounded_destination(LOCAL + 6, LOCAL + 16, LOCAL + 30),
        ("agent_set_scripted_destination", LOCAL + 30, 2, 1, 0),
        ("assign", LOCAL + 10, 0),
    ]


def agent_release(dialogue_slot):
    return [
        *actor_guard(dialogue_slot),
        ("neq", LOCAL + 30, LOCAL + 25),
        ("agent_clear_scripted_mode", LOCAL + 30),
        ("agent_force_rethink", LOCAL + 30),
        ("assign", LOCAL + 10, 0),
    ]


def agent_wield(dialogue_slot, item_count):
    return [
        *actor_guard(dialogue_slot),
        ("ge", LOCAL + 6, 0),
        ("lt", LOCAL + 6, item_count),
        ("agent_has_item_equipped", LOCAL + 30, LOCAL + 6),
        ("agent_set_wielded_item", LOCAL + 30, LOCAL + 6),
        ("assign", LOCAL + 10, 0),
    ]
