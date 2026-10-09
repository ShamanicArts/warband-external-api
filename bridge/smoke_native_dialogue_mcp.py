"""Actual original Native entry, no injected line or claimed choice execution."""

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
        "method": "actual MCP Native conversation entry; no choice-success claim"
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
                result = await session.call_tool(name, arguments or {})
                if result.isError:
                    proof["error"] = {
                        "tool": name,
                        "content": [p.model_dump() for p in result.content],
                    }
                    save()
                    raise RuntimeError(f"{name} failed; inspect evidence")
                return payload(result)

            proof["before"] = await call("warband_get_state")
            save()
            queued = await call(
                "warband_start_native_conversation", {"agent_id": args.agent_id}
            )
            proof["queued"] = queued
            save()
            for _ in range(150):
                proof["command"] = await call(
                    "warband_command_status", {"command_id": queued["id"]}
                )
                proof["after"] = await call("warband_get_state")
                status = proof["command"]["status"]
                if status in ("rejected", "expired", "interrupted"):
                    break
                if status == "acknowledged" and proof["after"]["dialogue_active"]:
                    break
                await asyncio.sleep(0.1)
            save()
            if (
                proof["command"]["status"] != "acknowledged"
                or not proof["after"]["dialogue_active"]
            ):
                raise RuntimeError(
                    "Native entry unproven; inspect facts and independent screenshot"
                )
            print(
                "PASS entry dispatch/dialogue flag; independent screenshot required"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument("--evidence", required=True)
    asyncio.run(run(parser.parse_args()))
