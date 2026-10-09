"""Add real engine scripts to a fresh Native copy; never modify Native/Pendor.

Opcodes verified against TaleWorlds ModSys 1.171 mirror at
int19h/mb_warband_module_system f718b182eb25ae21c3095e89bdba5d95158a682f.
This deliberately does not import the old, incorrect header_operations.py.
"""

import argparse
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from module_system.battle_ops import battle_order
from module_system.campaign_ops import campaign_export
from module_system.goods_trade import goods_trade
from module_system.market_ops import market_export
from module_system.menu_actions import append_actions
from module_system.menu_hooks import instrument_menus
from module_system.mission_departure import leave_town_ops, recognize_town_permission
from module_system.mission_hooks import instrument_missions
from module_system.scene_ops import agent_combat, agent_move, agent_release, agent_wield
from module_system.world_ops import diplomacy, party_order, world_encounter
from module_system.world_ops import query as world_query

REG = 1 << 56
STR = 3 << 56
LOCAL = 17 << 56
TROOP = 5 << 56
PARTY = 9 << 56
ACK_SLOT = 99999  # Reserved by this isolated mod on trp_player.
RESULT_SLOT, NPC_SLOT, READY_SLOT, JOB_SLOT = 99998, 99997, 99996, 99995
CONTEXT_SLOT, SESSION_SLOT = 99994, 99993
NPC_AGENT_SLOT = 99992
MISSION_SLOT, MISSION_FLAGS_SLOT = 99991, 99990
MENU_SLOT, POLL_NONCE_SLOT, DIALOG_ACTIVE_SLOT = 99989, 99988, 99986
MENU_SESSION_SLOT, MENU_RESULT_SLOT, MENU_REG_BASE = 99985, 99984, 99940
SCRIPT = 13 << 56

# Official operation names and values, not the previous prototype's headers.
OPS = {
    "try_begin": 4,
    "else_try": 5,
    "try_end": 3,
    "eq": 31,
    "ge": 30,
    "gt": 32,
    "assign": 2133,
    "store_script_param": 23,
    "str_store_string": 2320,
    "send_message_to_url": 380,
    "troop_get_slot": 520,
    "troop_set_slot": 500,
    "get_player_agent_no": 1700,
    "agent_get_troop_id": 1718,
    "store_agent_hit_points": 1720,
    "agent_get_position": 1710,
    "position_get_x": 726,
    "position_get_y": 727,
    "position_get_z": 728,
    "set_fixed_point_multiplier": 2124,
    "store_troop_gold": 2149,
    "display_message": 1106,
    "party_get_position": 1625,
    "store_current_hours": 2270,
    "store_mission_timer_a": 2370,
    "val_add": 2105,
    "store_current_scene": 2211,
    "try_for_agents": 12,
    "agent_is_alive": 1702,
    "agent_is_human": 1704,
    "agent_is_active": 1712,
    "agent_get_team": 1770,
    "agent_set_position": 1711,
    "position_set_x": 729,
    "position_set_y": 730,
    "position_set_z_to_ground_level": 791,
    "str_store_string_reg": 2321,
    "start_mission_conversation": 1920,
    "store_conversation_troop": 2200,
    "store_sub": 2121,
    "store_conversation_agent": 2199,
    "store_mul": 2122,
    "store_add": 2120,
    "le": 0x80000000 | 32,
    "neq": 0x80000000 | 31,
    "lt": 0x80000000 | 30,
    "try_for_range": 6,
    "try_for_parties": 11,
    "party_is_active": 132,
    "party_get_num_companion_stacks": 1650,
    "party_get_num_prisoner_stacks": 1651,
    "party_stack_get_troop_id": 1652,
    "party_stack_get_size": 1653,
    "party_stack_get_num_wounded": 1654,
    "party_prisoner_stack_get_troop_id": 1656,
    "party_prisoner_stack_get_size": 1657,
    "troop_get_inventory_capacity": 1540,
    "troop_get_inventory_slot": 1541,
    "troop_get_inventory_slot_modifier": 1542,
    "troop_inventory_slot_get_item_amount": 1537,
    "store_character_level": 2171,
    "store_attribute_level": 2172,
    "store_skill_level": 2170,
    "store_faction_of_party": 2204,
    "party_get_template_id": 1609,
    "party_get_slot": 521,
    "party_get_num_companions": 1601,
    "check_quest_active": 200,
    "quest_get_slot": 526,
    "not_multiplayer": 0x80000000 | 419,
    "val_and": 2115,
    "copy_position": 700,
    "call_script": 1,
    "team_get_hold_fire_order": 1784,
    "team_get_movement_order": 1785,
    "team_get_riding_order": 1786,
    "team_get_weapon_usage_order": 1787,
    "team_give_order": 1790,
    "team_get_order_position": 1794,
    "team_set_order_position": 1791,
    "get_scene_boundaries": 1799,
    "val_sub": 2106,
    "agent_set_attack_action": 1745,
    "agent_set_defend_action": 1746,
    "agent_get_attack_action": 1763,
    "agent_get_defend_action": 1764,
    "agent_get_action_dir": 1767,
    "agent_get_wielded_item": 1726,
    "agent_get_scripted_destination": 1731,
    "agent_set_scripted_destination": 1730,
    "agent_clear_scripted_mode": 1735,
    "agent_force_rethink": 1732,
    "agent_has_item_equipped": 1729,
    "agent_set_wielded_item": 1747,
    "agent_get_item_slot": 1804,
    "agent_set_scripted_destination_no_attack": 1748,
    "or_eq": 0x40000000 | 31,
    "store_relation": 2190,
    "faction_get_slot": 522,
    "faction_get_color": 1277,
    "faction_slot_eq": 542,
    "get_party_ai_behavior": 2290,
    "get_party_ai_object": 2291,
    "party_get_ai_initiative": 1638,
    "party_set_ai_behavior": 1640,
    "party_set_ai_object": 1641,
    "rest_for_hours": 1030,
    "rest_for_hours_interactive": 1031,
    "troop_inventory_slot_get_item_max_amount": 1538,
    "store_item_value": 2230,
    "store_mod": 2119,
    "val_mul": 2107,
    "val_div": 2108,
    "store_div": 2123,
    "troop_add_gold": 1528,
    "troop_remove_gold": 1529,
    "troop_inventory_slot_set_item_amount": 1534,
    "troop_set_inventory_slot": 1543,
    "troop_set_inventory_slot_modifier": 1544,
    "item_get_type": 1570,
    "not_item_has_property": 2723 | 0x80000000,
    "map_free": 37,
    "start_encounter": 1300,
    "finish_mission": 1907,
}


