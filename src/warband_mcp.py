"""Platform-independent MCP client for the Warband mod's HTTP bridge. No CUA."""

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

import anyio
from mcp.server.fastmcp import FastMCP

from bridge.game_bridge import load_token

mcp = FastMCP(
    "Warband",
    instructions=(
        "These tools connect to actual Warband game scripts, not desktop automation. "
        "Check connected and telemetry age before using state. Commands are queued, "
        "not executed, until the game polls; check status for game acknowledgement. "
        "Scene scans, guarded relocation and NPC dialogue are game-script operations. "
        "Relocation is a debug teleport, not walking or campaign navigation. "
        "Generate NPC text yourself, grounded in the exported scene and character; "
        "npc_say renders it in the game's actual dialogue UI. Observe the dialogue "
        "event rather than pretending the player has replied. "
        "CUA is used separately by the developer for launch and visual validation."
    ),
)


def request(path, data=None):
    endpoint = os.environ.get("WARBAND_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/")
    token_path = os.environ.get("WARBAND_TOKEN_FILE")
    if not token_path:
        raise RuntimeError("Set WARBAND_TOKEN_FILE to the bridge's token file")
    req = Request(
        endpoint + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Authorization": "Bearer " + load_token(Path(token_path)),
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=5) as response:
        return json.load(response)


@mcp.tool()
async def warband_get_state() -> dict:
    """Read engine-sourced player gold, troop ID, position, HP and heartbeat.

    Mission telemetry runs in the free-play tutorial; campaign telemetry runs
    while campaign time advances. Pausing can make telemetry stale.
    """
    return await anyio.to_thread.run_sync(lambda: request("/api/state"))


@mcp.tool()
async def warband_display_message(text: str) -> dict:
    """Queue an actual game-script display_message, not CUA typing.

    Return ID and queued status. Check warband_command_status for acknowledgement;
    that means the game executed the operation, not that a human saw the message.
    """
    return await anyio.to_thread.run_sync(
        lambda: request("/api/commands", {"text": text})
    )


@mcp.tool()
async def warband_command_status(command_id: int) -> dict:
    """Get queued/dispatched/acknowledged/expired status of a command."""
    if command_id <= 0:
        raise ValueError("command_id must be positive")
    return await anyio.to_thread.run_sync(
        lambda: request(f"/api/commands/{command_id}")
    )


async def operation(kind: str, arguments: dict) -> dict:
    return await anyio.to_thread.run_sync(
        lambda: request("/api/commands", {"operation": kind, "arguments": arguments})
    )


@mcp.tool()
async def warband_refresh_scene_agents() -> dict:
    """Ask actual game scripts to enumerate up to 64 living human scene agents.

    Returns a command ID; retrieve the census with warband_scene_agents. Names
    come from module definitions; positions, HP, teams and IDs come from the game.
    """
    return await operation("scan_agents", {})


@mcp.tool()
async def warband_scene_agents(command_id: int) -> dict:
    """Read a census job. Only complete=true means all expected agents arrived."""
    if command_id <= 0:
        raise ValueError("command_id must be positive")
    return await anyio.to_thread.run_sync(lambda: request(f"/api/agents/{command_id}"))


@mcp.tool()
async def warband_relocate_player(x: float, y: float) -> dict:
    """Debug teleport within 10m, ground-aligned, in the instrumented test mission.

    This is not keyboard input, walking, or campaign travel. Game scripts check
    the current mission session, scene, living player and distance at execution.
    Verify the acknowledgement and subsequent engine position before proceeding.
    """
    return await operation("relocate_player", {"x": x, "y": y})


@mcp.tool()
async def warband_npc_say(agent_id: int, text: str) -> dict:
    """Have a freshly scanned NPC speak supplied text in Warband's dialogue UI.

    Generate text in the calling agent; this server has no hard-coded LLM provider.
    Refresh agents first. This opens a real one-turn conversation with a visible
    'Back to training' choice; it does not yet accept arbitrary player free text.
    Read warband_dialogue_event to confirm opening/closing. Mission telemetry may
    pause during dialogue, delaying the normal command acknowledgement until close.
    """
    return await operation("npc_say", {"agent_id": agent_id, "text": text})


@mcp.tool()
async def warband_dialogue_event(command_id: int) -> dict:
    """Read game-reported opened/closed events for an NPC speech command."""
    if command_id <= 0:
        raise ValueError("command_id must be positive")
    return await anyio.to_thread.run_sync(
        lambda: request(f"/api/dialogue/{command_id}")
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
