"""Execute a real Native choice through MCP; record its observable effect."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bridge.smoke_mcp import payload


async def run(args):
    proof: dict[str, Any] = {"method": "real stdio MCP calls; no desktop automation"}
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

            async def wait_command(command):
                status = {}
                for _ in range(240):
                    status = await call(
                        "warband_command_status", {"command_id": command["id"]}
                    )
                    if status["status"] in ("acknowledged", "rejected", "interrupted"):
                        return status
                    await asyncio.sleep(0.5)
                raise RuntimeError(f"Command never acknowledged: {status}")

            async def party():
                command = await call(
                    "warband_refresh_campaign",
                    {
                        "dataset": "party",
                        "offset": 0,
                        "limit": 16,
                    },
                )
                status = await wait_command(command)
                page = await call(
                    "warband_campaign_result", {"command_id": command["id"]}
                )
                if (
                    status["status"] != "acknowledged"
                    or not page["complete"]
                    or page["next_offset"] is not None
                ):
                    raise RuntimeError(f"Need a complete party snapshot: {page}")
                return page

            proof["catalog"] = await call("warband_menu_options")
            proof["before"] = await call("warband_get_state")
            matches = [
                a for a in proof["catalog"]["actions"] if a["option"] == args.option
            ]
            if len(matches) != 1:
                raise RuntimeError(f"Option not allowlisted here: {args.option}")
            if args.party_proof:
                proof["party_before"] = await party()
            proof["selected"] = matches[0]
            command = await call("warband_select_menu", {"action_id": matches[0]["id"]})
            proof["command"] = command
            proof["status"] = await wait_command(command)
            proof["after"] = await call("warband_get_state")
            if proof["status"]["status"] == "acknowledged" and (
                args.expect_menu or args.expect_mission
            ):
                for _ in range(240):
                    matched = (
                        not args.expect_menu
                        or proof["after"].get("menu_name") == args.expect_menu
                    )
                    matched &= (
                        not args.expect_mission
                        or proof["after"].get("mission_template") == args.expect_mission
                    )
                    if proof["after"].get("connected") and matched:
                        break
                    await asyncio.sleep(0.5)
                    proof["after"] = await call("warband_get_state")
            if args.party_proof and proof["status"]["status"] == "acknowledged":
                proof["party_after"] = await party()
                before = sum(r["count"] for r in proof["party_before"]["rows"])
                after = sum(r["count"] for r in proof["party_after"]["rows"])
                proof["recruitment_delta"] = {
                    "members_added": after - before,
                    "gold_spent": proof["before"]["player_gold"]
                    - proof["after"]["player_gold"],
                }
            args.evidence.write_text(json.dumps(proof, indent=2))
            if args.expect_rejected:
                if proof["status"]["status"] != "rejected":
                    raise RuntimeError(
                        "Expected a game-side Native condition rejection"
                    )
                if proof["before"]["player_gold"] != proof["after"]["player_gold"]:
                    raise RuntimeError("Rejected choice changed gold")
                print(
                    f"PASS Native rejected {args.option}: "
                    f"result={proof['status']['result']}"
                )
                return
            if proof["status"]["status"] != "acknowledged":
                raise RuntimeError(f"Native choice rejected: {proof['status']}")
            if args.expect_menu and proof["after"].get("menu_name") != args.expect_menu:
                raise RuntimeError(
                    f"Expected menu {args.expect_menu}: {proof['after']}"
                )
            if (
                args.expect_mission
                and proof["after"].get("mission_template") != args.expect_mission
            ):
                raise RuntimeError(
                    f"Expected mission {args.expect_mission}: {proof['after']}"
                )
            if args.party_proof:
                delta = proof["recruitment_delta"]
                if (
                    delta["members_added"] <= 0
                    or delta["gold_spent"] != 10 * delta["members_added"]
                ):
                    raise RuntimeError(
                        f"Recruitment did not match 10 denars/man: {delta}"
                    )
            print(
                f"PASS Native {proof['selected']['menu']}/{args.option}: acknowledged"
            )
            print(json.dumps(proof["after"]))
            if args.party_proof:
                print(f"PASS real recruitment: {proof['recruitment_delta']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--option", required=True)
    parser.add_argument("--expect-menu")
    parser.add_argument("--expect-mission")
    parser.add_argument("--party-proof", action="store_true")
    parser.add_argument("--expect-rejected", action="store_true")
    parser.add_argument("--evidence", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
