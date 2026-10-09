"""Portable HTTP transport for vanilla Warband's send_message_to_url opcode."""

import argparse
import hmac
import json
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bridge.campaign import CampaignExports
from bridge.protocol import OPERATIONS, validate_operation, wire_arguments


class Store:
    def __init__(self, database: Path, catalog=None):
        self.lock = threading.RLock()
        self.wakeup = threading.Condition(self.lock)
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS commands "
            "(id INTEGER PRIMARY KEY, text TEXT, created REAL, status TEXT)"
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(commands)")}
        for name, declaration in {
            "kind": "TEXT NOT NULL DEFAULT 'message'",
            "arguments": "TEXT NOT NULL DEFAULT '{}'",
            "scene": "INTEGER",
            "session": "INTEGER",
            "result": "INTEGER",
        }.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE commands ADD COLUMN {name} {declaration}")
        self._interrupt_mission_commands()
        self.db.commit()
        self.state = None
        self.diagnostics = {}
        self.scans = {}
        self.dialogues = {}
        self.catalog = (catalog or {}).get("troops", {})
        self.module_catalog = catalog or {}
        self.campaign = CampaignExports(self.db, catalog or {})

    def _interrupt_mission_commands(self):
        # A restart cannot prove the old mission still exists. Never replay its
        # effects automatically; dispatched commands may already have executed.
        self.db.execute(
            "UPDATE commands SET status=CASE WHEN status='queued' THEN 'rejected' "
            "ELSE 'interrupted' END, result=-3 "
            "WHERE kind!='message' AND status IN ('queued','dispatched')"
        )

    def _expire(self, now):
        self.db.execute(
            "UPDATE commands SET status='expired' "
            "WHERE status IN ('queued', 'dispatched') AND created<?",
            (now - 30,),
        )

    def enqueue(self, text, kind="message", arguments=None, scope=None):
        if not isinstance(text, str) or not 1 <= len(text) <= 200:
            raise ValueError("Message must contain 1–200 characters")
        if any(c in text for c in "|\r\n\x00") or not text.isprintable():
            raise ValueError("Message cannot contain protocol delimiters or controls")
        with self.lock:
            self._expire(time.time())
            count = self.db.execute(
                "SELECT count(*) FROM commands WHERE status IN ('queued', 'dispatched')"
            ).fetchone()[0]
            if count >= 32:
                raise ValueError("Command queue is full")
            last = self.db.execute(
                "SELECT COALESCE(max(id), 0) FROM commands"
            ).fetchone()[0]
            command_id = max(last + 1, int(time.time()))
            self.db.execute(
                "INSERT INTO commands "
                "(id,text,created,status,kind,arguments,scene,session) "
                "VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)",
                (
                    command_id,
                    text,
                    time.time(),
                    kind,
                    json.dumps(arguments if arguments is not None else {"text": text}),
                    (scope or {}).get("scene_id"),
                    (scope or {}).get("mission_session"),
                ),
            )
            self.db.commit()
            self.wakeup.notify_all()
            return self.command(command_id)

    def enqueue_operation(self, kind, arguments):
        with self.lock:
            state = self.snapshot()
            validate_operation(kind, arguments, state)
            if kind == "npc_say":
                candidates = [
                    scan
                    for scan in self.scans.values()
                    if scan["complete"]
                    and scan["scene_id"] == state["scene_id"]
                    and scan["mission_session"] == state["mission_session"]
                    and time.time() - scan["created"] < 30
                ]
                if (
                    not candidates
                    or arguments["agent_id"] not in candidates[-1]["agents"]
                ):
                    raise ValueError("Refresh scene agents before targeting this NPC")
                if candidates[-1]["agents"][arguments["agent_id"]]["is_player"]:
                    raise ValueError("NPC speech cannot target the player")
            return self.enqueue(
                arguments.get("text", kind),
                kind,
                arguments,
                state if kind != "message" else None,
            )

    def command(self, command_id):
        with self.lock:
            self._expire(time.time())
            self.db.commit()
            row = self.db.execute(
                "SELECT * FROM commands WHERE id=?", (command_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Unknown command ID")
            data = dict(row)
            data["arguments"] = json.loads(data["arguments"])
            return data

    def poll(self, query, wait_seconds=0):
        fields = ("ack", "gold", "troop", "hp", "x", "y", "z", "clock")
        if query.get("v") not in ("1", "2") or query.get("context") not in (
            "mission",
            "campaign",
            "menu",
        ):
            raise ValueError("Unsupported game protocol/context")
        values = {field: int(query[field]) for field in fields}
        if query["v"] == "2":
            values.update(
                {
                    field: int(query[field])
                    for field in ("scene", "agent", "result", "session")
                }
            )
            values.update(
                {
                    field: int(query[field])
                    for field in (
                        "mission",
                        "flags",
                        "captive",
                        "town",
                        "encounter",
                        "build",
                        "menu",
                        "dialogue",
                        "pulse",
                    )
                    if field in query
                }
            )
        if any(abs(v) > 2**53 for v in values.values()):
            raise ValueError("State value out of bounds")
        now = time.time()
        with self.lock:
            if (
                self.state
                and query["context"] == "mission"
                and self.state["context"] == "mission"
                and values["clock"] < self.state["clock"]
            ):
                self._interrupt_mission_commands()
            self.state = {
                "source": "Warband engine scripts",
                "protocol": int(query["v"]),
                "context": query["context"],
                "received_at": now,
                "player_gold": values["gold"],
                "player_troop_id": values["troop"],
                "player_hit_points": values["hp"]
                if query["context"] == "mission"
                else None,
                "position": {k: values[k] / 100 for k in ("x", "y", "z")},
                "clock": values["clock"],
                "acknowledged_command_id": values["ack"],
                "scene_id": values.get("scene"),
                "mission_session": values.get("session"),
                "player_agent_id": values.get("agent"),
                "last_command_result": values.get("result", 0),
                "integration_revision": values.get("build", 2),
                "mission_template_id": values.get("mission"),
                "mission_template": self.module_catalog.get("missions", {}).get(
                    str(values.get("mission"))
                ),
                "mission_flags": values.get("flags"),
                "menu_id": values.get("menu") if query["context"] == "menu" else None,
                "menu_name": self.module_catalog.get("menus", {}).get(
                    str(values.get("menu"))
                )
                if query["context"] == "menu"
                else None,
                "dialogue_active": bool(values.get("dialogue", 0)),
                "player_is_captive": bool(values["captive"])
                if values.get("captive") in (0, 1)
                else None,
                "native_context": {
                    "last_town_id": values.get("town"),
                    "last_encounter_party_id": values.get("encounter"),
                    "caveat": "Prior Native context; not proof of an active menu",
                },
            }
            self.db.execute(
                "UPDATE commands SET status=?, result=? "
                "WHERE id=? AND status IN ('dispatched', 'expired', 'interrupted')",
                (
                    "acknowledged" if values.get("result", 0) == 0 else "rejected",
                    values.get("result", 0),
                    values["ack"],
                ),
            )
            self._expire(now)
            waited = False
            while True:
                row = self.db.execute(
                    "SELECT * FROM commands WHERE status IN ('queued', 'dispatched') "
                    "ORDER BY id LIMIT 1"
                ).fetchone()
                if row is None and wait_seconds and not waited:
                    self.wakeup.wait(timeout=min(max(wait_seconds, 0), 2))
                    waited = True
                    continue
                if (
                    row is None
                    or row["kind"] == "message"
                    or (
                        row["kind"] == "scan_campaign"
                        and query["context"] in ("campaign", "menu")
                        and query["v"] == "2"
                    )
                    or (
                        row["kind"] != "scan_campaign"
                        and query["v"] == "2"
                        and row["scene"] == values.get("scene")
                        and row["session"] == values.get("session")
                        and query["context"] == "mission"
                    )
                ):
                    break
                self.db.execute(
                    "UPDATE commands SET status='rejected',result=-2 WHERE id=?",
                    (row["id"],),
                )
            if row:
                self.db.execute(
                    "UPDATE commands SET status='dispatched' WHERE id=?", (row["id"],)
                )
            self.db.commit()
            if query["v"] == "1":
                return (
                    f"741731|1|{row['id']}|1|0|{row['text']}"
                    if row
                    else "741731|1|0|0|0|idle"
                )
            if not row:
                return (
                    f"741731|2|0|0|0|0|0|0|0|{values['pulse']}|idle"
                    if "pulse" in values
                    else "741731|2|0|0|0|0|0|0|0|idle"
                )
            args = wire_arguments(row["kind"], json.loads(row["arguments"]))
            args[3] = row["session"] if row["session"] is not None else -1
            fields = [
                741731,
                2,
                row["id"],
                OPERATIONS[row["kind"]],
                *args,
                row["scene"] if row["scene"] is not None else -1,
            ]
            if "pulse" in values:
                fields.append(values["pulse"])
            return "|".join(map(str, [*fields, row["text"]]))

    def event(self, path, query):
        if query.get("v") != "2":
            raise ValueError("Expected protocol-2 event")
        job = int(query["job"])
        with self.lock:
            command = self.command(job)
            if command["status"] not in (
                "dispatched",
                "acknowledged",
                "expired",
                "interrupted",
            ):
                raise ValueError("Event does not correspond to a dispatched command")
            if path in ("/campaign-row", "/campaign-end"):
                self.campaign.event(path, query, command)
                return
            if path == "/dialogue":
                if command["kind"] != "npc_say" or query.get("event") not in ("1", "2"):
                    raise ValueError("Invalid dialogue event")
                if (
                    self.dialogues.get(job, {}).get("event") == "closed"
                    and query["event"] == "1"
                ):
                    return
                self.dialogues[job] = {
                    "command_id": job,
                    "event": "opened" if query["event"] == "1" else "closed",
                    "received_at": time.time(),
                    "text": command["text"],
                    "agent_id": command["arguments"]["agent_id"],
                }
                return
            if command["kind"] != "scan_agents":
                raise ValueError("Agent event requires a scene census command")
            if (
                int(query["scene"]) != command["scene"]
                or int(query["session"]) != command["session"]
            ):
                raise ValueError("Scene/session changed during census")
            if job not in self.scans:
                if len(self.scans) >= 64:
                    del self.scans[next(iter(self.scans))]
                self.scans[job] = {
                    "command_id": job,
                    "created": time.time(),
                    "complete": False,
                    "scene_id": command["scene"],
                    "mission_session": command["session"],
                    "agents": {},
                    "expected_count": None,
                    "name_source": "module definitions; not live renamed agent names",
                }
            scan = self.scans[job]
            if path == "/agent":
                data = {
                    field: int(query[field])
                    for field in ("id", "troop", "team", "hp", "x", "y", "z", "player")
                }
                if not 0 <= data["id"] < 10000 or len(scan["agents"]) >= 64:
                    if data["id"] not in scan["agents"]:
                        raise ValueError("Agent census limit exceeded")
                scan["agents"][data["id"]] = {
                    "agent_id": data["id"],
                    "troop_id": data["troop"],
                    "name": self.catalog.get(str(data["troop"])),
                    "team": data["team"],
                    "hit_points": data["hp"],
                    "is_player": bool(data["player"]),
                    "position": {k: data[k] / 100 for k in ("x", "y", "z")},
                }
            elif path in ("/agents-end", "/agents_end"):
                count = int(query["count"])
                if not 0 <= count <= 64:
                    raise ValueError("Invalid census count")
                scan["expected_count"] = count
            else:
                raise ValueError("Unknown game event")
            scan["complete"] = len(scan["agents"]) == scan["expected_count"]

    def scan_result(self, job):
        with self.lock:
            if job not in self.scans:
                return {
                    "command_id": job,
                    "complete": False,
                    "reason": "No census received; refresh after a bridge restart",
                }
            scan = self.scans[job]
            return {
                **scan,
                "agents": list(scan["agents"].values()),
                "age_seconds": time.time() - scan["created"],
                "truncated": scan["expected_count"] == 64,
            }

    def dialogue_result(self, job):
        with self.lock:
            return dict(
                self.dialogues.get(job, {"command_id": job, "event": "not_observed"})
            )

    def snapshot(self):
        with self.lock:
            if self.state is None:
                return {
                    "connected": False,
                    "reason": "No game telemetry received",
                    "http_diagnostics": dict(self.diagnostics),
                }
            age = time.time() - self.state["received_at"]
            return {"connected": age < 15, "age_seconds": round(age, 3), **self.state}

    def capabilities(self):
        return {
            "transport": "vanilla game scripts over authenticated loopback HTTP",
            "desktop_dependency": False,
            "protocol": 2,
            "state": self.snapshot(),
            "implemented": {
                "message": "mission or campaign",
                "scene_agents": "single-player missions; 64 living humans max",
                "relocate_player": "debug teleport <=10m, not walking",
                "npc_say": "one non-battle dialogue line; no free-text reply yet",
                "campaign_exports": [
                    "party",
                    "prisoners",
                    "inventory",
                    "character",
                    "world_parties",
                    "quests",
                ],
            },
            "unimplemented": [
                "campaign travel orders",
                "trade",
                "recruitment",
                "quest actions",
                "combat orders",
                "multi-turn NPC dialogue",
                "free-text player input",
            ],
            "campaign_page_limit": 16,
            "module_instrumented_missions": self.module_catalog.get(
                "instrumented_missions", []
            ),
            "expected_integration_revision": 4,
            "polling": "revision 4 chains HTTP long-polls in paused game time",
            "caveats": [
                "Before revision 4, campaign polling pauses with game time",
                "HTTP failure stops the loop; game-time/mission triggers retry",
                "World census includes hidden parties (omniscient debug data)",
                "Labels come from module definitions, not live renamed entities",
            ],
        }


def make_server(store, token, host="127.0.0.1", port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args):
            pass  # Game URLs contain the token; never log them.

        def reply(self, status, body, content_type="application/json"):
            # Counts only; never retain request URLs containing the game token.
            key = f"{urlparse(self.path).path} {status}"
            with store.lock:
                if urlparse(self.path).path == "/poll":
                    store.diagnostics[key] = store.diagnostics.get(key, 0) + 1
            data = (
                json.dumps(body) if content_type == "application/json" else body
            ).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path in (
                "/poll",
                "/agent",
                "/agents-end",
                "/agents_end",
                "/dialogue",
                "/campaign-row",
                "/campaign-end",
            ):
                supplied = query.get("token", [""])[0]
            else:
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                self.reply(403, {"error": "Forbidden"})
                return
            try:
                if url.path == "/poll":
                    if any(len(v) != 1 for v in query.values()):
                        raise ValueError("Duplicate protocol field")
                    result = store.poll(
                        {k: v[0] for k, v in query.items()},
                        wait_seconds=0.25 if query.get("build") == ["4"] else 0,
                    )
                    self.reply(200, result, "text/plain")
                elif url.path in (
                    "/agent",
                    "/agents-end",
                    "/agents_end",
                    "/dialogue",
                    "/campaign-row",
                    "/campaign-end",
                ):
                    if any(len(v) != 1 for v in query.values()):
                        raise ValueError("Duplicate protocol field")
                    store.event(url.path, {k: v[0] for k, v in query.items()})
                    self.reply(200, "0|0|0|0|0|idle", "text/plain")
                elif url.path == "/api/state":
                    self.reply(200, store.snapshot())
                elif url.path == "/api/capabilities":
                    self.reply(200, store.capabilities())
                elif url.path.startswith("/api/campaign/"):
                    with store.lock:
                        self.reply(
                            200, store.campaign.result(int(url.path.rsplit("/", 1)[1]))
                        )
                elif url.path.startswith("/api/commands/"):
                    self.reply(200, store.command(int(url.path.rsplit("/", 1)[1])))
                elif url.path.startswith("/api/agents/"):
                    self.reply(200, store.scan_result(int(url.path.rsplit("/", 1)[1])))
                elif url.path.startswith("/api/dialogue/"):
                    self.reply(
                        200, store.dialogue_result(int(url.path.rsplit("/", 1)[1]))
                    )
                else:
                    self.reply(404, {"error": "Unknown endpoint"})
            except (ValueError, KeyError) as exc:
                self.reply(400, {"error": str(exc)})

        def do_POST(self):
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                self.reply(403, {"error": "Forbidden"})
                return
            if self.path != "/api/commands":
                self.reply(404, {"error": "Unknown endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2048:
                    raise ValueError("Invalid body length")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected an operation object")
                if not store.snapshot().get("connected"):
                    self.reply(
                        409, {"error": "Game is disconnected or telemetry is stale"}
                    )
                    return
                if set(data) == {"text"}:
                    self.reply(202, store.enqueue_operation("message", data))
                elif set(data) == {"operation", "arguments"}:
                    self.reply(
                        202,
                        store.enqueue_operation(data["operation"], data["arguments"]),
                    )
                else:
                    raise ValueError(
                        "Expected text or an allowlisted operation and arguments"
                    )
            except (ValueError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})

    return ThreadingHTTPServer((host, port), Handler)


def load_token(path):
    token = Path(path).read_text().strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("Expected a 64-character hexadecimal token")
    return token


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--create-token", action="store_true")
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    if args.create_token:
        with args.token_file.open("x") as f:
            f.write(secrets.token_hex(32))
        args.token_file.chmod(0o600)
    server = make_server(
        Store(
            args.database,
            json.loads(args.catalog.read_text()) if args.catalog else None,
        ),
        load_token(args.token_file),
        port=args.port,
    )
    print(f"Warband game bridge listening on 127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
