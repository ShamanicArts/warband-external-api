"""Allowlisted game operations; no desktop or arbitrary bytecode commands."""

import math

OPERATIONS = {
    "message": 1,
    "scan_agents": 2,
    "relocate_player": 3,
    "npc_say": 4,
    "scan_campaign": 5,
}
DATASETS = {
    "party": 1,
    "prisoners": 2,
    "inventory": 3,
    "character": 4,
    "world_parties": 5,
    "quests": 6,
}


def validate_operation(kind, payload, state):
    if kind not in OPERATIONS or not isinstance(payload, dict):
        raise ValueError("Unknown game operation or malformed arguments")
    if not state.get("connected"):
        raise ValueError("Game telemetry is stale or disconnected")
    context = "campaign" if kind == "scan_campaign" else "mission"
    if kind != "message" and (
        state.get("protocol") != 2 or state.get("context") != context
    ):
        raise ValueError(f"This operation requires protocol-2 {context} telemetry")
    expected = {
        "message": {"text"},
        "scan_agents": set(),
        "relocate_player": {"x", "y"},
        "npc_say": {"agent_id", "text"},
        "scan_campaign": {"dataset", "offset", "limit"},
    }[kind]
    if set(payload) != expected:
        raise ValueError("Unexpected or missing operation arguments")
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
        agent_id = payload["agent_id"]
        if type(agent_id) is not int or not 0 <= agent_id < 10000:
            raise ValueError("Expected a valid nonnegative scene agent ID")
        if agent_id == state.get("player_agent_id"):
            raise ValueError("NPC speech cannot target the player")
    if kind == "relocate_player":
        for key in ("x", "y"):
            value = payload[key]
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError("Coordinates must be finite numbers")
        position = state["position"]
        if math.hypot(payload["x"] - position["x"], payload["y"] - position["y"]) > 10:
            raise ValueError("Test relocation is limited to 10 metres from the player")


def wire_arguments(kind, payload):
    if kind == "scan_campaign":
        return [DATASETS[payload["dataset"]], payload["offset"], payload["limit"], 0]
    if kind == "relocate_player":
        return [round(payload["x"] * 100), round(payload["y"] * 100), 0, 0]
    if kind == "npc_say":
        return [payload["agent_id"], 0, 0, 0]
    return [0, 0, 0, 0]
