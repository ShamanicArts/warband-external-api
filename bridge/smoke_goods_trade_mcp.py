"""Actual MCP quote/guarded trade acceptance; inspect before any retry."""

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
        "method": "actual MCP full/unmodified goods trade",
        "commands": [],
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
                response = await session.call_tool(name, arguments or {})
                if response.isError:
                    raise RuntimeError(f"{name}: {response.content}")
                return payload(response)

            async def trade(execute=False, price=0, rejected=False):
                queued = await call(
                    "warband_goods_trade",
                    {
                        "side": args.side,
                        "slot": args.slot,
                        "item_id": args.item_id,
                        "execute": execute,
                        "expected_price": price,
                    },
                )
                proof["commands"].append({"queued": queued})
                save()
                result = {}
                for _ in range(150):
                    result = await call(
                        "warband_trade_result", {"command_id": queued["id"]}
                    )
                    status = result["command"]["status"]
                    if (
                        status in ("rejected", "expired", "interrupted")
                        or status == "acknowledged"
                        and result.get("complete")
                    ):
                        break
                    await asyncio.sleep(0.1)
                proof["commands"][-1]["result"] = result
                save()
                if rejected:
                    if result["command"]["status"] != "rejected":
                        raise RuntimeError(f"Price mismatch not rejected: {result}")
                elif result["command"]["status"] != "acknowledged" or not result.get(
                    "complete"
                ):
                    raise RuntimeError(
                        f"Missing engine transaction result; DO NOT retry: {result}"
                    )
                return result

            proof["before"] = await call("warband_get_state")
            quote = await trade()
            proof["quote"] = quote
            facts = quote["facts"]
            if args.expect_price is not None and facts["price"] != args.expect_price:
                raise RuntimeError(
                    f"Quote differs from independently expected price: {facts}"
                )
            if args.execute:
                await trade(True, facts["price"] + 1, rejected=True)
                after_rejection = await trade()
                if after_rejection["facts"] != facts:
                    raise RuntimeError(
                        "Rejected price agreement changed quote/stock/gold"
                    )
                result = await trade(True, facts["price"])
                proof["executed"] = result
                end = result["facts"]
                direction = -1 if args.side == "buy" else 1
                if (
                    end["player_gold"]
                    != facts["player_gold"] + direction * facts["price"]
                    or end["merchant_gold"]
                    != facts["merchant_gold"] - direction * facts["price"]
                    or end["source_item"] != -1
                    or end["destination_item"] != args.item_id
                    or end["destination_amount"] != facts["source_amount"]
                ):
                    raise RuntimeError(
                        f"Transaction conservation/readback mismatch: {end}"
                    )
                print("PASS actual trade:", end)
            else:
                print("PASS read-only quote:", facts)
            proof["after"] = await call("warband_get_state")
            save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--item-id", type=int, required=True)
    parser.add_argument("--expect-price", type=int)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence", required=True)
    asyncio.run(run(parser.parse_args()))
