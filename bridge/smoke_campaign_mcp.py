"""Real MCP campaign export proof; no CUA calls and no game-state mutations."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bridge.protocol import DATASETS
from bridge.smoke_mcp import payload


async def run(args):
    proof = {"pages": {}}
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
                    raise RuntimeError(f"MCP tool failed: {name}: {result}")
                return result

            proof["capabilities"] = await call("warband_capabilities")
            state = await call("warband_get_state")
            if not state.get("connected") or state.get("context") != "campaign":
                raise RuntimeError(f"Need a running isolated campaign: {state}")
            proof["before"] = state
            for dataset in args.datasets:
                pages = []
                offset = 0
                for _ in range(args.max_pages):
                    command = await call(
                        "warband_refresh_campaign",
                        {"dataset": dataset, "offset": offset, "limit": 16},
                    )
                    page = {}
                    for _ in range(60):
                        page = await call(
                            "warband_campaign_result", {"command_id": command["id"]}
                        )
                        status = await call(
                            "warband_command_status", {"command_id": command["id"]}
                        )
                        if status["status"] in ("rejected", "expired", "interrupted"):
                            raise RuntimeError(f"Export did not execute: {status}")
                        if page.get("complete") and status["status"] == "acknowledged":
                            break
                        await asyncio.sleep(0.5)
                    else:
                        raise RuntimeError(f"Export incomplete: {dataset}: {page}")
                    pages.append(page)
                    print(
                        f"PASS {dataset}: offset={offset} rows={len(page['rows'])} "
                        f"total={page['total']} acknowledged"
                    )
                    if page["next_offset"] is None:
                        break
                    offset = page["next_offset"]
                proof["pages"][dataset] = pages
            proof["after"] = await call("warband_get_state")
    args.evidence.write_text(json.dumps(proof, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--datasets", nargs="+", choices=list(DATASETS), default=list(DATASETS)
    )
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--evidence", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
