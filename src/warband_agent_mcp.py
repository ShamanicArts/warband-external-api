"""Constrained MCP adapter for one role-scoped Warband agent session."""

import os
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP

from bridge.game_bridge import load_token
from warband_agentic.agent_client import AgentHttpClient

mcp = FastMCP(
    "Warband Constrained Agent",
    log_level="WARNING",
    instructions=(
        "This server exposes exactly one role-scoped Warband session. Start with "
        "warband_agent_turn. Act only through a current opaque affordance, copy "
        "its bounded arguments, and copy observation.context.revision into "
        "expected_revision. On stale-context errors, fetch a fresh turn and reason "
        "again. A queued or accepted action is not proof of a game consequence; "
        "inspect the outcome evidence. Capability schemas describe possible shapes, "
        "but only a currently listed affordance authorizes an action. Choose a "
        "stable request_id for each intended action; reuse it only when retrying the "
        "identical submission."
    ),
)


def _client():
    endpoint = os.environ.get("WARBAND_AGENT_URL")
    token_path = os.environ.get("WARBAND_AGENT_TOKEN_FILE")
    if not endpoint or not token_path:
        raise RuntimeError(
            "Set WARBAND_AGENT_URL and WARBAND_AGENT_TOKEN_FILE for one session"
        )
    return AgentHttpClient(endpoint, load_token(Path(token_path)))


@mcp.tool()
async def warband_agent_manifest() -> dict:
    """Describe this session's public role, actor and submission contract."""
    return await anyio.to_thread.run_sync(lambda: _client().manifest())


@mcp.tool()
async def warband_agent_turn() -> dict:
    """Read the filtered observation and only the currently valid affordances."""
    return await anyio.to_thread.run_sync(lambda: _client().turn())


@mcp.tool()
async def warband_agent_act(
    request_id: str,
    affordance_token: str,
    arguments: dict,
    expected_revision: int,
) -> dict:
    """Submit one exact current affordance with a stable idempotency key.

    request_id must be 1-200 printable characters and unique to the intended
    action. Retry an identical submission with the same ID; changed intent needs
    a new ID. Capability schemas are descriptive: only a currently listed
    affordance token authorizes an action, and its required arguments must be
    copied exactly.
    """
    request = {
        "request_id": request_id,
        "affordance_token": affordance_token,
        "arguments": arguments,
        "expected_revision": expected_revision,
    }
    return await anyio.to_thread.run_sync(lambda: _client().submit(request))


@mcp.tool()
async def warband_agent_outcome(request_id: str) -> dict:
    """Reconcile a prior request with its latest evidence-bearing outcome."""
    return await anyio.to_thread.run_sync(lambda: _client().outcome(request_id))


@mcp.tool()
async def warband_agent_events(after: int = 0, limit: int = 100) -> dict:
    """Read this session's safe event page after a monotonic cursor."""
    return await anyio.to_thread.run_sync(lambda: _client().events(after, limit))


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