def compile_ops(operations):
    return (
        str(len(operations))
        + " "
        + " ".join(
            " ".join(map(str, (OPS[name], len(args), *args)))
            for name, *args in operations
        )
    )


def telemetry_ops(url_string, mission, native_globals=None, context=None):
    ops = [
        ("not_multiplayer",),
        *(([("party_is_active", PARTY)]) if not mission else []),
        *(
            [("assign", native_globals["mcp_http_active"], 1)]
            if native_globals and "mcp_http_active" in native_globals
            else []
        ),
        ("set_fixed_point_multiplier", 100),
        (
            "troop_set_slot",
            TROOP,
            CONTEXT_SLOT,
            int(mission) if context is None else context,
        ),
        ("troop_get_slot", REG + 18, TROOP, POLL_NONCE_SLOT),
        ("val_add", REG + 18, 1),
        ("troop_set_slot", TROOP, POLL_NONCE_SLOT, REG + 18),
        ("troop_get_slot", REG + 0, TROOP, ACK_SLOT),
        ("store_troop_gold", REG + 1, TROOP),
        ("troop_get_slot", REG + 10, TROOP, RESULT_SLOT),
        ("troop_get_slot", REG + 11, TROOP, SESSION_SLOT),
    ]
    if mission:
        ops += [
            ("get_player_agent_no", LOCAL),
            ("ge", LOCAL, 0),
            ("agent_is_active", LOCAL),
            ("agent_get_troop_id", REG + 2, LOCAL),
            ("store_agent_hit_points", REG + 3, LOCAL, 1),
            ("agent_get_position", 1, LOCAL),
            ("store_mission_timer_a", REG + 7),
            ("store_current_scene", REG + 8),
            ("assign", REG + 9, LOCAL),
            ("troop_get_slot", REG + 12, TROOP, MISSION_SLOT),
            ("troop_get_slot", REG + 13, TROOP, MISSION_FLAGS_SLOT),
        ]
    else:
        ops += [
            ("assign", REG + 2, 0),
            ("assign", REG + 3, -1),
            ("party_get_position", 1, PARTY),
            ("store_current_hours", REG + 7),
            ("assign", REG + 8, -1),
            ("assign", REG + 9, -1),
            ("assign", REG + 11, -1),
            ("assign", REG + 12, -1),
            ("assign", REG + 13, 0),
        ]
    ops += [
        ("troop_get_slot", REG + 17, TROOP, MENU_SLOT),
        ("troop_get_slot", REG + 19, TROOP, DIALOG_ACTIVE_SLOT),
        ("troop_get_slot", REG + 20, TROOP, MENU_SESSION_SLOT),
    ]
    ops += [
        ("assign", REG + register, (native_globals or {}).get(name, -1))
        for register, name in (
            (14, "g_player_is_captive"),
            (15, "current_town"),
            (16, "g_encountered_party"),
        )
    ]
    ops += [
        ("position_get_x", REG + 4, 1),
        ("position_get_y", REG + 5, 1),
        ("position_get_z", REG + 6, 1),
        ("str_store_string", 127, url_string),
        ("send_message_to_url", 127, 0),
    ]
    return ops


def telemetry(url_string, mission, native_globals=None, context=None):
    return compile_ops(telemetry_ops(url_string, mission, native_globals, context))


