"""Actual MCP world getter/action proof; no invented campaign movement."""

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bridge.smoke_mcp import payload


async def run(args):
    proof: dict[str, Any] = {"method": "actual stdio MCP and engine world results"}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.warband_mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, arguments):
                response = await session.call_tool(name, arguments)
                result = payload(response)
                if response.isError:
                    raise RuntimeError(f"{name}: {result}")
                return result

            async def command(name, arguments, rejected=False):
                cmd = await call(name, arguments)
                result: dict[str, Any] = {}
                status = "pending"
                for _ in range(150):
                    result = await call(
                        "warband_world_command_result",
                        {
                            "command_id": cmd["id"],
                        },
                    )
                    status = result["command"]["status"]
                    if status in ("acknowledged", "rejected", "expired", "interrupted"):
                        if (
                            rejected
                            or result.get("complete")
                            or status != "acknowledged"
                        ):
                            break
                    await asyncio.sleep(0.1)
                proof[name] = result
                with open(args.evidence, "w") as f:
                    json.dump(proof, f, indent=2)
                if status != ("rejected" if rejected else "acknowledged"):
                    raise RuntimeError(f"Unexpected command outcome: {result}")
                if not rejected and not result.get("complete"):
                    raise RuntimeError(f"Missing engine facts: {result}")
                return result

            proof["before"] = await call("warband_get_state", {})
            result = await command(
                "warband_inspect_world_entity",
                {
                    "entity": args.entity,
                    "entity_id": args.entity_id,
                    "other_id": args.other_id,
                },
            )
            print("PASS engine world facts:", result["facts"])
            if args.diplomacy:
                result = await command(
                    "warband_diplomacy",
                    {
                        "faction_a": args.entity_id,
                        "faction_b": args.other_id,
                        "action": args.diplomacy,
                        "world_control": args.world_control,
                    },
                    rejected=args.expect_rejected,
                )
                if not args.expect_rejected:
                    relation = result["facts"]["relation"]
                    if (
                        args.diplomacy == "war"
                        and relation >= 0
                        or args.diplomacy == "peace"
                        and relation < 0
                    ):
                        raise RuntimeError(f"Diplomacy read-back mismatch: {result}")
                print("PASS diplomacy outcome:", result)
            if args.order:
                result = await command(
                    "warband_campaign_party_order",
                    {
                        "party_id": args.entity_id,
                        "target_party_id": args.other_id,
                        "order": args.order,
                        "world_control": args.world_control,
                    },
                    rejected=args.expect_rejected,
                )
                print("Party AI outcome (NOT travel proof):", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", choices=["faction", "party"], required=True)
    parser.add_argument("--entity-id", type=int, required=True)
    parser.add_argument("--other-id", type=int, default=0)
    parser.add_argument("--diplomacy", choices=["war", "peace"])
    parser.add_argument(
        "--order", choices=["hold", "travel", "patrol", "attack", "avoid", "escort"]
    )
    parser.add_argument("--world-control", action="store_true")
    parser.add_argument("--expect-rejected", action="store_true")
    parser.add_argument("--evidence", required=True)
    asyncio.run(run(parser.parse_args()))
