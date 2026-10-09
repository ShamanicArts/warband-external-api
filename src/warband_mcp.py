"""Platform-independent MCP client for the Warband mod's HTTP bridge. No CUA."""

import json
import os
from pathlib import Path
from typing import Literal
from urllib.request import Request, urlopen

import anyio
from mcp.server.fastmcp import FastMCP

from bridge.game_bridge import load_token

mcp = FastMCP(
    "Warband",
    log_level="WARNING",
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
async def warband_capabilities() -> dict:
    """Discover implemented vs unsupported features and current context restrictions."""
    return await anyio.to_thread.run_sync(lambda: request("/api/capabilities"))


@mcp.tool()
async def warband_menu_options() -> dict:
    """List reviewed Native menu action candidates for the current menu.

    Labels can be unexpanded templates. These are not claims of availability:
    Native conditions are checked in game on selection. No cheats or arbitrary
    script execution. Mutating commands use the exact current menu-entry session.
    """
    return await anyio.to_thread.run_sync(lambda: request("/api/menu-options"))


@mcp.tool()
async def warband_select_menu(action_id: int) -> dict:
    """Execute an allowlisted Native menu choice using its real conditions/action.

    Obtain action_id from warband_menu_options, then check command status AND
    resulting state. Recruitment costs gold and obeys Native capacity/supply.
    Acknowledgement means the Native consequence was dispatched, not that every
    inner branch succeeded. It may enter a scene or change menus. No rollback.
    """
    return await operation("select_menu", {"action_id": action_id})


@mcp.tool()
async def warband_battle_order(
    formation: int,
    order: Literal[
        "hold",
        "follow",
        "charge",
        "mount",
        "dismount",
        "advance",
        "fall_back",
        "stand_closer",
        "spread_out",
        "blunt_weapons",
        "any_weapons",
        "stand_ground",
        "hold_fire",
        "fire_at_will",
        "retreat",
    ],
) -> dict:
    """Issue a Native order to the living player's own team in a battle mission.

    Formation 0–8 selects one division; 9 selects everyone. No enemy-team control.
    Retreat can lose a battle. Check acknowledgement and warband_battle_order_result;
    read-back proves order state, not movement, obedience, or combat success.
    """
    return await operation("battle_order", {"formation": formation, "order": order})


@mcp.tool()
async def warband_battle_order_result(command_id: int) -> dict:
    """Read durable per-formation Native engine orders for a battle command."""
    return await anyio.to_thread.run_sync(
        lambda: request(f"/api/battle-orders/{command_id}")
    )


@mcp.tool()
async def warband_place_formation(formation: int, x: float, y: float) -> dict:
    """Move the player's division's hold point to an in-scene position (metres).

    Native pathfinding/obstacles still apply. No teleport: team_set_order_position
    plus hold order. Formation 0–8, or 9 for everyone. Read back with
    warband_battle_order_result and verify actual troop positions separately.
    """
    return await operation(
        "formation_position", {"formation": formation, "x": x, "y": y}
    )


@mcp.tool()
async def warband_agent_wield(
    agent_id: int, item_id: int, world_control: bool = False
) -> dict:
    """Select an actually equipped weapon for a living player/NPC; no item spawning.

    Obtain item IDs from a fresh scene agent's weapon_slots. Native checks that
    the actor really has it equipped. Read back combat.weapon afterwards.
    Default restricts to the player's team; world_control explicitly permits others.
    """
    return await operation(
        "agent_wield",
        {
            "agent_id": agent_id,
            "item_id": item_id,
            "world_control": world_control,
        },
    )


@mcp.tool()
async def warband_agent_combat(
    agent_id: int,
    action: Literal["attack", "attack_hold", "clear_attack", "block", "clear_block"],
    direction: Literal["down", "right", "left", "up"] = "up",
    duration_ms: int = 1000,
    world_control: bool = False,
) -> dict:
    """Drive real player/NPC attack/block actions, not keyboard simulation.

    Uses Native agent_set_attack_action/agent_set_defend_action. Actor must be a
    living human in this scene. Default restricts to the player's team;
    world_control=True is an explicit world intervention permitting other teams.
    attack releases immediately, attack_hold readies, block lasts 0–10000ms.
    Check acknowledgement AND fresh scene combat read-back; equipment, timing,
    animation and engine restrictions can prevent the requested action.
    Player attack_hold was ineffective in current live tests, even with a melee
    weapon; do not treat this as verified player input. NPC combat takes scripted
    control at the actor's current location; release_npc afterwards restores AI.
    """
    return await operation(
        "agent_combat",
        {
            "agent_id": agent_id,
            "action": action,
            "direction": direction,
            "duration_ms": duration_ms,
            "world_control": world_control,
        },
    )


@mcp.tool()
async def warband_move_npc(
    agent_id: int,
    x: float,
    y: float,
    world_control: bool = False,
) -> dict:
    """Give a living NPC a scripted walking destination inside scene bounds.

    Not teleport and not player movement input. Native AI/pathfinding moves the
    NPC; obstacles/combat can interfere. Default permits the player's team only;
    world_control=True explicitly intervenes in other teams. Fresh scene census
    reads destination and actual position. Release afterwards to restore AI.
    """
    return await operation(
        "agent_move",
        {
            "agent_id": agent_id,
            "x": x,
            "y": y,
            "world_control": world_control,
        },
    )


@mcp.tool()
async def warband_release_npc(agent_id: int, world_control: bool = False) -> dict:
    """Clear an NPC's scripted movement and request normal Native AI rethink."""
    return await operation(
        "agent_release",
        {
            "agent_id": agent_id,
            "world_control": world_control,
        },
    )


@mcp.tool()
async def warband_inspect_world_entity(
    entity: Literal["faction", "party"],
    entity_id: int,
    other_id: int = 0,
) -> dict:
    """Queue actual campaign faction/party getters; read world_command_result.

    Faction returns relation to other_id, leaders, state and color. Party returns
    AI behavior/object/initiative, faction and actual map position. Observations
    are omniscient world data, not proof of legitimate player knowledge.
    """
    return await operation(
        "world_query",
        {
            "entity": entity,
            "entity_id": entity_id,
            "other_id": other_id,
        },
    )


@mcp.tool()
async def warband_diplomacy(
    faction_a: int,
    faction_b: int,
    action: Literal["war", "peace"],
    world_control: bool = False,
) -> dict:
    """Call reviewed Native kingdom war/peace scripts, including their consequences.

    Normal authority requires faction_a to be the player's active kingdom with
    the player as leader. world_control=True is an explicit world intervention
    permitting other active kingdoms. This can change relations, prisoners,
    sieges, quests and logs: reversing relation is NOT rollback. Live acceptance
    pending; inspect result and state, never mistake dispatch for success.
    """
    return await operation(
        "diplomacy",
        {
            "faction_a": faction_a,
            "faction_b": faction_b,
            "action": action,
            "world_control": world_control,
        },
    )


@mcp.tool()
async def warband_campaign_party_order(
    party_id: int,
    order: Literal["hold", "travel", "patrol", "attack", "avoid", "escort"],
    target_party_id: int = 0,
    world_control: bool = False,
) -> dict:
    """Apply Native map-party AI settings and read actual AI/position back.

    Main party is 0; other parties require explicit world_control. Fixed centers
    cannot move. Native scripts may overwrite NPC AI. Main-party engine behavior
    is still under live investigation: this is NOT yet a verified player travel
    capability. No teleport, clock advancement or invented movement. Check fresh
    world getters for actual movement, not just acknowledgement or AI values.
    """
    return await operation(
        "party_order",
        {
            "party_id": party_id,
            "order": order,
            "target_party_id": target_party_id,
            "world_control": world_control,
        },
    )


@mcp.tool()
async def warband_world_start_encounter(
    party_id: int, world_control: bool = False
) -> dict:
    """Explicit WORLD intervention: schedule Native town/castle/village encounter.

    Requires explicit world_control=True, free campaign map and noncaptivity.
    Schedules original Native auto-entry flow WITHOUT teleport or travel.
    Native's own map_free-guarded auto trigger executes entry. Scheduling isn't
    entry; immediate entry passed at Praven with no measured clock increment.
    Does not prove legitimate arrival, distance/contact, or normal player action.
    Mobile-party encounters not supported here yet. Acknowledgement is scheduling;
    world result describes target BEFORE entry, not proof of menu/scene arrival.
    Inspect fresh warband_get_state/menu_options for actual encounter outcome.
    """
    return await operation(
        "world_encounter", {"party_id": party_id, "world_control": world_control}
    )


@mcp.tool()
async def warband_leave_town_scene() -> dict:
    """Request normal departure from Native town_default scene (town/tavern/castle).

    Explicit request provides departure confirmation. Exact installed Native Tab
    permission is recognized at build; game retains its no-active-attacker guard.
    Requires living player, exact mission/session and no dialogue/battle. Not
    generic mission abort, battle retreat or village departure (quest effects).
    Uses engine teardown, not desktop input. Verify fresh menu context after ack.
    """
    return await operation("leave_scene", {})


@mcp.tool()
async def warband_campaign_wait(hours: int, speed: int = 1) -> dict:
    """Start Native attackable, interactive resting for 1–24 hours (speed 1–5).

    Zero hours cancels resting. Campaign map only, not captive. This genuinely
    advances the world: enemies, wages, food and quest timers remain active.
    Acknowledgement means resting started, NOT all requested hours elapsed.
    Inspect fresh state.clock and interruption/encounter context. Not travel.
    """
    return await operation("campaign_wait", {"hours": hours, "speed": speed})


@mcp.tool()
async def warband_world_command_result(command_id: int) -> dict:
    """Read durable actual engine facts for world inspection/diplomacy/party AI."""
    return await anyio.to_thread.run_sync(
        lambda: request(f"/api/world-results/{command_id}")
    )


@mcp.tool()
async def warband_goods_trade(
    side: Literal["buy", "sell"],
    slot: int,
    item_id: int,
    execute: bool = False,
    expected_price: int = 0,
) -> dict:
    """Quote or explicitly execute ONE full unmodified goods stack at town market.

    Not gear, unique items, partial stacks or an inventory editor. Slot is the
    source merchant slot for buy, player slot for sell. Item must still match.
    Quote first and read warband_trade_result. Execute recomputes price and rejects
    unless it equals expected_price; requires funds and a free destination slot.
    Executes reviewed stock/gold transfer plus original Native economic event.
    No UI pending barter balance. Inspect durable result before retrying effects.
    """
    return await operation(
        "goods_trade",
        {
            "side": side,
            "slot": slot,
            "item_id": item_id,
            "execute": execute,
            "expected_price": expected_price,
        },
    )


@mcp.tool()
async def warband_trade_result(command_id: int) -> dict:
    """Read durable quote/transaction engine facts separately from acknowledgement."""
    return await anyio.to_thread.run_sync(lambda: request(f"/api/trades/{command_id}"))


@mcp.tool()
async def warband_inspect_merchant(
    merchant: Literal["arms", "armor", "goods", "horses"],
    offset: int = 10,
    limit: int = 16,
) -> dict:
    """Queue a bounded actual town merchant inventory/price-factor page.

    Requires the town marketplace menu and exact entry session. Offset 10 skips
    equipped slots; empty slots remain explicit. Returns Native inventory and
    ORIGINAL buy/sell factor scripts, not assumed final prices. Modifiers, partial
    stacks and engine rounding are not yet integrated into transaction quotes.
    This does not buy/sell anything. Read warband_merchant_result afterwards.
    """
    return await operation(
        "scan_merchant", {"merchant": merchant, "offset": offset, "limit": limit}
    )


@mcp.tool()
async def warband_merchant_result(command_id: int) -> dict:
    """Read durable actual merchant inventory, gold and Native price factors."""
    return await anyio.to_thread.run_sync(
        lambda: request(f"/api/merchants/{command_id}")
    )


@mcp.tool()
async def warband_refresh_campaign(
    dataset: Literal[
        "party", "prisoners", "inventory", "character", "world_parties", "quests"
    ],
    offset: int = 0,
    limit: int = 16,
) -> dict:
    """Request a game-code campaign snapshot page (at most 16 rows).

    Read it with warband_campaign_result. Revision 4 services paused campaigns
    and Native menus; older modules need advancing game time. Inventory includes
    empty/equipment slots; world data includes
    all active parties, including hidden parties, so this is an omniscient debug
    view, not player-visible scouting. Quest titles are definition templates,
    not rendered journal text. A page is atomic only at its own export time.
    """
    return await operation(
        "scan_campaign", {"dataset": dataset, "offset": offset, "limit": limit}
    )


@mcp.tool()
async def warband_campaign_result(command_id: int) -> dict:
    """Read a durable campaign page. Wait for complete, then use next_offset.

    Rows are engine values; names are module definition labels. Stale pages must
    not be treated as current state. Separate pages can observe changing armies.
    """
    if command_id <= 0:
        raise ValueError("command_id must be positive")
    return await anyio.to_thread.run_sync(
        lambda: request(f"/api/campaign/{command_id}")
    )


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
