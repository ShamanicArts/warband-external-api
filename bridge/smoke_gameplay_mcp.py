"""Live MCP-only gameplay proof. CUA is used separately for visual validation."""

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bridge.smoke_mcp import payload


async def run(args):
    proof = {}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.warband_mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, arguments=None):
                return payload(await session.call_tool(name, arguments or {}))

            async def wait(name, arguments, predicate):
                result = {}
                for _ in range(30):
                    result = await call(name, arguments)
                    if predicate(result):
                        return result
                    await asyncio.sleep(0.5)
                raise RuntimeError(f"Timed out waiting for {name}: {result}")

            state = await call("warband_get_state")
            if not state.get("connected") or state.get("protocol") != 2:
                raise RuntimeError(f"Need live protocol-2 mod telemetry: {state}")
            proof["before"] = state
            command = await call("warband_refresh_scene_agents")
            census = await wait(
                "warband_scene_agents",
                {"command_id": command["id"]},
                lambda r: r.get("complete") is True,
            )
            proof["census"] = census
            census_status = await wait(
                "warband_command_status",
                {"command_id": command["id"]},
                lambda r: r["status"] in ("acknowledged", "rejected"),
            )
            if census_status["status"] != "acknowledged":
                raise RuntimeError(f"Census rejected: {census_status}")
            print("Complete engine census:", len(census["agents"]), "living humans")
            print(
                "NPCs:",
                [
                    (a["agent_id"], a["name"])
                    for a in census["agents"]
                    if not a["is_player"]
                ],
            )
            if args.relocate:
                state = await call("warband_get_state")
                target = {"x": state["position"]["x"] + 2, "y": state["position"]["y"]}
                command = await call("warband_relocate_player", target)
                result = await wait(
                    "warband_command_status",
                    {"command_id": command["id"]},
                    lambda r: r["status"] in ("acknowledged", "rejected"),
                )
                if result["status"] != "acknowledged":
                    raise RuntimeError(f"Relocation rejected: {result}")
                after = await call("warband_get_state")
                if (
                    math.hypot(
                        after["position"]["x"] - target["x"],
                        after["position"]["y"] - target["y"],
                    )
                    > 0.05
                ):
                    raise RuntimeError(f"Position verification failed: {after}")
                proof["relocation"] = {
                    "command": result,
                    "target": target,
                    "after": after,
                }
                print(
                    "PASS: game-script relocation verified by engine position", target
                )
            if args.npc_line:
                candidates = [a for a in census["agents"] if not a["is_player"]]
                trainers = [
                    a for a in candidates if "trainer" in (a["name"] or "").lower()
                ]
                state = await call("warband_get_state")
                npc = min(
                    trainers or candidates,
                    key=lambda a: math.hypot(
                        a["position"]["x"] - state["position"]["x"],
                        a["position"]["y"] - state["position"]["y"],
                    ),
                )
                command = await call(
                    "warband_npc_say",
                    {"agent_id": npc["agent_id"], "text": args.npc_line},
                )
                event = await wait(
                    "warband_dialogue_event",
                    {"command_id": command["id"]},
                    lambda r: r.get("event") == "opened",
                )
                proof["npc_speech"] = {"command": command, "npc": npc, "event": event}
                print(
                    "PASS: actual NPC dialogue hook opened", npc["name"], command["id"]
                )
    if args.evidence:
        args.evidence.write_text(json.dumps(proof, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--relocate", action="store_true", help="Opt-in: teleport +2m")
    parser.add_argument(
        "--npc-line", help="Opt-in: render this line in an NPC dialogue"
    )
    parser.add_argument("--evidence", type=Path)
    asyncio.run(run(parser.parse_args()))
