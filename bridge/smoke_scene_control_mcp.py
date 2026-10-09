"""Actual MCP scene-control acceptance; player-controller failures stay explicit."""

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bridge.smoke_mcp import payload


async def run(args):
    proof: dict[str, Any] = {"method": "actual stdio MCP; Native actor operations"}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.warband_mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, arguments=None):
                response = await session.call_tool(name, arguments or {})
                result = payload(response)
                if response.isError:
                    raise RuntimeError(f"{name}: {result}")
                return result

            def save():
                args.evidence.write_text(json.dumps(proof, indent=2))

            async def command(name, arguments):
                cmd = await call(name, arguments)
                status = {}
                for _ in range(100):
                    status = await call(
                        "warband_command_status", {"command_id": cmd["id"]}
                    )
                    if status["status"] in (
                        "acknowledged",
                        "rejected",
                        "expired",
                        "interrupted",
                    ):
                        break
                    await asyncio.sleep(0.1)
                if status.get("status") != "acknowledged":
                    raise RuntimeError(f"{name} did not execute: {status}")
                return status

            async def scan():
                cmd = await command("warband_refresh_scene_agents", {})
                page = {}
                for _ in range(100):
                    page = await call("warband_scene_agents", {"command_id": cmd["id"]})
                    if page.get("complete"):
                        return page
                    await asyncio.sleep(0.1)
                raise RuntimeError(f"Incomplete scene census: {page}")

            proof["before"] = await call("warband_get_state")
            player = proof["before"]["player_agent_id"]
            proof["initial_scene"] = await scan()
            players = [
                a for a in proof["initial_scene"]["agents"] if a["agent_id"] == player
            ]
            if len(players) != 1:
                raise RuntimeError("Need player in bounded census for combat proof")
            catalog = json.loads(args.catalog.read_text())
            names = catalog["items"]
            melee = [
                item
                for item in players[0]["weapon_slots"]
                if item >= 0
                and any(
                    word in names.get(str(item), "").lower()
                    for word in ("sword", "cleaver", "axe", "mace", "spear")
                )
            ]
            if not melee:
                raise RuntimeError(
                    f"Need an actually equipped melee weapon: {players[0]}"
                )
            proof["selected_weapon"] = {
                "item_id": melee[0],
                "name": names[str(melee[0])],
            }
            proof["wield_command"] = await command(
                "warband_agent_wield",
                {
                    "agent_id": player,
                    "item_id": melee[0],
                },
            )
            await asyncio.sleep(0.3)
            proof["wield_scene"] = await scan()
            wielder = next(
                a for a in proof["wield_scene"]["agents"] if a["agent_id"] == player
            )
            if wielder["combat"]["weapon"] != melee[0]:
                save()
                raise RuntimeError(
                    f"Equipped melee weapon did not become wielded: {wielder}"
                )
            proof["attack_command"] = await command(
                "warband_agent_combat",
                {
                    "agent_id": player,
                    "action": "attack_hold",
                    "direction": "up",
                    "duration_ms": 0,
                },
            )
            await asyncio.sleep(0.3)
            proof["attack_scene"] = await scan()
            actor = next(
                a for a in proof["attack_scene"]["agents"] if a["agent_id"] == player
            )
            proof["clear_attack"] = await command(
                "warband_agent_combat",
                {
                    "agent_id": player,
                    "action": "clear_attack",
                    "direction": "up",
                    "duration_ms": 0,
                },
            )
            save()
            proof["player_attack_verified"] = not (
                actor["combat"]["attack"] not in (1, 2, 3, 6)
                or actor["combat"]["direction"] != 3
            )
            player_check = "PASS" if proof["player_attack_verified"] else "FAIL"
            print(f"{player_check} player attack: {actor['combat']}")
            save()
            x, y = (
                proof["before"]["position"]["x"] + 3,
                proof["before"]["position"]["y"] + 3,
            )
            proof["placement_command"] = await command(
                "warband_place_formation",
                {
                    "formation": 9,
                    "x": x,
                    "y": y,
                },
            )
            placement = {}
            for _ in range(100):
                placement = await call(
                    "warband_battle_order_result",
                    {"command_id": proof["placement_command"]["id"]},
                )
                if placement.get("complete"):
                    break
                await asyncio.sleep(0.1)
            proof["placement_result"] = placement
            save()
            if not placement.get("complete") or any(
                row["movement"] != 0
                or abs(row["x"] / 100 - x) > 0.02
                or abs(row["y"] / 100 - y) > 0.02
                for row in placement["formations"]
            ):
                raise RuntimeError(f"Formation placement mismatch: {placement}")
            print("PASS formation placement: all nine hold destinations match")
            page = await scan()
            allies = [
                a
                for a in page["agents"]
                if not a["is_player"] and a["team"] == players[0]["team"]
            ]
            if not allies:
                raise RuntimeError("Need an allied NPC for walking proof")
            allies = [
                a
                for a in allies
                if any(
                    item >= 0 and "sword" in names.get(str(item), "").lower()
                    for item in a["weapon_slots"]
                )
            ]
            if not allies:
                raise RuntimeError(
                    "Need allied melee equipment for directional combat proof"
                )
            npc = min(
                allies,
                key=lambda a: math.hypot(
                    a["position"]["x"] - x, a["position"]["y"] - y
                ),
            )
            proof["npc_before"] = npc
            target = {"x": npc["position"]["x"] + 5, "y": npc["position"]["y"]}
            proof["npc_target"] = target
            proof["npc_move_command"] = await command(
                "warband_move_npc", {"agent_id": npc["agent_id"], **target}
            )
            moved = 0
            distance_before = math.hypot(
                npc["position"]["x"] - target["x"], npc["position"]["y"] - target["y"]
            )
            for _ in range(15):
                await asyncio.sleep(0.5)
                page = await scan()
                current = next(
                    (a for a in page["agents"] if a["agent_id"] == npc["agent_id"]),
                    None,
                )
                if current is None:
                    raise RuntimeError("NPC disappeared/died during walking proof")
                proof["npc_after"] = current
                moved = distance_before - math.hypot(
                    current["position"]["x"] - target["x"],
                    current["position"]["y"] - target["y"],
                )
                if moved > 1:
                    break
            proof["npc_release_command"] = await command(
                "warband_release_npc", {"agent_id": npc["agent_id"]}
            )
            save()
            current = proof["npc_after"]
            if moved <= 1 or any(
                abs(current["scripted_destination"][key] - target[key]) > 0.02
                for key in ("x", "y")
            ):
                raise RuntimeError(
                    f"NPC did not walk towards requested engine destination: {current}"
                )
            proof["npc_clear_block"] = await command(
                "warband_agent_combat",
                {
                    "agent_id": npc["agent_id"],
                    "action": "clear_block",
                    "duration_ms": 0,
                },
            )
            npc_melee = next(
                item
                for item in current["weapon_slots"]
                if item >= 0 and "sword" in names.get(str(item), "").lower()
            )
            proof["npc_wield"] = await command(
                "warband_agent_wield",
                {
                    "agent_id": npc["agent_id"],
                    "item_id": npc_melee,
                },
            )
            await asyncio.sleep(1)
            proof["npc_attack_command"] = await command(
                "warband_agent_combat",
                {
                    "agent_id": npc["agent_id"],
                    "action": "attack_hold",
                    "direction": "up",
                    "duration_ms": 0,
                },
            )
            await asyncio.sleep(0.3)
            proof["npc_attack_scene"] = await scan()
            npc_actor = next(
                a
                for a in proof["npc_attack_scene"]["agents"]
                if a["agent_id"] == npc["agent_id"]
            )
            proof["npc_attack_verified"] = (
                npc_actor["combat"]["attack"] in (1, 2, 3, 6)
                and npc_actor["combat"]["direction"] == 3
            )
            proof["npc_clear_attack"] = await command(
                "warband_agent_combat",
                {
                    "agent_id": npc["agent_id"],
                    "action": "clear_attack",
                    "duration_ms": 0,
                },
            )
            proof["npc_block_command"] = await command(
                "warband_agent_combat",
                {
                    "agent_id": npc["agent_id"],
                    "action": "block",
                    "direction": "up",
                    "duration_ms": 5000,
                },
            )
            await asyncio.sleep(0.3)
            proof["npc_block_scene"] = await scan()
            blocker = next(
                a
                for a in proof["npc_block_scene"]["agents"]
                if a["agent_id"] == npc["agent_id"]
            )
            proof["npc_block_verified"] = blocker["combat"]["defend"] in (1, 2)
            proof["npc_clear_block_final"] = await command(
                "warband_agent_combat",
                {
                    "agent_id": npc["agent_id"],
                    "action": "clear_block",
                    "duration_ms": 0,
                },
            )
            proof["npc_final_release"] = await command(
                "warband_release_npc", {"agent_id": npc["agent_id"]}
            )
            proof["after"] = await call("warband_get_state")
            save()
            print(f"PASS NPC walking: moved {moved:.2f}m closer; release acknowledged")
            print(
                f"{'PASS' if proof['npc_attack_verified'] else 'FAIL'} NPC attack: "
                f"{npc_actor['combat']}"
            )
            print(
                f"{'PASS' if proof['npc_block_verified'] else 'FAIL'} NPC block: "
                f"{blocker['combat']}"
            )
            if not proof["npc_attack_verified"] or not proof["npc_block_verified"]:
                raise RuntimeError("Directional NPC combat failed; see evidence")
            if not proof["player_attack_verified"] and not args.npc_acceptance:
                raise RuntimeError(
                    "Player attack ineffective; NPC checks passed separately"
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument(
        "--npc-acceptance",
        action="store_true",
        help="Accept NPC/formation checks; record player failure",
    )
    asyncio.run(run(parser.parse_args()))
