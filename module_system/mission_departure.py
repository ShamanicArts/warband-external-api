"""Recognize Native's reviewed town departure permission; no generic mission abort.

Village Tab retains its original fugitive-quest success/failure consequences.
"""

from module_system.menu_hooks import operation_end
from module_system.scene_ops import LOCAL, TROOP, living_player


def recognize_town_permission(lines, globals_):
    headers = [i for i, line in enumerate(lines) if line.startswith("mst_")]
    for mission_id, start in enumerate(headers):
        if lines[start].split()[0] != "mst_town_default":
            continue
        if "g_main_attacker_agent" not in globals_:
            raise ValueError("Native town departure attacker global is missing")
        boundary = (
            headers[mission_id + 1] if mission_id + 1 < len(headers) else len(lines)
        )
        tabs = []
        for line in lines[start + 3 : boundary]:
            fields = line.split()
            if not fields or fields[0] != "-21.000000":
                continue
            end = operation_end(fields, 3)
            tabs.append(fields)
            expected = [
                4,
                4,
                0,
                31,
                2,
                globals_["g_main_attacker_agent"],
                0,
                2075,
                1,
                1,
                3,
                0,
            ]
            if list(map(int, fields[3:end])) != expected or fields[end:] != ["0"]:
                raise ValueError(
                    "Unreviewed Native town departure trigger; refuse adaptation"
                )
        if len(tabs) != 1:
            raise ValueError(
                "Native town departure must have exactly one reviewed Tab handler"
            )
        return mission_id
    return None


def leave_town_ops(mission_id, globals_, mission_slot, flags_slot, dialogue_slot):
    if mission_id is None:
        return [("eq", 0, 1)]
    return [
        ("troop_get_slot", LOCAL + 29, TROOP, mission_slot),
        ("eq", LOCAL + 29, mission_id),
        ("troop_get_slot", LOCAL + 29, TROOP, flags_slot),
        ("val_and", LOCAL + 29, 2),
        ("eq", LOCAL + 29, 0),
        *living_player(dialogue_slot),
        ("eq", globals_["g_main_attacker_agent"], 0),
        # Caller explicitly requests departure, providing the player's confirmation.
        # Same recognized Native permission, original engine mission teardown.
        ("assign", LOCAL + 10, 0),
        ("finish_mission", 0),
    ]


def recognize_street_permission(lines, globals_, cannot_leave_string):
    headers = [i for i, line in enumerate(lines) if line.startswith("mst_")]
    for mission_id, start in enumerate(headers):
        if lines[start].split()[0] != "mst_town_center":
            continue
        required = ("talk_context", "g_mt_mode", "g_defending_against_siege")
        if cannot_leave_string is None or any(
            name not in globals_ for name in required
        ):
            raise ValueError("Native streets departure definitions missing")
        boundary = (
            headers[mission_id + 1] if mission_id + 1 < len(headers) else len(lines)
        )
        tabs = [
            line.split()
            for line in lines[start + 3 : boundary]
            if line.startswith("-21.000000 ")
        ]
        expected = [
            12,
            4,
            0,
            31 | 0x40000000,
            2,
            globals_["talk_context"],
            19,
            31,
            2,
            globals_["talk_context"],
            18,
            1106,
            1,
            cannot_leave_string,
            5,
            0,
            31 | 0x40000000,
            2,
            globals_["g_mt_mode"],
            0,
            31,
            2,
            globals_["g_mt_mode"],
            1,
            1935,
            0,
            2075,
            1,
            1,
            5,
            0,
            1106,
            1,
            cannot_leave_string,
            3,
            0,
        ]
        if len(tabs) != 1:
            raise ValueError("Native streets require one reviewed Tab handler")
        fields = tabs[0]
        end = operation_end(fields, 3)
        if (
            fields[1:3] != ["0.000000", "0.000000"]
            or list(map(int, fields[3:end])) != expected
            or fields[end:] != ["0"]
        ):
            raise ValueError("Unreviewed Native streets departure trigger")
        return mission_id
    return None