def callback(
    agent_url=0,
    end_url=0,
    campaign_row_url=0,
    campaign_end_url=0,
    quest_count=0,
    skill_count=0,
    poll_urls=None,
    native_globals=None,
    menu_actions=None,
    battle_result_url=0,
    item_count=0,
    world_result_url=0,
    faction_count=0,
    kingdom_ids=None,
    native_scripts=None,
    merchant_row_url=0,
    merchant_end_url=0,
    troop_count=0,
    market_menu_id=-1,
    trade_result_url=0,
    town_departure_id=None,
):
    cmd, kind, a, b, session, scene, result, tmp, agent, count = [
        LOCAL + i for i in (3, 4, 5, 6, 8, 9, 10, 11, 12, 13)
    ]
    scan = [
        ("assign", REG + 20, cmd),
        ("assign", REG + 30, scene),
        ("assign", REG + 31, session),
        ("assign", count, 0),
        ("get_player_agent_no", LOCAL + 14),
        ("try_for_agents", agent),
        ("agent_is_active", agent),
        ("agent_is_alive", agent),
        ("agent_is_human", agent),
        ("le", count, 63),
        ("val_add", count, 1),
        ("assign", REG + 21, agent),
        ("agent_get_troop_id", REG + 22, agent),
        ("agent_get_team", REG + 23, agent),
        ("store_agent_hit_points", REG + 24, agent, 1),
        ("agent_get_position", 2, agent),
        ("position_get_x", REG + 25, 2),
        ("position_get_y", REG + 26, 2),
        ("position_get_z", REG + 27, 2),
        ("agent_get_attack_action", REG + 32, agent),
        ("agent_get_defend_action", REG + 33, agent),
        ("agent_get_action_dir", REG + 34, agent),
        ("agent_get_wielded_item", REG + 35, agent, 0),
        ("agent_get_scripted_destination", 2, agent),
        ("position_get_x", REG + 36, 2),
        ("position_get_y", REG + 37, 2),
        *[("agent_get_item_slot", REG + 38 + i, agent, i) for i in range(4)],
        ("assign", REG + 28, 0),
        ("try_begin",),
        ("eq", agent, LOCAL + 14),
        ("assign", REG + 28, 1),
        ("try_end",),
        ("str_store_string", 127, agent_url),
        ("send_message_to_url", 127, 0),
        ("try_end",),
        ("assign", REG + 29, count),
        ("str_store_string", 127, end_url),
        ("send_message_to_url", 127, 0),
        ("assign", result, 0),
    ]
    relocate = [
        ("troop_get_slot", tmp, TROOP, DIALOG_ACTIVE_SLOT),
        ("eq", tmp, 0),
        ("get_player_agent_no", agent),
        ("ge", agent, 0),
        ("agent_is_active", agent),
        ("agent_is_alive", agent),
        ("agent_get_position", 2, agent),
        ("position_get_x", LOCAL + 14, 2),
        ("position_get_y", LOCAL + 15, 2),
        ("store_sub", LOCAL + 14, a, LOCAL + 14),
        ("store_sub", LOCAL + 15, b, LOCAL + 15),
        ("store_mul", LOCAL + 14, LOCAL + 14, LOCAL + 14),
        ("store_mul", LOCAL + 15, LOCAL + 15, LOCAL + 15),
        ("store_add", LOCAL + 14, LOCAL + 14, LOCAL + 15),
        ("le", LOCAL + 14, 1000000),
        ("position_set_x", 2, a),
        ("position_set_y", 2, b),
        ("position_set_z_to_ground_level", 2),
        ("agent_set_position", agent, 2),
        ("assign", result, 0),
    ]
    npc = [
        ("troop_get_slot", tmp, TROOP, DIALOG_ACTIVE_SLOT),
        ("eq", tmp, 0),
        ("troop_get_slot", tmp, TROOP, MISSION_FLAGS_SLOT),
        ("val_and", tmp, 2),
        ("eq", tmp, 0),
        ("agent_is_active", a),
        ("agent_is_alive", a),
        ("agent_is_human", a),
        ("get_player_agent_no", agent),
        ("neq", a, agent),
        ("agent_get_troop_id", tmp, a),
        ("str_store_string_reg", 126, 0),
        ("troop_set_slot", TROOP, NPC_SLOT, tmp),
        ("troop_set_slot", TROOP, NPC_AGENT_SLOT, a),
        ("troop_set_slot", TROOP, READY_SLOT, 1),
        ("troop_set_slot", TROOP, JOB_SLOT, cmd),
        ("assign", result, 0),
        ("start_mission_conversation", tmp),
    ]
    choose_menu = []
    for index, action in enumerate(menu_actions or []):
        choose_menu += [
            ("try_begin",) if index == 0 else ("else_try",),
            ("eq", a, action["id"]),
            ("troop_get_slot", tmp, TROOP, MENU_SLOT),
            ("eq", tmp, action["menu_id"]),
            *[("troop_get_slot", REG + i, TROOP, MENU_REG_BASE + i) for i in range(32)],
            ("call_script", SCRIPT + action["condition_script"]),
            ("troop_get_slot", result, TROOP, MENU_RESULT_SLOT),
            ("eq", result, 0),
            ("call_script", SCRIPT + action["consequence_script"]),
        ]
    if choose_menu:
        choose_menu += [("try_end",)]
    return compile_ops(
        [
            *(
                [("eq", native_globals["mcp_http_active"], 1)]
                if native_globals and "mcp_http_active" in native_globals
                else []
            ),
            ("store_script_param", LOCAL, 1),
            ("not_multiplayer",),
            ("ge", LOCAL, 10 if poll_urls else 9),
            ("store_script_param", LOCAL + 2, 2),
            ("ge", LOCAL + 2, 1),
            ("eq", REG, 741731),
            ("eq", REG + 1, 2),
            ("assign", LOCAL + 24, REG + 9),
            ("try_begin",),
            ("troop_get_slot", LOCAL + 1, TROOP, ACK_SLOT),
            ("gt", REG + 2, LOCAL + 1),
            ("assign", cmd, REG + 2),
            ("assign", kind, REG + 3),
            ("assign", a, REG + 4),
            ("assign", b, REG + 5),
            ("assign", LOCAL + 16, REG + 6),
            ("assign", session, REG + 7),
            ("assign", scene, REG + 8),
            ("assign", result, -1),
            ("set_fixed_point_multiplier", 100),
            ("try_begin",),
            ("eq", kind, 1),
            ("display_message", 0, 0x66FFAA),
            ("assign", result, 0),
            ("else_try",),
            ("or_eq", kind, 6),
            ("or_eq", kind, 17),
            ("eq", kind, 18),
            ("troop_get_slot", tmp, TROOP, CONTEXT_SLOT),
            ("eq", tmp, 2),
            ("troop_get_slot", tmp, TROOP, MENU_SESSION_SLOT),
            ("eq", tmp, session),
            ("troop_get_slot", tmp, TROOP, MENU_SLOT),
            ("eq", tmp, scene),
            ("troop_get_slot", tmp, TROOP, DIALOG_ACTIVE_SLOT),
            ("eq", tmp, 0),
            ("try_begin",),
            ("eq", kind, 6),
            *choose_menu,
            ("else_try",),
            ("eq", kind, 17),
            *market_export(
                merchant_row_url,
                merchant_end_url,
                native_globals or {},
                native_scripts or {},
                troop_count,
                market_menu_id,
            ),
            ("else_try",),
            ("eq", kind, 18),
            *goods_trade(
                trade_result_url,
                native_globals or {},
                native_scripts or {},
                troop_count,
                item_count,
                market_menu_id,
            ),
            ("try_end",),
            ("else_try",),
            ("troop_get_slot", tmp, TROOP, CONTEXT_SLOT),
            ("eq", tmp, 1),
            ("troop_get_slot", tmp, TROOP, SESSION_SLOT),
            ("eq", tmp, session),
            ("store_current_scene", tmp),
            ("eq", tmp, scene),
            ("try_begin",),
            ("eq", kind, 2),
            *scan,
            ("else_try",),
            ("eq", kind, 3),
            *relocate,
            ("else_try",),
            ("eq", kind, 4),
            *npc,
            ("else_try",),
            ("eq", kind, 7),
            *battle_order(battle_result_url, MISSION_FLAGS_SLOT, DIALOG_ACTIVE_SLOT),
            ("else_try",),
            ("eq", kind, 8),
            *battle_order(
                battle_result_url,
                MISSION_FLAGS_SLOT,
                DIALOG_ACTIVE_SLOT,
                placement=True,
            ),
            ("else_try",),
            ("eq", kind, 9),
            *agent_combat(DIALOG_ACTIVE_SLOT),
            ("else_try",),
            ("eq", kind, 10),
            *agent_move(DIALOG_ACTIVE_SLOT),
            ("else_try",),
            ("eq", kind, 11),
            *agent_release(DIALOG_ACTIVE_SLOT),
            ("else_try",),
            ("eq", kind, 12),
            *agent_wield(DIALOG_ACTIVE_SLOT, item_count),
            ("else_try",),
            ("eq", kind, 20),
            *leave_town_ops(
                town_departure_id,
                native_globals or {},
                MISSION_SLOT,
                MISSION_FLAGS_SLOT,
                DIALOG_ACTIVE_SLOT,
            ),
            ("try_end",),
            ("else_try",),
            ("eq", kind, 5),
            ("troop_get_slot", tmp, TROOP, CONTEXT_SLOT),
            ("neq", tmp, 1),
            ("eq", scene, -1),
            ("eq", session, -1),
            ("ge", a, 1),
            ("le", a, 6),
            ("ge", b, 0),
            ("le", b, 100000),
            ("ge", LOCAL + 16, 1),
            ("le", LOCAL + 16, 16),
            *campaign_export(
                campaign_row_url, campaign_end_url, quest_count, skill_count
            ),
            ("else_try",),
            ("eq", kind, 13),
            ("troop_get_slot", tmp, TROOP, CONTEXT_SLOT),
            ("neq", tmp, 1),
            ("eq", scene, -1),
            ("eq", session, -1),
            *world_query(world_result_url, faction_count),
            ("else_try",),
            ("or_eq", kind, 14),
            ("eq", kind, 15),
            ("troop_get_slot", tmp, TROOP, CONTEXT_SLOT),
            ("eq", tmp, 0),
            ("eq", scene, -1),
            ("eq", session, -1),
            ("eq", (native_globals or {}).get("g_player_is_captive", -1), 0),
            ("try_begin",),
            ("eq", kind, 14),
            *diplomacy(
                world_result_url,
                kingdom_ids or [],
                native_scripts or {},
                native_globals or {},
            ),
            ("else_try",),
            ("eq", kind, 15),
            *party_order(world_result_url),
            ("try_end",),
            ("else_try",),
            ("eq", kind, 16),
            ("troop_get_slot", tmp, TROOP, CONTEXT_SLOT),
            ("eq", tmp, 0),
            ("eq", scene, -1),
            ("eq", session, -1),
            ("eq", (native_globals or {}).get("g_player_is_captive", -1), 0),
            ("ge", a, 0),
            ("le", a, 24),
            ("ge", b, 1),
            ("le", b, 5),
            ("try_begin",),
            ("eq", a, 0),
            ("rest_for_hours", 0, 0, 0),
            ("else_try",),
            ("rest_for_hours_interactive", a, b, 1),
            ("try_end",),
            ("assign", result, 0),
            ("else_try",),
            ("eq", kind, 19),
            ("troop_get_slot", tmp, TROOP, CONTEXT_SLOT),
            ("eq", tmp, 0),
            ("eq", scene, -1),
            ("eq", session, -1),
            ("eq", (native_globals or {}).get("g_player_is_captive", -1), 0),
            *world_encounter(world_result_url, native_globals or {}),
            ("try_end",),
            ("troop_set_slot", TROOP, RESULT_SLOT, result),
            ("troop_set_slot", TROOP, ACK_SLOT, cmd),
            ("try_end",),
            *(
                [
                    ("try_begin",),
                    ("troop_get_slot", LOCAL + 23, TROOP, POLL_NONCE_SLOT),
                    ("eq", LOCAL + 24, LOCAL + 23),
                    ("troop_get_slot", LOCAL + 22, TROOP, CONTEXT_SLOT),
                    ("try_begin",),
                    ("eq", LOCAL + 22, 1),
                    *telemetry_ops(poll_urls[0], True, native_globals),
                    ("else_try",),
                    ("eq", LOCAL + 22, 0),
                    *telemetry_ops(poll_urls[1], False, native_globals),
                    ("else_try",),
                    ("eq", LOCAL + 22, 2),
                    *telemetry_ops(poll_urls[2], False, native_globals, context=2),
                    *(
                        [
                            ("else_try",),
                            ("eq", LOCAL + 22, 3),
                            *telemetry_ops(
                                poll_urls[3], False, native_globals, context=3
                            ),
                        ]
                        if len(poll_urls) > 3
                        else []
                    ),
                    ("try_end",),
                    ("try_end",),
                ]
                if poll_urls
                else []
            ),
            ("try_begin",),
            ("troop_get_slot", LOCAL + 22, TROOP, CONTEXT_SLOT),
            ("eq", LOCAL + 22, 2),
            *[("troop_get_slot", REG + i, TROOP, MENU_REG_BASE + i) for i in range(32)],
            ("try_end",),
        ]
    )


