"""Prove actual engine formation orders through the real stdio MCP server."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bridge.smoke_mcp import payload


async def run(args):
    proof = {
        "method": "actual stdio MCP and Warband engine order read-back",
        "steps": [],
    }
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

            if args.verify_restart:
                existing = json.loads(args.evidence.read_text())
                checked = []
                for step in existing["steps"]:
                    job = step["result"]["command_id"]
                    result = await call(
                        "warband_battle_order_result", {"command_id": job}
                    )
                    if (
                        not result["complete"]
                        or result["command"]["status"] != "acknowledged"
                        or result["formations"] != step["result"]["formations"]
                    ):
                        raise RuntimeError(f"Order read-back lost after restart: {job}")
                    checked.append(job)
                existing["restart_verification"] = {
                    "method": "real stdio MCP reads after bridge process restart",
                    "command_ids": checked,
                    "all_results_preserved": True,
                }
                args.evidence.write_text(json.dumps(existing, indent=2))
                print(
                    f"PASS bridge restart: {len(checked)} durable MCP results preserved"
                )
                return

            proof["before"] = await call("warband_get_state")
            for order, field, value in (
                ("hold_fire", "fire", 1),
                ("fire_at_will", "fire", 0),
                ("follow", "movement", 1),
                ("hold", "movement", 0),
            ):
                command = await call(
                    "warband_battle_order",
                    {
                        "formation": 9,
                        "order": order,
                    },
                )
                result = {}
                for _ in range(100):
                    result = await call(
                        "warband_battle_order_result",
                        {
                            "command_id": command["id"],
                        },
                    )
                    if result["command"]["status"] in (
                        "rejected",
                        "expired",
                        "interrupted",
                    ):
                        raise RuntimeError(f"Battle command failed: {result}")
                    if (
                        result["complete"]
                        and result["command"]["status"] == "acknowledged"
                    ):
                        break
                    await asyncio.sleep(0.2)
                if (
                    not result.get("complete")
                    or result["command"]["status"] != "acknowledged"
                    or any(row[field] != value for row in result["formations"])
                ):
                    raise RuntimeError(
                        f"Native read-back did not match {order}: {result}"
                    )
                proof["steps"].append({"order": order, "result": result})
                args.evidence.write_text(json.dumps(proof, indent=2))
                print(f"PASS {order}: acknowledged; all 9 formations {field}={value}")
            proof["after"] = await call("warband_get_state")
            args.evidence.write_text(json.dumps(proof, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--verify-restart", action="store_true")
    asyncio.run(run(parser.parse_args()))
