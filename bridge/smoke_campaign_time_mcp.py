"""Measure actual campaign time and party movement via real MCP; stop in finally."""

import argparse
import asyncio
import json
import math
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bridge.smoke_mcp import payload


async def run(args):
    proof: dict[str, Any] = {
        "method": "real MCP, attackable Native rest, engine positions"
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.warband_mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, arguments=None):
                reply = await session.call_tool(name, arguments or {})
                data = payload(reply)
                if reply.isError:
                    raise RuntimeError(f"{name}: {data}")
                return data

            async def command(name, arguments):
                queued = await call(name, arguments)
                status = {}
                for _ in range(150):
                    status = await call(
                        "warband_command_status", {"command_id": queued["id"]}
                    )
                    if status["status"] in (
                        "acknowledged",
                        "rejected",
                        "interrupted",
                        "expired",
                    ):
                        break
                    await asyncio.sleep(0.1)
                if status.get("status") != "acknowledged":
                    raise RuntimeError(f"Engine did not acknowledge {name}: {status}")
                return status

            async def party(entity_id=None):
                cmd = await command(
                    "warband_inspect_world_entity",
                    {
                        "entity": "party",
                        "entity_id": args.party_id if entity_id is None else entity_id,
                        "other_id": 0,
                    },
                )
                result = {}
                for _ in range(150):
                    result = await call(
                        "warband_world_command_result", {"command_id": cmd["id"]}
                    )
                    if result.get("complete"):
                        return result
                    await asyncio.sleep(0.1)
                raise RuntimeError(f"Missing party getter facts: {result}")

            proof["before"] = await call("warband_get_state")
            proof["party_before"] = await party()
            proof["target_before"] = await party(args.target_id)
            proof["order"] = await command(
                "warband_campaign_party_order",
                {
                    "party_id": args.party_id,
                    "order": "travel",
                    "target_party_id": args.target_id,
                    "world_control": args.party_id != 0,
                },
            )
            proof["after_order"] = await party()
            try:
                proof["wait"] = await command(
                    "warband_campaign_wait", {"hours": 1, "speed": 5}
                )
                samples = []
                proof["samples"] = samples
                for _ in range(40):
                    await asyncio.sleep(1)
                    state = await call("warband_get_state")
                    samples.append(state)
                    if (
                        state["clock"] > proof["before"]["clock"]
                        or state["context"] != "campaign"
                    ):
                        break
                proof["party_after"] = await party()
            finally:
                state = await call("warband_get_state")
                if state["connected"] and state["context"] == "campaign":
                    proof["stop_wait"] = await command(
                        "warband_campaign_wait", {"hours": 0, "speed": 1}
                    )
                else:
                    proof["stop_wait"] = {
                        "not_sent": "Encounter/menu interrupted rest; inspect first"
                    }
                proof["after"] = await call("warband_get_state")
                with open(args.evidence, "w") as file:
                    json.dump(proof, file, indent=2)
            start, end = (
                proof["party_before"]["facts"]["position"],
                proof["party_after"]["facts"]["position"],
            )
            movement = math.hypot(end["x"] - start["x"], end["y"] - start["y"])
            proof["measured_map_movement"] = movement
            proof["clock_advanced"] = proof["after"]["clock"] > proof["before"]["clock"]
            target = proof["target_before"]["facts"]["position"]
            closer = math.hypot(
                start["x"] - target["x"], start["y"] - target["y"]
            ) - math.hypot(end["x"] - target["x"], end["y"] - target["y"])
            proof["distance_to_target_improvement"] = closer
            proof["party_travel_verified"] = movement > 0.02 and closer > 0.02
            with open(args.evidence, "w") as file:
                json.dump(proof, file, indent=2)
            print("Clock advanced:", proof["clock_advanced"])
            print("Measured party movement:", movement, "map units; not teleport")
            print("Distance to target improved by:", closer, "map units")
            if not proof["clock_advanced"]:
                raise RuntimeError("Native rest did not measurably advance clock")
            if not proof["party_travel_verified"]:
                raise RuntimeError("AI setting did not move party; NOT verified travel")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--party-id", type=int, default=0)
    parser.add_argument("--target-id", type=int, required=True)
    parser.add_argument("--evidence", required=True)
    asyncio.run(run(parser.parse_args()))