def dialogue_lines(states, event_url):
    reply_state = len(states)
    condition = compile_ops(
        [
            ("troop_get_slot", LOCAL, TROOP, READY_SLOT),
            ("eq", LOCAL, 1),
            ("store_conversation_troop", LOCAL + 1),
            ("troop_get_slot", LOCAL + 2, TROOP, NPC_SLOT),
            ("eq", LOCAL + 1, LOCAL + 2),
            ("store_conversation_agent", LOCAL + 3),
            ("troop_get_slot", LOCAL + 4, TROOP, NPC_AGENT_SLOT),
            ("eq", LOCAL + 3, LOCAL + 4),
            ("str_store_string_reg", 60, 126),
        ]
    )

    def event(code):
        return compile_ops(
            [
                ("troop_get_slot", REG + 20, TROOP, JOB_SLOT),
                ("assign", REG + 21, code),
                ("str_store_string", 127, event_url),
                ("send_message_to_url", 127, 0),
                ("troop_set_slot", TROOP, READY_SLOT, 0),
                ("troop_set_slot", TROOP, DIALOG_ACTIVE_SLOT, 1 if code == 1 else 0),
            ]
        )

    return [
        f"dlga_start:mcp_npc_end 4095 {states.index('start')} "
        f"{condition} {{s60}} {reply_state} {event(1)} NO_VOICEOVER",
        f"dlga_mcp_npc_end:close_window 69631 {reply_state} 0 "
        f"Back_to_training. {states.index('close_window')} {event(2)} NO_VOICEOVER",
    ]


