"""Export or evaluate the deterministic agent-usability fixture as JSON."""

import argparse
import json
import sys

from warband_agentic.contracts import to_wire
from warband_agentic.usability import (
    build_faction_revision_recovery_fixture,
    build_faction_usability_fixture,
)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("export", "evaluate"))
    parser.add_argument(
        "--fixture",
        choices=("faction-order-v1", "faction-revision-recovery-v2"),
        default="faction-order-v1",
    )
    args = parser.parse_args(argv)
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
