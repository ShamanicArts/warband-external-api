"""Recognize Native's reviewed town departure permission; no generic mission abort.

Village Tab has fugitive-quest consequences and is deliberately NOT supported.
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
