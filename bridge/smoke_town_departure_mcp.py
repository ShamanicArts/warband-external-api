"""Actual normal town-scene departure, not CUA Tab or arbitrary mission abort."""

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
    proof: dict[str, Any] = {
        "method": "actual MCP recognized Native town permission and engine teardown"
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.warband_mcp"], env=dict(os.environ)
    )

    def save():
        with open(args.evidence, "w") as file:
            json.dump(proof, file, indent=2)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, arguments=None):
                reply = await session.call_tool(name, arguments or {})
                if reply.isError:
                    proof["error"] = {
                        "tool": name,
                        "content": [part.model_dump() for part in reply.content],
                    }
                    save()
                    raise RuntimeError(f"{name}: {reply.content}")
                return payload(reply)

            proof["before"] = await call("warband_get_state")
            save()
            queued = await call("warband_leave_town_scene")
            proof["queued"] = queued
            save()
            for _ in range(150):
                proof["command"] = await call(
                    "warband_command_status", {"command_id": queued["id"]}
                )
                proof["after"] = await call("warband_get_state")
                status = proof["command"]["status"]
                state = proof["after"]
                if status in ("rejected", "expired", "interrupted"):
                    break
                if (
                    status == "acknowledged"
                    and state["context"] == "menu"
                    and state["menu_name"] == args.expect_menu
                ):
                    break
                await asyncio.sleep(0.1)
            save()
            if (
                proof["command"]["status"] != "acknowledged"
                or proof["after"]["context"] != "menu"
                or proof["after"]["menu_name"] != args.expect_menu
                or proof["after"]["player_gold"] != proof["before"]["player_gold"]
                or proof["after"]["native_context"]["last_encounter_party_id"]
                != proof["before"]["native_context"]["last_encounter_party_id"]
            ):
                raise RuntimeError(
                    "Departure unproven; inspect retained evidence before retrying"
                )
            print(
                "PASS actual MCP departure: scene",
                proof["before"]["scene_id"],
                "to Native",
                args.expect_menu,
                "; unchanged gold/encounter",
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-menu", default="town")
    parser.add_argument("--evidence", required=True)
    asyncio.run(run(parser.parse_args()))
