"""Allowlisted game operations; no desktop or arbitrary bytecode commands."""

import math

OPERATIONS = {
    "message": 1,
    "scan_agents": 2,
    "relocate_player": 3,
    "npc_say": 4,
    "scan_campaign": 5,
    "select_menu": 6,
    "battle_order": 7,
    "formation_position": 8,
    "agent_combat": 9,
    "agent_move": 10,
    "agent_release": 11,
    "agent_wield": 12,
}
DATASETS = {
    "party": 1,
    "prisoners": 2,
    "inventory": 3,
    "character": 4,
    "world_parties": 5,
    "quests": 6,
}
ORDERS = {
    "hold": 0,
    "follow": 1,
    "charge": 2,
    "mount": 3,
    "dismount": 4,
    "advance": 5,
    "fall_back": 6,
    "stand_closer": 7,
    "spread_out": 8,
    "blunt_weapons": 9,
    "any_weapons": 10,
    "stand_ground": 11,
    "hold_fire": 12,
    "fire_at_will": 13,
    "retreat": 14,
}
DIRECTIONS = {"down": 0, "right": 1, "left": 2, "up": 3}
SCENE_CONTROLS = {
    "formation_position",
    "agent_combat",
    "agent_move",
    "agent_release",
    "agent_wield",
}


def validate_operation(kind, payload, state):
    if kind not in OPERATIONS or not isinstance(payload, dict):
        raise ValueError("Unknown game operation or malformed arguments")
    if not state.get("connected"):
        raise ValueError("Game telemetry is stale or disconnected")
    context = (
        "menu"
        if kind == "select_menu"
        else "campaign"
        if kind == "scan_campaign"
        else "mission"
    )
    if kind != "message" and (
        state.get("protocol") != 2
        or (
            state.get("context") != context
            and not (kind == "scan_campaign" and state.get("context") == "menu")
        )
    ):
        raise ValueError(f"This operation requires protocol-2 {context} telemetry")
    expected = {
        "message": {"text"},
        "scan_agents": set(),
        "relocate_player": {"x", "y"},
        "npc_say": {"agent_id", "text"},
        "scan_campaign": {"dataset", "offset", "limit"},
        "select_menu": {"action_id"},
        "battle_order": {"formation", "order"},
        "formation_position": {"formation", "x", "y"},
        "agent_combat": {
            "agent_id",
            "action",
            "direction",
            "duration_ms",
            "world_control",
        },
        "agent_move": {"agent_id", "x", "y", "world_control"},
        "agent_release": {"agent_id", "world_control"},
        "agent_wield": {"agent_id", "item_id", "world_control"},
    }[kind]
    if set(payload) != expected:
        raise ValueError("Unexpected or missing operation arguments")
    if kind in SCENE_CONTROLS:
        if state.get("integration_revision", 0) < 7:
            raise ValueError("Scene control needs integration revision 7")
        if (
            state.get("dialogue_active")
            or not (state.get("player_hit_points") or 0) > 0
        ):
            raise ValueError("Scene control requires a living player outside dialogue")
        if "agent_id" in payload:
            if (
                type(payload["agent_id"]) is not int
                or not 0 <= payload["agent_id"] < 10000
            ):
                raise ValueError("Expected a valid scene agent ID")
            if type(payload["world_control"]) is not bool:
                raise ValueError("world_control must be an explicit boolean")
        if kind in ("agent_move", "agent_release") and payload["agent_id"] == state.get(
            "player_agent_id"
        ):
            raise ValueError(
                "Scripted walking controls NPC AI, not player movement input"
            )
        if "x" in payload:
            for key in ("x", "y"):
                value = payload[key]
                if (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or abs(value) > 10000
                ):
                    raise ValueError(
                        "Scene coordinates must be finite within +/-10000m"
                    )
        if kind == "agent_combat":
            if (
                not isinstance(payload["action"], str)
                or payload["action"]
                not in {"attack", "attack_hold", "clear_attack", "block", "clear_block"}
                or not isinstance(payload["direction"], str)
                or payload["direction"] not in DIRECTIONS
            ):
                raise ValueError("Unknown combat action/direction")
            if (
                type(payload["duration_ms"]) is not int
                or not 0 <= payload["duration_ms"] <= 10000
            ):
                raise ValueError("Block duration must be 0–10000ms")
        if kind == "agent_wield" and (
            type(payload["item_id"]) is not int or not 0 <= payload["item_id"] < 10000
        ):
            raise ValueError("Expected a valid equipped item ID")
    if kind in ("battle_order", "formation_position"):
        if state.get("integration_revision", 0) < 6:
            raise ValueError("Battle orders need integration revision 6")
        if not (state.get("mission_flags") or 0) & 2:
            raise ValueError("Battle orders require a battle-mode mission")
        if (
            state.get("dialogue_active")
            or not (state.get("player_hit_points") or 0) > 0
        ):
            raise ValueError("Battle orders require a living player outside dialogue")
        if type(payload["formation"]) is not int or not 0 <= payload["formation"] <= 9:
            raise ValueError("Formation must be 0–8, or 9 for everyone")
        if kind == "battle_order" and (
            not isinstance(payload["order"], str) or payload["order"] not in ORDERS
        ):
            raise ValueError("Unknown Native battle order")
    if kind == "select_menu":
        if state.get("integration_revision", 0) < 5:
            raise ValueError("Menu control needs integration revision 5")
        if type(state.get("menu_session")) is not int or state["menu_session"] <= 0:
            raise ValueError("Menu control needs a valid menu-entry session")
        if (
            type(payload["action_id"]) is not int
            or not 0 <= payload["action_id"] < 10000
        ):
            raise ValueError("Expected a valid catalog menu action ID")
        if state.get("dialogue_active"):
            raise ValueError("Cannot select a menu during dialogue")
    if kind == "scan_campaign":
        if (
            not isinstance(payload["dataset"], str)
            or payload["dataset"] not in DATASETS
        ):
            raise ValueError("Unknown campaign dataset")
        if type(payload["offset"]) is not int or not 0 <= payload["offset"] <= 100000:
            raise ValueError("Offset must be an integer from 0 to 100000")
        if type(payload["limit"]) is not int or not 1 <= payload["limit"] <= 16:
            raise ValueError("Limit must be an integer from 1 to 16")
    if "text" in payload:
        text = payload["text"]
        if (
            not isinstance(text, str)
            or not 1 <= len(text) <= 200
            or any(c in text for c in "|\r\n\x00{}")
            or not text.isprintable()
        ):
            raise ValueError(
                "Text needs 1–200 printable characters without | or braces"
            )
    if kind == "npc_say":
        if state.get("dialogue_active"):
            raise ValueError("A conversation is already active")
        if (
            state.get("mission_flags", 0) is not None
            and state.get("mission_flags", 0) & 2
        ):
            raise ValueError("NPC dialogue is disabled during battle missions")
        agent_id = payload["agent_id"]
        if type(agent_id) is not int or not 0 <= agent_id < 10000:
            raise ValueError("Expected a valid nonnegative scene agent ID")
        if agent_id == state.get("player_agent_id"):
            raise ValueError("NPC speech cannot target the player")
    if kind == "relocate_player":
        if state.get("dialogue_active"):
            raise ValueError("Cannot relocate the player during dialogue")
        for key in ("x", "y"):
            value = payload[key]
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError("Coordinates must be finite numbers")
        position = state["position"]
        if math.hypot(payload["x"] - position["x"], payload["y"] - position["y"]) > 10:
            raise ValueError("Test relocation is limited to 10 metres from the player")


