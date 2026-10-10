"""Export or resolve the deterministic two-faction benchmark arena."""

import argparse
import json
import sys
from pathlib import Path

from warband_agentic.faction_arena import (
    build_deterministic_faction_arena,
    build_deterministic_faction_campaign,
)


def _write_stream_event(event_type, key, value):
    json.dump(
        {
            "schema": "warband.agentic/deterministic-faction-campaign-event/v1",
            "type": event_type,
            key: value,
        },
        sys.stdout,
        separators=(",", ":"),
        sort_keys=True,
    )
    sys.stdout.write("\n")
    sys.stdout.flush()


def _campaign_stream(parser, args):
    if args.faction is not None:
        parser.error("--faction is not valid with campaign")
    campaign = build_deterministic_faction_campaign(epoch_count=args.epochs or 3)
    _write_stream_event("turn", "briefing", campaign.briefing())
    lines = (
        Path(args.input).read_text(encoding="utf-8").splitlines()
        if args.input is not None
        else sys.stdin
    )
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            decisions = {int(key): response for key, response in value.items()}
        except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
            parser.error(
                "each campaign input line must be an object keyed by faction ID"
            )
        step = campaign.submit(decisions)
        if step["state"] == "complete":
            _write_stream_event("report", "report", step["report"])
            return
        _write_stream_event("turn", "briefing", step["briefing"])
    parser.error("campaign input ended before every epoch received decisions")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("export", "resolve", "resolve-providers", "campaign")
    )
    parser.add_argument("input", nargs="?", help="JSON input file; defaults to stdin")
    parser.add_argument("--faction", type=int, choices=(15, 16))
    parser.add_argument("--epochs", type=int, choices=range(1, 101))
    args = parser.parse_args(argv)

    if args.command == "campaign":
        _campaign_stream(parser, args)
        return
    if args.epochs is not None:
        parser.error("--epochs is only valid with campaign")
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
