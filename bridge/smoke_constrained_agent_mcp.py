"""Exercise stale recovery through the real constrained-agent stdio MCP server."""

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
    environment = dict(os.environ)
    environment.update(
        {
            "WARBAND_AGENT_URL": args.endpoint,
            "WARBAND_AGENT_TOKEN_FILE": str(args.token_file),
        }
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.warband_agent_mcp"],
        env=environment,
    )
    proof = {
        "schema": "warband.agentic/evidence/direct-mcp-fixture/v1",
        "method": "real constrained-agent stdio MCP over deterministic HTTP fixture",
        "game_launched": False,
        "external_model_invoked": False,
    }
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            proof["tools"] = [tool.name for tool in tools.tools]
            expected_tools = {
                "warband_agent_manifest",
                "warband_agent_turn",
                "warband_agent_act",
                "warband_agent_outcome",
                "warband_agent_events",
            }
            if set(proof["tools"]) != expected_tools:
                raise RuntimeError("Constrained MCP exposed an unexpected tool set")

            proof["manifest"] = payload(
                await session.call_tool("warband_agent_manifest", {})
            )
            first = payload(await session.call_tool("warband_agent_turn", {}))
            proof["first_revision"] = first["observation"]["context"]["revision"]
            defend = _defend_affordance(first)
            stale = await session.call_tool(
                "warband_agent_act",
                {
                    "request_id": "direct-mcp:stale-attempt",
                    "affordance_token": defend["token"],
                    "arguments": {"order": "defend", "target_id": 2},
                    "expected_revision": proof["first_revision"],
                },
            )
            if not stale.isError:
                raise RuntimeError("Fixture did not reject the stale first action")
            proof["stale_rejected"] = True

            refreshed = payload(await session.call_tool("warband_agent_turn", {}))
            proof["refreshed_revision"] = refreshed["observation"]["context"][
                "revision"
            ]
            defend = _defend_affordance(refreshed)
            request_id = "direct-mcp:refreshed-defense"
            proof["action"] = payload(
                await session.call_tool(
                    "warband_agent_act",
                    {
                        "request_id": request_id,
                        "affordance_token": defend["token"],
                        "arguments": {"order": "defend", "target_id": 2},
                        "expected_revision": proof["refreshed_revision"],
                    },
                )
            )
            proof["outcome"] = payload(
                await session.call_tool(
                    "warband_agent_outcome", {"request_id": request_id}
                )
            )
    if proof["first_revision"] != 7 or proof["refreshed_revision"] != 8:
        raise RuntimeError("Fixture did not expose the expected revision transition")
    if proof["action"] != proof["outcome"] or proof["outcome"]["state"] != "observed":
        raise RuntimeError("Refreshed action did not reach an observed outcome")
    order_facts = [
        fact for fact in proof["outcome"]["facts"] if fact["key"] == "parties.17.order"
    ]
    if len(order_facts) != 1 or order_facts[0]["value"] != "defend":
        raise RuntimeError("Observed outcome did not prove the defense order")
    args.evidence.write_text(json.dumps(proof, indent=2) + "\n")
    return proof


def _defend_affordance(turn):
    matches = []
    for affordance in turn["affordances"]:
        properties = affordance["parameters"]["properties"]
        if (
            properties.get("order", {}).get("const") == "defend"
            and properties.get("target_id", {}).get("const") == 2
        ):
            matches.append(affordance)
    if len(matches) != 1:
        raise RuntimeError("Turn did not contain one exact Praven defense affordance")
    return matches[0]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args(argv)
    proof = asyncio.run(run(args))
    print(json.dumps(proof, sort_keys=True))


if __name__ == "__main__":
    main()