def wire_arguments(kind, payload):
    if kind == "formation_position":
        return [
            payload["formation"],
            round(payload["x"] * 100),
            round(payload["y"] * 100),
            0,
        ]
    if kind in ("agent_combat", "agent_move", "agent_release", "agent_wield"):
        actor = payload["agent_id"] + (10000 if payload["world_control"] else 0)
        if kind == "agent_wield":
            return [actor, payload["item_id"], 0, 0]
        if kind == "agent_move":
            return [actor, round(payload["x"] * 100), round(payload["y"] * 100), 0]
        if kind == "agent_combat":
            code = {
                "attack": 0,
                "attack_hold": 4,
                "clear_attack": 8,
                "block": 12,
                "clear_block": 16,
            }[payload["action"]]
            if payload["action"] not in ("clear_attack", "clear_block"):
                code += DIRECTIONS[payload["direction"]]
            return [actor, code, payload["duration_ms"], 0]
        return [actor, 0, 0, 0]
    if kind == "battle_order":
        return [payload["formation"], ORDERS[payload["order"]], 0, 0]
    if kind == "select_menu":
        return [payload["action_id"], 0, 0, 0]
    if kind == "scan_campaign":
        return [DATASETS[payload["dataset"]], payload["offset"], payload["limit"], 0]
    if kind == "relocate_player":
        return [round(payload["x"] * 100), round(payload["y"] * 100), 0, 0]
    if kind == "npc_say":
        return [payload["agent_id"], 0, 0, 0]
    return [0, 0, 0, 0]