def build(native: Path, output: Path, endpoint: str, token: str):
    native, output = native.resolve(), output.resolve()
    if native.name != "Native" or not (native / "module.ini").is_file():
        raise ValueError("Source must be an installed Native module")
    if output.exists() or output == native or native in output.parents:
        raise ValueError("Output must be a new directory outside Native")
    url = urlparse(endpoint)
    if (
        url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or url.path
        or url.port not in (None, 80)
    ):
        raise ValueError("Vanilla Warband needs loopback HTTP on port 80")
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise ValueError("Token must be 64 lowercase hexadecimal characters")
    # Check patch seams before creating any output.
    scripts = (native / "scripts.txt").read_text()
    pattern = r"(?m)^(game_receive_url_response -1\s*\n)\s*0\s*\n"
    if len(re.findall(pattern, scripts)) != 1:
        raise ValueError("Expected exactly one empty Native URL callback")
    missions = (native / "mission_templates.txt").read_text().splitlines()
    strings = (native / "strings.txt").read_text(encoding="latin-1").splitlines()
    count = int(strings[1])
    if len(strings[2:]) != count:
        raise ValueError("Native string count mismatch")
    new_strings = []
    for kind in ("mission", "campaign"):
        value = (
            f"{endpoint}/poll?token={token}&v=2&context={kind}"
            "&ack={reg0}&gold={reg1}&troop={reg2}&hp={reg3}"
            "&x={reg4}&y={reg5}&z={reg6}&clock={reg7}"
            "&scene={reg8}&agent={reg9}&result={reg10}&session={reg11}"
            "&mission={reg12}&flags={reg13}&captive={reg14}&town={reg15}"
            "&encounter={reg16}&menu={reg17}&pulse={reg18}&dialogue={reg19}"
            "&menu-session={reg20}&build=12"
        )
        new_strings.append(f"str_mcp_{kind}_url {value}")
    new_strings.extend(
        [
            f"str_mcp_agent_url {endpoint}/agent?token={token}&v=2"
            "&job={reg20}&id={reg21}&troop={reg22}&team={reg23}&hp={reg24}"
            "&x={reg25}&y={reg26}&z={reg27}&player={reg28}&scene={reg30}"
            "&session={reg31}&attack={reg32}&defend={reg33}&direction={reg34}"
            "&weapon={reg35}&destination-x={reg36}&destination-y={reg37}"
            "&slot0={reg38}&slot1={reg39}&slot2={reg40}&slot3={reg41}",
            f"str_mcp_agents_end_url {endpoint}/agents-end?token={token}&v=2"
            "&job={reg20}&count={reg29}&scene={reg30}&session={reg31}",
            f"str_mcp_dialogue_url {endpoint}/dialogue?token={token}&v=2"
            "&job={reg20}&event={reg21}",
            f"str_mcp_campaign_row {endpoint}/campaign-row?token={token}&v=2"
            "&job={reg20}&dataset={reg21}&id={reg22}"
            "&a={reg23}&b={reg24}&c={reg25}&d={reg26}&e={reg27}&f={reg28}",
            f"str_mcp_campaign_end {endpoint}/campaign-end?token={token}&v=2"
            "&job={reg20}&dataset={reg21}&count={reg29}&total={reg30}",
        ]
    )
    new_strings.append(
        new_strings[1]
        .replace("str_mcp_campaign_url", "str_mcp_menu_url")
        .replace("context=campaign", "context=menu")
    )
    new_strings.append(
        f"str_mcp_order_url {endpoint}/battle-order?token={token}&v=2"
        "&job={reg20}&team={reg21}&formation={reg22}&movement={reg23}"
        "&fire={reg24}&riding={reg25}&weapon={reg26}&x={reg27}&y={reg28}"
        "&scene={reg30}&session={reg31}"
    )
    new_strings.append(
        f"str_mcp_world_url {endpoint}/world-result?token={token}&v=2"
        "&job={reg20}&kind={reg21}&id={reg22}&other={reg23}"
        "&a={reg24}&b={reg25}&c={reg26}&d={reg27}&e={reg28}&f={reg29}"
    )
    new_strings.extend(
        [
            f"str_mcp_merchant_row {endpoint}/merchant-row?token={token}&v=2"
            "&job={reg20}&slot={reg21}&item={reg22}&modifier={reg23}"
            "&amount={reg24}&max-amount={reg25}&base-value={reg26}"
            "&buy-factor={reg27}&sell-factor={reg28}&merchant={reg29}&town={reg30}",
            f"str_mcp_merchant_end {endpoint}/merchant-end?token={token}&v=2"
            "&job={reg20}&total={reg21}&count={reg22}&gold={reg23}"
            "&merchant={reg24}&town={reg25}",
        ]
    )
    new_strings.append(
        new_strings[1]
        .replace("str_mcp_campaign_url", "str_mcp_trade_url")
        .replace("context=campaign", "context=trade")
    )
    new_strings.append(
        f"str_mcp_trade_result {endpoint}/trade-result?token={token}&v=2"
        "&job={reg20}&mode={reg21}&item={reg22}&source-slot={reg23}"
        "&destination-slot={reg24}&price={reg25}&merchant={reg26}&town={reg27}"
        "&player-gold={reg28}&merchant-gold={reg29}&source-item={reg30}"
        "&destination-item={reg31}&source-amount={reg32}&destination-amount={reg33}"
        "&factor={reg34}&can-execute={reg35}"
    )
    strings[1] = str(count + len(new_strings))
    strings.extend(new_strings)
    variables_path = native / "variables.txt"
    native_globals = (
        {
            name: (2 << 56) + i
            for i, name in enumerate(variables_path.read_text().splitlines())
        }
        if variables_path.exists()
        else {}
    )
    if "mcp_http_active" in native_globals:
        raise ValueError("Native already uses reserved MCP lifecycle global")
    native_globals["mcp_http_active"] = (2 << 56) + len(native_globals)
    town_departure_id = recognize_town_permission(missions, native_globals)
    variable_names = (
        variables_path.read_text().splitlines() if variables_path.exists() else []
    )

    def mission_triggers(mission_id, flags):
        return [
            "2.000000 0.000000 0.000000 0 "
            + telemetry(STR + count, True, native_globals),
            "-19.000000 0.000000 0.000000 0 "
            + compile_ops(
                [
                    ("not_multiplayer",),
                    ("assign", native_globals["mcp_http_active"], 1),
                    ("troop_get_slot", LOCAL, TROOP, SESSION_SLOT),
                    ("val_add", LOCAL, 1),
                    ("troop_set_slot", TROOP, SESSION_SLOT, LOCAL),
                    ("troop_set_slot", TROOP, CONTEXT_SLOT, 1),
                    ("troop_set_slot", TROOP, READY_SLOT, 0),
                    ("troop_set_slot", TROOP, DIALOG_ACTIVE_SLOT, 0),
                    ("troop_set_slot", TROOP, MISSION_SLOT, mission_id),
                    ("troop_set_slot", TROOP, MISSION_FLAGS_SLOT, flags),
                ]
            ),
            "-29.000000 0.000000 0.000000 0 "
            + compile_ops(
                [
                    ("not_multiplayer",),
                    ("troop_set_slot", TROOP, CONTEXT_SLOT, 0),
                    ("troop_set_slot", TROOP, READY_SLOT, 0),
                ]
            ),
        ]

    missions, mission_names = instrument_missions(missions, mission_triggers)

    # Menu entry can consume registers populated by the preceding consequence.
    # Bootstrap must not replace those values with gold/coordinates. Native does
    # not use s123 or pos47; these are reserved scratch in this isolated module.
    def bootstrap_ops(url, context):
        return [
            *[("assign", LOCAL + 32 + i, REG + i) for i in range(21)],
            ("str_store_string_reg", 123, 127),
            ("copy_position", 47, 1),
            ("try_begin",),
            *telemetry_ops(url, False, native_globals, context=context),
            ("try_end",),
            *[("assign", REG + i, LOCAL + 32 + i) for i in range(21)],
            ("str_store_string_reg", 127, 123),
            ("copy_position", 1, 47),
        ]

    menu_bootstrap = bootstrap_ops(STR + count + 7, 2)
    menus, menu_names = instrument_menus(
        (native / "menus.txt").read_text(encoding="latin-1").splitlines(),
        lambda menu_id: compile_ops(
            [
                ("assign", native_globals["mcp_http_active"], 1),
                ("troop_set_slot", TROOP, MENU_SLOT, menu_id),
                ("troop_set_slot", TROOP, CONTEXT_SLOT, 2),
                ("troop_set_slot", TROOP, READY_SLOT, 0),
                ("troop_set_slot", TROOP, DIALOG_ACTIVE_SLOT, 0),
                ("troop_get_slot", LOCAL + 31, TROOP, MENU_SESSION_SLOT),
                ("val_add", LOCAL + 31, 1),
                ("troop_set_slot", TROOP, MENU_SESSION_SLOT, LOCAL + 31),
            ]
        ),
        on_return=compile_ops(
            [
                ("troop_set_slot", TROOP, CONTEXT_SLOT, 0),
                ("troop_set_slot", TROOP, MENU_SLOT, -1),
            ]
        ),
        make_suffix=lambda menu_id: compile_ops(
            [
                *[
                    ("troop_set_slot", TROOP, MENU_REG_BASE + i, REG + i)
                    for i in range(32)
                ],
                *menu_bootstrap,
            ]
        ),
        on_shutdown=compile_ops([("assign", native_globals["mcp_http_active"], 0)]),
        on_trade=compile_ops(bootstrap_ops(STR + count + 12, 3)),
    )
    script_lines = scripts.splitlines()
    extra_scripts, menu_actions = append_actions(
        menus, int(script_lines[1]), compile_ops, MENU_RESULT_SLOT
    )
    script_lines[1] = str(int(script_lines[1]) + len(extra_scripts) // 2)
    scripts = "\n".join([*script_lines, *extra_scripts]) + "\n"
    simple = (native / "simple_triggers.txt").read_text().splitlines()
    simple[1] = str(int(simple[1]) + 1)
    simple.append("0.100000 " + telemetry(STR + count + 1, False, native_globals))
    states = (native / "dialog_states.txt").read_text().splitlines()
    if "mcp_npc_end" in states:
        raise ValueError("Native already contains MCP dialogue state")
    conversations = (
        (native / "conversation.txt").read_text(encoding="latin-1").splitlines()
    )
    added_dialogue = dialogue_lines(states, STR + count + 4)
    conversations[1] = str(int(conversations[1]) + 2)
    conversations.insert(3, added_dialogue[0])
    conversations.append(added_dialogue[1])

    def definitions(filename, prefix):
        path = native / filename
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="latin-1").splitlines():
            fields = line.split()
            if filename == "factions.txt" and len(fields) > 1 and fields[0].isdigit():
                # Native writes previous faction's note count without a newline:
                # all but the first definition begin `0 fac_name ...`.
                fields = fields[1:]
            if fields and fields[0].startswith(prefix):
                rows.append(fields)
        return rows

    quests = definitions("quests.txt", "qst_")
    troop_names = [
        row[1].replace("_", " ") for row in definitions("troops.txt", "trp_")
    ]
    skills = definitions("skills.txt", "skl_")
    items = definitions("item_kinds1.txt", "itm_")
    factions = definitions("factions.txt", "fac_")
    faction_ids = [row[0] for row in factions]
    kingdom_ids = [
        i
        for i, name in enumerate(faction_ids)
        if name == "fac_player_supporters_faction"
        or re.fullmatch(r"fac_kingdom_[1-6]", name)
    ]
    native_scripts = {
        name: i
        for i, name in enumerate(
            re.findall(
                r"^([A-Za-z_][A-Za-z_0-9]*) -1$",
                (native / "scripts.txt").read_text(),
                re.M,
            )
        )
    }
    parties = {}
    for line in (
        (native / "parties.txt").read_text(encoding="latin-1").splitlines()
        if (native / "parties.txt").exists()
        else []
    ):
        fields = line.split()
        if len(fields) > 4 and fields[3].startswith("p_"):
            parties[fields[1]] = fields[4].replace("_", " ")
    shutil.copytree(native, output)
    (output / "variables.txt").write_text(
        "\n".join([*variable_names, "mcp_http_active"]) + "\n"
    )
    (output / "strings.txt").write_text("\n".join(strings) + "\n", encoding="latin-1")
    (output / "scripts.txt").write_text(
        re.sub(
            pattern,
            lambda m: (
                m[1]
                + " "
                + callback(
                    STR + count + 2,
                    STR + count + 3,
                    STR + count + 5,
                    STR + count + 6,
                    len(quests),
                    len(skills),
                    (STR + count, STR + count + 1, STR + count + 7, STR + count + 12),
                    native_globals,
                    menu_actions,
                    STR + count + 8,
                    len(items),
                    STR + count + 9,
                    len(factions),
                    kingdom_ids,
                    native_scripts,
                    STR + count + 10,
                    STR + count + 11,
                    len(troop_names),
                    menu_names.index("town_trade")
                    if "town_trade" in menu_names
                    else -1,
                    STR + count + 13,
                    town_departure_id,
                )
                + "\n"
            ),
            scripts,
        )
    )
    (output / "mission_templates.txt").write_text("\n".join(missions) + "\n")
    (output / "simple_triggers.txt").write_text("\n".join(simple) + "\n")
    (output / "menus.txt").write_text("\n".join(menus) + "\n", encoding="latin-1")
    (output / "dialog_states.txt").write_text(
        "\n".join([*states, "mcp_npc_end"]) + "\n"
    )
    (output / "conversation.txt").write_text(
        "\n".join(conversations) + "\n", encoding="latin-1"
    )
    (output / "mcp-catalog.json").write_text(
        json.dumps(
            {
                "name_source": "module troop definitions, not live renamed agent names",
                "troops": {str(i): name for i, name in enumerate(troop_names)},
                "items": {
                    str(i): row[1].replace("_", " ") for i, row in enumerate(items)
                },
                "skills": {
                    str(i): row[1].replace("_", " ") for i, row in enumerate(skills)
                },
                "quests": {
                    str(i): {
                        "symbol": row[0],
                        "title_template": row[1].replace("_", " "),
                    }
                    for i, row in enumerate(quests)
                },
                "factions": {
                    str(i): row[1].replace("_", " ") for i, row in enumerate(factions)
                },
                "parties": parties,
                "kingdom_ids": kingdom_ids,
                "missions": {
                    str(i): line.split()[0][4:]
                    for i, line in enumerate(
                        line
                        for line in (native / "mission_templates.txt")
                        .read_text()
                        .splitlines()
                        if line.startswith("mst_")
                    )
                },
                "instrumented_missions": mission_names,
                "menus": {str(i): name for i, name in enumerate(menu_names)},
                "scene_departure_missions": []
                if town_departure_id is None
                else [town_departure_id],
                "menu_actions": menu_actions,
            },
            indent=2,
        )
    )
    ini = (output / "module.ini").read_text()
    ini = re.sub(r"(?m)^module_name\s*=.*$", "module_name = WarbandMCP", ini)
    (output / "module.ini").write_text(ini)
    (output / "mcp-build.json").write_text(
        json.dumps(
            {
                "protocol": 2,
                "integration_revision": 12,
                "scene_departure_missions": []
                if town_departure_id is None
                else [town_departure_id],
                "source": str(native),
                "transport": "engine HTTP opcode 380",
                "instrumented_missions": mission_names,
                "modified": [
                    "strings.txt",
                    "scripts.txt",
                    "mission_templates.txt",
                    "simple_triggers.txt",
                    "module.ini",
                    "conversation.txt",
                    "dialog_states.txt",
                    "menus.txt",
                ],
                "commands": [
                    "message",
                    "scan_agents",
                    "relocate_player",
                    "npc_say",
                    "scan_campaign",
                    "select_menu",
                    "battle_order",
                    "formation_position",
                    "agent_combat",
                    "agent_move",
                    "agent_release",
                    "agent_wield",
                    "world_query",
                    "diplomacy",
                    "party_order",
                    "campaign_wait",
                    "scan_merchant",
                    "goods_trade",
                    "world_encounter",
                    "leave_scene",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1")
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    build(args.native, args.output, args.endpoint, args.token_file.read_text().strip())
