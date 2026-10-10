"""Export or resolve the deterministic two-faction benchmark arena."""

import argparse
import json
import sys
from pathlib import Path

from warband_agentic.faction_arena import build_deterministic_faction_arena


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "resolve", "resolve-providers"))
    parser.add_argument("input", nargs="?", help="JSON input file; defaults to stdin")
    parser.add_argument("--faction", type=int, choices=(15, 16))
    args = parser.parse_args(argv)

    arena = build_deterministic_faction_arena()
    if args.command == "export":
        if args.input is not None:
            parser.error("export does not accept an input file")
        result = arena.task(args.faction) if args.faction else arena.briefing()
    else:
        if args.faction is not None:
            parser.error("--faction is only valid with export")
        value = (
            json.loads(Path(args.input).read_text())
            if args.input is not None
            else json.load(sys.stdin)
        )
        if not isinstance(value, dict):
            parser.error("resolve input must be an object keyed by faction ID")
        try:
            decisions = {int(key): response for key, response in value.items()}
        except (TypeError, ValueError):
            parser.error("resolve faction keys must be integers")
        result = (
            arena.resolve_provider_results(decisions)
            if args.command == "resolve-providers"
            else arena.resolve(decisions)
        )
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
