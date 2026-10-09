"""Actual Native center-entry proof, explicitly NOT player travel/arrival."""

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
        "method": "actual MCP world encounter; no movement/arrival claim"
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
                    raise RuntimeError(f"{name}: {reply.content}")
                return payload(reply)

            proof["before"] = await call("warband_get_state")
            # Prove that a default call cannot implicitly grant world authority.
            reply = await session.call_tool(
                "warband_world_start_encounter", {"party_id": args.party_id}
            )
            proof["default_rejection"] = {
                "is_error": reply.isError,
                "content": [part.model_dump() for part in reply.content],
            }
            save()
            if not reply.isError:
                raise RuntimeError("Default encounter was not authority-rejected")
            queued = await call(
                "warband_world_start_encounter",
                {"party_id": args.party_id, "world_control": True},
            )
            proof["queued"] = queued
            save()
            status = "pending"
            result: dict[str, Any] = {}
            state = proof["before"]
            for _ in range(150):
                result = await call(
                    "warband_world_command_result", {"command_id": queued["id"]}
                )
                state = await call("warband_get_state")
                proof.update(result=result, after=state)
                status = result["command"]["status"]
                if status in ("rejected", "expired", "interrupted"):
                    break
                if status == "acknowledged" and result.get("complete"):
                    break
                await asyncio.sleep(0.1)
            save()
            if status == "acknowledged" and result.get("complete"):
                proof["scheduled_state"] = state
                if state["context"] == "campaign" and args.advance_time:
                    proof["advance_time_request"] = await call(
                        "warband_campaign_wait", {"hours": 1, "speed": 1}
                    )
                    save()
                for _ in range(150):
                    state = await call("warband_get_state")
                    proof["after"] = state
                    if (
                        state["context"] == "menu"
                        and state["menu_name"] == args.expect_menu
                    ):
                        break
                    await asyncio.sleep(0.1)
                if state["context"] == "campaign" and state["connected"]:
                    proof["stop_time_request"] = await call(
                        "warband_campaign_wait", {"hours": 0, "speed": 1}
                    )
                save()
            if (
                proof["result"]["command"]["status"] != "acknowledged"
                or not proof["result"].get("complete")
                or proof["after"]["menu_name"] != args.expect_menu
                or proof["after"]["position"] != proof["before"]["position"]
                or proof["after"]["native_context"]["last_encounter_party_id"]
                != args.party_id
            ):
                raise RuntimeError(
                    "Native entry/motion checks failed; inspect retained evidence"
                )
            print(
                "PASS explicit world Native center entry:",
                args.expect_menu,
                "party",
                args.party_id,
                "; player position unchanged",
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--party-id", type=int, required=True)
    parser.add_argument("--expect-menu", required=True)
    parser.add_argument("--advance-time", action="store_true")
    parser.add_argument("--evidence", required=True)
    asyncio.run(run(parser.parse_args()))
