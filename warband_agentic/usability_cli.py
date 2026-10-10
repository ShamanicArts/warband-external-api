"""Export or evaluate the deterministic agent-usability fixture as JSON."""

import argparse
import json
import sys
from pathlib import Path

from bridge.game_bridge import load_token
from warband_agentic.agent_http import make_agent_server
from warband_agentic.contracts import to_wire
from warband_agentic.mcp_usability import build_faction_mcp_usability_fixture
from warband_agentic.usability import (
    build_faction_revision_recovery_fixture,
    build_faction_usability_fixture,
)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("export", "evaluate", "serve-mcp"))
    parser.add_argument(
        "--fixture",
        choices=("faction-order-v1", "faction-revision-recovery-v2"),
        default="faction-order-v1",
    )
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == "serve-mcp":
        if args.fixture != "faction-revision-recovery-v2":
            parser.error(
                "serve-mcp currently requires --fixture faction-revision-recovery-v2"
            )
        if args.token_file is None:
            parser.error("serve-mcp requires --token-file")
        if not 0 <= args.port <= 65535:
            parser.error("--port must be from 0 through 65535")
        fixture = build_faction_mcp_usability_fixture()
        server = make_agent_server(
            fixture.session,
            load_token(args.token_file),
            port=args.port,
        )
        json.dump(
            {
                "endpoint": f"http://127.0.0.1:{server.server_port}",
                "fixture": "faction-revision-recovery-v2",
                "game_launched": False,
                "task": fixture.task(),
            },
            sys.stdout,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        sys.stdout.flush()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return
    if args.token_file is not None or args.port != 0:
        parser.error("--token-file and --port are only valid with serve-mcp")
    fixture = (
        build_faction_usability_fixture()
        if args.fixture == "faction-order-v1"
        else build_faction_revision_recovery_fixture()
    )
    if args.command == "export":
        result = fixture.briefing()
    else:
        result = to_wire(fixture.evaluate(json.load(sys.stdin)))
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
