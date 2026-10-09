"""Real MCP full merchant inventory pages; never equate factors with prices."""

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
        "method": "real MCP, Native merchant inventories/price factors",
        "merchants": {},
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.warband_mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, arguments=None):
                response = await session.call_tool(name, arguments or {})
                data = payload(response)
                if response.isError:
                    raise RuntimeError(f"{name}: {data}")
                return data

            proof["before"] = await call("warband_get_state")
            for merchant in ("arms", "armor", "goods", "horses"):
                offset = 10
                pages = []
                proof["merchants"][merchant] = pages
                while offset is not None:
                    cmd = await call(
                        "warband_inspect_merchant",
                        {"merchant": merchant, "offset": offset, "limit": 16},
                    )
                    page = {}
                    status = {}
                    for _ in range(150):
                        status = await call(
                            "warband_command_status", {"command_id": cmd["id"]}
                        )
                        page = await call(
                            "warband_merchant_result", {"command_id": cmd["id"]}
                        )
                        if status["status"] == "acknowledged" and page.get("complete"):
                            break
                        if status["status"] in ("rejected", "expired", "interrupted"):
                            raise RuntimeError(
                                f"Merchant engine rejected/expired command: {status}"
                            )
                        await asyncio.sleep(0.1)
                    if (
                        not page.get("complete")
                        or status.get("status") != "acknowledged"
                    ):
                        raise RuntimeError(f"Incomplete merchant page: {page}")
                    pages.append(page)
                    with open(args.evidence, "w") as file:
                        json.dump(proof, file, indent=2)
                    offset = page["next_offset"]
                rows = [row for page in pages for row in page["rows"]]
                if (
                    len({row["slot"] for row in rows}) != len(rows)
                    or len(rows) != pages[0]["total"] - 10
                ):
                    raise RuntimeError("Merchant pages duplicate/miss inventory slots")
                stock = [row for row in rows if row["item"] >= 0]
                if not stock or any(
                    row["buy_factor"] <= 0 or row["sell_factor"] <= 0 for row in stock
                ):
                    raise RuntimeError(
                        f"Missing stock or Native pricing factors: {stock}"
                    )
                print(
                    f"PASS {merchant}: {len(rows)} slots; {len(stock)} stocked; "
                    f"gold {pages[0]['merchant_gold']}"
                )
            proof["after"] = await call("warband_get_state")
            with open(args.evidence, "w") as file:
                json.dump(proof, file, indent=2)
            if proof["before"]["player_gold"] != proof["after"]["player_gold"]:
                raise RuntimeError("Read-only merchant inspection changed player gold")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    asyncio.run(run(parser.parse_args()))
