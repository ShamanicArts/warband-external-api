"""Real MCP stdio handshake/state read; optional live game command proof."""

import argparse
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result):
    if result.isError:
        raise RuntimeError(result.content)
    if result.structuredContent is not None:
        return result.structuredContent
    for item in result.content:
        if item.type == "text":
            data = json.loads(item.text)
            if isinstance(data, dict):
                return data
    raise RuntimeError("Expected an MCP JSON object response")


async def main(message):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "src.warband_mcp"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("MCP tools:", ", ".join(tool.name for tool in tools.tools))
            result = await session.call_tool("warband_get_state", {})
            state = payload(result)
            print("Engine state:", json.dumps(state))
            if message is None:
                return
            if not state.get("connected"):
                raise RuntimeError("Game must be running with fresh telemetry")
            result = await session.call_tool(
                "warband_display_message", {"text": message}
            )
            command = payload(result)
            print("Queued command:", json.dumps(command))
            for _ in range(20):
                await asyncio.sleep(0.5)
                result = await session.call_tool(
                    "warband_command_status", {"command_id": command["id"]}
                )
                if payload(result)["status"] == "acknowledged":
                    print("PASS: game acknowledged actual MCP command")
                    return
            raise RuntimeError("Command was not acknowledged in 10 seconds")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", help="Opt-in: display this text through game code")
    asyncio.run(main(parser.parse_args().message))