def leave_street_ops(mission_id, globals_, mission_slot, flags_slot, dialogue_slot):
    if mission_id is None:
        return [("eq", 0, 1)]
    return [
        ("troop_get_slot", LOCAL + 29, TROOP, mission_slot),
        ("eq", LOCAL + 29, mission_id),
        ("troop_get_slot", LOCAL + 29, TROOP, flags_slot),
        ("val_and", LOCAL + 29, 2),
        ("eq", LOCAL + 29, 0),
        *living_player(dialogue_slot),
        ("neq", globals_["talk_context"], 19),
        ("neq", globals_["talk_context"], 18),
        ("eq", globals_["g_defending_against_siege"], 0),
        ("or_eq", globals_["g_mt_mode"], 0),
        ("eq", globals_["g_mt_mode"], 1),
        ("mission_enable_talk",),
        ("assign", LOCAL + 10, 0),
        ("finish_mission", 0),
    ]


def village_permission(lines, quest, fugitive, scripts):
    """Recognize complete Native quest-effect handler and return reviewed recipe."""
    headers = [i for i, line in enumerate(lines) if line.startswith("mst_")]
    for mission_id, start in enumerate(headers):
        if lines[start].split()[0] != "mst_village_center":
            continue
        required = ("cf_troop_agent_is_alive", "fail_quest", "succeed_quest")
        if (
            quest is None
            or fugitive is None
            or any(name not in scripts for name in required)
        ):
            raise ValueError("Native village departure quest definitions missing")
        script = 13 << 56
        alive, fail, succeed = [script + scripts[name] for name in required]
        expected = [
            13,
            4,
            0,
            200,
            1,
            quest,
            202 | 0x80000000,
            1,
            quest,
            203 | 0x80000000,
            1,
            quest,
            546,
            3,
            quest,
            11,
            1,
            4,
            0,
            1,
            2,
            alive,
            fugitive,
            1,
            2,
            fail,
            quest,
            5,
            0,
            1,
            2,
            succeed,
            quest,
            3,
            0,
            3,
            0,
            2075,
            1,
            1,
        ]
        boundary = (
            headers[mission_id + 1] if mission_id + 1 < len(headers) else len(lines)
        )
        tabs = [
            line.split()
            for line in lines[start + 3 : boundary]
            if line.startswith("-21.000000 ")
        ]
        if len(tabs) != 1:
            raise ValueError("Native village requires one reviewed Tab handler")
        fields = tabs[0]
        end = operation_end(fields, 3)
        if (
            fields[1:3] != ["0.000000", "0.000000"]
            or list(map(int, fields[3:end])) != expected
            or fields[end:] != ["0"]
        ):
            raise ValueError("Unreviewed Native village departure quest handler")
        return mission_id, [
            ("try_begin",),
            ("check_quest_active", quest),
            ("not_check_quest_succeeded", quest),
            ("not_check_quest_failed", quest),
            ("quest_slot_eq", quest, 11, 1),
            ("try_begin",),
            ("call_script", alive, fugitive),
            ("call_script", fail, quest),
            ("else_try",),
            ("call_script", succeed, quest),
            ("try_end",),
            ("try_end",),
        ]
    return None, []


def leave_village_ops(
    mission_id, quest_effects, mission_slot, flags_slot, dialogue_slot
):
    if mission_id is None:
        return [("eq", 0, 1)]
    return [
        ("troop_get_slot", LOCAL + 29, TROOP, mission_slot),
        ("eq", LOCAL + 29, mission_id),
        ("troop_get_slot", LOCAL + 29, TROOP, flags_slot),
        ("val_and", LOCAL + 29, 2),
        ("eq", LOCAL + 29, 0),
        *living_player(dialogue_slot),
        *quest_effects,
        ("assign", LOCAL + 10, 0),
        ("finish_mission", 0),
    ]
