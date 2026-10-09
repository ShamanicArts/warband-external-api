#!/usr/bin/env python3
"""
Warband External API Bridge

Monitors files written by the Warband mod (via simple_triggers.txt file I/O)
and provides a WebSocket/stdio interface for external agents.

Usage:
    python3 bridge/warband_bridge.py              # stdio mode
    python3 bridge/warband_bridge.py --ws 8765    # WebSocket mode
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Default paths
GAME_DIR = Path(os.environ.get(
    "WARBAND_DIR",
    "/home/shamanic/.local/share/Steam/steamapps/common/MountBlade Warband"
))
STATE_FILE = GAME_DIR / "external_api_state.txt"
CMD_FILE = GAME_DIR / "external_api_cmd.txt"
CMD_LOCK = GAME_DIR / "external_api_lock.txt"

# State file format constants
# The mod writes one line per entity per tick:
#   STATE:<entity_type>:<entity_id>:<slot_name>=<value>
# Example:
#   PARTY:123456789:name=Lord Harlaus
#   PARTY:123456789:position_x=42.5
#   PARTY:123456789:position_y=-38.2
#   FACTION:6:treasury=12000
#   AGENT:98765:health=45
#   AGENT:98765:alive=1


def parse_state_line(line: str) -> dict | None:
    """Parse a single state line into a dict."""
    line = line.strip()
    if not line or line.startswith("#") or line.startswith(";"):
        return None
    parts = line.split(":", 3)
    if len(parts) < 4:
        return None
    entity_type, entity_id, key, value = parts
    return {
        "type": entity_type.strip(),
        "id": entity_id.strip(),
        "key": key.strip(),
        "value": value.strip(),
    }


def parse_state_file(path: Path) -> dict:
    """Read and parse the full state file into a nested dict."""
    if not path.exists():
        return {}
    
    state = {}
    content = path.read_text().strip()
    if not content:
        return state
    
    for line in content.split("\n"):
        entry = parse_state_line(line)
        if entry is None:
            continue
        etype = entry["type"]
        eid = entry["id"]
        key = entry["key"]
        value = entry["value"]
        
        if etype not in state:
            state[etype] = {}
        if eid not in state[etype]:
            state[etype][eid] = {}
        state[etype][eid][key] = value
    
    return state


def write_command(entity_type: str, entity_id: str, command: str, params: dict | None = None):
    """
    Write a command for the mod to pick up.
    
    Format:
        CMD:<entity_type>:<entity_id>:<command>:<json_params>
    """
    with open(CMD_LOCK, "w") as lock:
        lock.write(str(time.time()))
    
    params_str = json.dumps(params or {})
    with open(CMD_FILE, "a") as f:
        f.write(f"CMD:{entity_type}:{entity_id}:{command}:{params_str}\n")


def format_state_display(state: dict) -> str:
    """Format state for console display."""
    lines = []
    for etype, entities in sorted(state.items()):
        lines.append(f"\n=== {etype} ===")
        for eid, attrs in sorted(entities.items())[:5]:  # limit per type
            name = attrs.get("name", eid)
            lines.append(f"  {name} ({eid}):")
            for k, v in list(attrs.items())[:10]:
                lines.append(f"    {k} = {v}")
            if len(attrs) > 10:
                lines.append(f"    ... ({len(attrs) - 10} more)")
    return "\n".join(lines)


def run_stdio():
    """Run in stdio mode - print state to stdout, read commands from stdin."""
    print("[bridge] Warband External API Bridge (stdio mode)")
    print(f"[bridge] Watching: {STATE_FILE}")
    print(f"[bridge] Commands: {CMD_FILE}")
    print("[bridge] Ready. Waiting for state file...")
    sys.stdout.flush()
    
    last_mtime = 0
    while True:
        try:
            if STATE_FILE.exists():
                mtime = STATE_FILE.stat().st_mtime
                if mtime > last_mtime:
                    state = parse_state_file(STATE_FILE)
                    if state:
                        print(f"\n[bridge] State update ({len(state)} entity types):")
                        print(format_state_display(state))
                        sys.stdout.flush()
                    last_mtime = mtime
            
            # Check for commands on stdin
            if sys.stdin.isatty():
                time.sleep(1)
            else:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if line:
                    parts = line.split(" ", 3)
                    if len(parts) >= 3:
                        write_command(parts[0], parts[1], parts[2])
                        print(f"[bridge] Sent: {parts[0]}:{parts[1]}:{parts[2]}")
                    else:
                        print("[bridge] Usage: <entity_type> <entity_id> <command> [params_json]")
                    sys.stdout.flush()
        except KeyboardInterrupt:
            print("\n[bridge] Shutting down.")
            break
        except Exception as e:
            print(f"[bridge] Error: {e}")
            sys.stdout.flush()
            time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Warband External API Bridge")
    parser.add_argument("--ws", type=int, help="WebSocket port (default: stdio mode)")
    args = parser.parse_args()
    
    if args.ws:
        print("[bridge] WebSocket mode not yet implemented, falling back to stdio")
    
    run_stdio()
