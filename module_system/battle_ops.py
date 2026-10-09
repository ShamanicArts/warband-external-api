"""Player-team-only Native orders with per-formation engine read-back."""

from module_system.scene_ops import bounded_destination

REG, LOCAL, TROOP = 1 << 56, 17 << 56, 5 << 56


def battle_order(result_url, mission_flags_slot, dialogue_slot, placement=False):
    # Same callback argument locals as the other allowlisted operations.
    job, group, order, result = LOCAL + 3, LOCAL + 5, LOCAL + 6, LOCAL + 10
    team, start, end, index = LOCAL + 25, LOCAL + 26, LOCAL + 27, LOCAL + 28
    return [
        ("troop_get_slot", team, TROOP, mission_flags_slot),
        ("val_and", team, 2),
        ("eq", team, 2),
        ("troop_get_slot", team, TROOP, dialogue_slot),
        ("eq", team, 0),
        ("ge", group, 0),
        ("le", group, 9),
        *([] if placement else [("ge", order, 0), ("le", order, 14)]),
        ("get_player_agent_no", index),
        ("ge", index, 0),
        ("agent_is_active", index),
        ("agent_is_alive", index),
        ("agent_get_team", team, index),
        *(
            [
                # Boundary checks use scratch locals 26–29, not the team in local25.
                *bounded_destination(LOCAL + 6, LOCAL + 16, index),
            ]
            if placement
            else []
        ),
        ("assign", REG + 30, LOCAL + 9),
        ("assign", REG + 31, LOCAL + 8),
        ("team_give_order", team, group, 0 if placement else order),
        *([("team_set_order_position", team, group, 2)] if placement else []),
        ("assign", start, group),
        ("store_add", end, group, 1),
        ("try_begin",),
        ("eq", group, 9),
        ("assign", start, 0),
        ("assign", end, 9),
        ("try_end",),
        ("try_for_range", index, start, end),
        ("assign", REG + 20, job),
        ("assign", REG + 21, team),
        ("assign", REG + 22, index),
        ("team_get_movement_order", REG + 23, team, index),
        ("team_get_hold_fire_order", REG + 24, team, index),
        ("team_get_riding_order", REG + 25, team, index),
        ("team_get_weapon_usage_order", REG + 26, team, index),
        ("team_get_order_position", 2, team, index),
        ("position_get_x", REG + 27, 2),
        ("position_get_y", REG + 28, 2),
        ("str_store_string", 127, result_url),
        ("send_message_to_url", 127, 0),
        ("try_end",),
        ("assign", result, 0),
    ]
