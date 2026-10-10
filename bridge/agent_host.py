"""Validated multi-session application-host configuration and CLI."""

import argparse
import hmac
import json
import stat
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from bridge.game_bridge import Store, make_server
from bridge.native_faction_agent_app import (
    NativeFactionAgentApplication,
    PartyOrderOption,
)
from bridge.native_menu_agent_app import NativeMenuAgentApplication
from bridge.native_npc_speech_app import NativeNpcSpeechApplication
from warband_agentic.agent_http import make_agent_server
from warband_agentic.events import SemanticEventLog

HOST_CONFIG_SCHEMA = "warband.agentic/host-config/v1"
HOST_DIAGNOSTICS_SCHEMA = "warband.agentic/host-diagnostics/v1"
EXPECTED_PROTOCOL = 2
EXPECTED_INTEGRATION_REVISION = 16


@dataclass(frozen=True, slots=True)
class BridgeHostPlan:
    database: Path
    catalog: Path
    build_manifest: Path
    token_file: Path
    token: str
    port: int


@dataclass(frozen=True, slots=True)
class SessionHostPlan:
    kind: str
    session_id: str
    token_file: Path
    token: str
    port: int
    settings: dict


@dataclass(frozen=True, slots=True)
class ControlHostPlan:
    token_file: Path
    token: str
    port: int


@dataclass(frozen=True, slots=True)
class AgentHostPlan:
    bridge: BridgeHostPlan
    control: ControlHostPlan
    events_database: Path
    sessions: tuple[SessionHostPlan, ...]
    module_protocol: int
    integration_revision: int

    def diagnostics(self):
        return {
            "schema": HOST_DIAGNOSTICS_SCHEMA,
            "status": "ready",
            "module": {
                "protocol": self.module_protocol,
                "integration_revision": self.integration_revision,
            },
            "bridge": {"host": "127.0.0.1", "port": self.bridge.port},
            "control": {"host": "127.0.0.1", "port": self.control.port},
            "sessions": [
                {
                    "kind": session.kind,
                    "session_id": session.session_id,
                    "host": "127.0.0.1",
                    "port": session.port,
                }
                for session in self.sessions
            ],
        }


def _exact_fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{label} fields do not match the host schema")


def _read_json(path, label, limit):
    try:
        if path.stat().st_size > limit:
            raise ValueError(f"{label} exceeds its size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _resolve_path(base, value, label):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be a non-empty path")
    path = Path(value)
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _database_path(base, value, label):
    path = _resolve_path(base, value, label)
    if not path.parent.is_dir():
        raise ValueError(f"{label} parent directory does not exist")
    if path.exists() and not path.is_file():
        raise ValueError(f"{label} is not a regular file")
    return path


def _read_token(base, value, label):
    path = _resolve_path(base, value, label)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"Cannot read {label}") from exc
    if mode & 0o077:
        raise ValueError(f"{label} must not be accessible by group or other users")
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError(f"{label} must contain 64 lowercase hexadecimal characters")
    return path, token


def _port(value, label):
    if type(value) is not int or not 1024 <= value <= 65535:
        raise ValueError(f"{label} must be an unprivileged TCP port")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f"{label} must be 1-128 characters")
    if not value.isprintable() or any(character in value for character in "/\\"):
        raise ValueError(f"{label} contains unsafe characters")
    return value


def _entity_id(value, label):
    if type(value) is not int or not 0 <= value < 1_000_000:
        raise ValueError(f"{label} must be a bounded non-negative integer")
    return value


def _session_plan(base, value, index):
    if not isinstance(value, dict):
        raise ValueError(f"session {index} must be an object")
    common = {"kind", "session_id", "token_file", "port"}
    kind = value.get("kind")
    specific = {
        "native-menu": set(),
        "native-faction": {
            "faction_id",
            "controlled_party_ids",
            "order_options",
        },
        "native-npc-speech": {"agent_id"},
    }
    if kind not in specific:
        raise ValueError(f"session {index} has an unsupported kind")
    _exact_fields(value, common | specific[kind], f"session {index}")
    token_file, token = _read_token(
        base, value["token_file"], f"session {index} token file"
    )
    settings = {}
    if kind == "native-faction":
        faction_id = _entity_id(value["faction_id"], "faction_id")
        parties = value["controlled_party_ids"]
        if not isinstance(parties, list) or not parties:
            raise ValueError("controlled_party_ids must be a non-empty list")
        controlled = tuple(
            _entity_id(party_id, "controlled party ID") for party_id in parties
        )
        if len(controlled) != len(set(controlled)):
            raise ValueError("controlled_party_ids must be unique")
        options = value["order_options"]
        if not isinstance(options, list) or not options:
            raise ValueError("order_options must be a non-empty list")
        parsed_options = []
        for option in options:
            _exact_fields(
                option,
                ("party_id", "order", "target_party_id", "title"),
                "party order option",
            )
            parsed = PartyOrderOption(
                option["party_id"],
                option["order"],
                option["target_party_id"],
                option["title"],
            )
            if parsed.party_id not in controlled:
                raise ValueError("party order option uses an uncontrolled party")
            parsed_options.append(parsed)
        settings = {
            "faction_id": faction_id,
            "controlled_party_ids": controlled,
            "order_options": tuple(parsed_options),
        }
    elif kind == "native-npc-speech":
        settings = {"agent_id": _entity_id(value["agent_id"], "agent_id")}
    return SessionHostPlan(
        kind,
        _identifier(value["session_id"], "session_id"),
        token_file,
        token,
        _port(value["port"], f"session {index} port"),
        settings,
    )


def load_agent_host_plan(path):
    config_path = Path(path).resolve()
    config = _read_json(config_path, "host configuration", 256 * 1024)
    _exact_fields(
        config,
        ("schema", "bridge", "control", "events_database", "sessions"),
        "host configuration",
    )
    if config["schema"] != HOST_CONFIG_SCHEMA:
        raise ValueError("Unsupported host configuration schema")
    bridge = config["bridge"]
    _exact_fields(
        bridge,
        (
            "database",
            "catalog",
            "build_manifest",
            "token_file",
            "port",
        ),
        "bridge configuration",
    )
    base = config_path.parent
    catalog_path = _resolve_path(base, bridge["catalog"], "catalog")
    _read_json(catalog_path, "module catalog", 32 * 1024 * 1024)
    build_path = _resolve_path(base, bridge["build_manifest"], "build manifest")
    build = _read_json(build_path, "module build manifest", 256 * 1024)
    if build.get("protocol") != EXPECTED_PROTOCOL:
        raise ValueError("Module protocol does not match this host")
    if build.get("integration_revision") != EXPECTED_INTEGRATION_REVISION:
        raise ValueError("Module integration revision does not match this host")
    bridge_token_file, bridge_token = _read_token(
        base, bridge["token_file"], "bridge token file"
    )
    bridge_plan = BridgeHostPlan(
        _database_path(base, bridge["database"], "bridge database"),
        catalog_path,
        build_path,
        bridge_token_file,
        bridge_token,
        _port(bridge["port"], "bridge port"),
    )
    control = config["control"]
    _exact_fields(control, ("token_file", "port"), "control configuration")
    control_token_file, control_token = _read_token(
        base, control["token_file"], "control token file"
    )
    control_plan = ControlHostPlan(
        control_token_file,
        control_token,
        _port(control["port"], "control port"),
    )
    sessions = config["sessions"]
    if not isinstance(sessions, list) or not 1 <= len(sessions) <= 32:
        raise ValueError("sessions must contain 1-32 entries")
    plans = tuple(
        _session_plan(base, session, index)
        for index, session in enumerate(sessions)
    )
    session_ids = [plan.session_id for plan in plans]
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("session IDs must be unique")
    ports = [bridge_plan.port, control_plan.port, *(plan.port for plan in plans)]
    if len(ports) != len(set(ports)):
        raise ValueError("bridge and session ports must be unique")
    tokens = [bridge_plan.token, control_plan.token, *(plan.token for plan in plans)]
    if len(tokens) != len(set(tokens)):
        raise ValueError("bridge and session tokens must be distinct")
    menu_count = sum(plan.kind == "native-menu" for plan in plans)
    if menu_count > 1:
        raise ValueError("only one native-menu session may control the player")
    controlled_parties = []
    controlled_agents = []
    for plan in plans:
        controlled_parties.extend(plan.settings.get("controlled_party_ids", ()))
        if "agent_id" in plan.settings:
            controlled_agents.append(plan.settings["agent_id"])
    if len(controlled_parties) != len(set(controlled_parties)):
        raise ValueError("controlled parties overlap between sessions")
    if len(controlled_agents) != len(set(controlled_agents)):
        raise ValueError("controlled agents overlap between sessions")
    return AgentHostPlan(
        bridge_plan,
        control_plan,
        _database_path(
            base, config["events_database"], "semantic events database"
        ),
        plans,
        build["protocol"],
        build["integration_revision"],
    )


class AgentApplicationHost:
    """Own one game bridge and the configured constrained session servers."""

    def __init__(self, plan):
        if not isinstance(plan, AgentHostPlan):
            raise TypeError("plan must be an AgentHostPlan")
        self.plan = plan
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._state = "created"
        self._store = None
        self._event_log = None
        self._bridge_server = None
        self._control_server = None
        self._agent_servers = []
        self._applications = {}
        self._threads = []
        self._failure = None

    def start(self):
        with self._lock:
            if self._state != "created":
                raise RuntimeError("application host was already started")
            try:
                catalog = _read_json(
                    self.plan.bridge.catalog,
                    "module catalog",
                    32 * 1024 * 1024,
                )
                self._store = Store(self.plan.bridge.database, catalog)
                self._event_log = SemanticEventLog(self.plan.events_database)
                self._bridge_server = make_server(
                    self._store,
                    self.plan.bridge.token,
                    port=self.plan.bridge.port,
                )
                self._control_server = make_host_control_server(
                    self,
                    self.plan.control.token,
                    port=self.plan.control.port,
                )
                self._start_server_thread(self._bridge_server, "bridge")
                self._start_server_thread(self._control_server, "control")
                self._state = "waiting-for-game"
                activation = threading.Thread(
                    target=self._activate_after_connection,
                    name="warband-agent-host-activation",
                    daemon=True,
                )
                self._threads.append(activation)
                activation.start()
            except Exception:
                for server in (self._bridge_server, self._control_server):
                    if server is not None:
                        server.server_close()
                self._close_resources()
                self._state = "failed"
                raise
        return self

    def _start_server_thread(self, server, label):
        thread = threading.Thread(
            target=server.serve_forever,
            name=f"warband-agent-host-{label}",
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()

    def _activate_after_connection(self):
        while not self._stopping.wait(0.05):
            try:
                snapshot = self._store.snapshot()
                if snapshot.get("connected") and snapshot.get("protocol") == 2:
                    self._activate_sessions()
                    return
            except Exception as exc:
                with self._lock:
                    self._failure = exc
                    self._state = "failed"
                    self._ready.set()
                return

    def _activate_sessions(self):
        servers = []
        applications = {}
        try:
            for session in self.plan.sessions:
                if session.kind == "native-menu":
                    application = NativeMenuAgentApplication(
                        self._store,
                        session.session_id,
                        event_log=self._event_log,
                    )
                elif session.kind == "native-faction":
                    application = NativeFactionAgentApplication(
                        self._store,
                        session.session_id,
                        event_log=self._event_log,
                        **session.settings,
                    )
                else:
                    application = NativeNpcSpeechApplication(
                        self._store,
                        session.session_id,
                        event_log=self._event_log,
                        **session.settings,
                    )
                server = make_agent_server(
                    application.session,
                    session.token,
                    port=session.port,
                )
                servers.append((session, server))
                applications[session.session_id] = application
            with self._lock:
                if self._stopping.is_set():
                    for _, server in servers:
                        server.server_close()
                    return
                self._applications = applications
                for session, server in servers:
                    self._agent_servers.append(server)
                    self._start_server_thread(server, session.session_id)
                self._state = "ready"
                self._ready.set()
        except Exception as exc:
            for _, server in servers:
                server.server_close()
            with self._lock:
                self._failure = exc
                self._state = "failed"
                self._ready.set()

    def wait_until_ready(self, timeout=None):
        if self._state == "created":
            raise RuntimeError("application host has not started")
        self._ready.wait(timeout)
        with self._lock:
            return self._state == "ready"

    def runtime_diagnostics(self):
        with self._lock:
            status = self._state
            sessions = [
                {
                    "kind": plan.kind,
                    "session_id": plan.session_id,
                    "host": "127.0.0.1",
                    "port": plan.port,
                    "status": (
                        "running"
                        if plan.session_id in self._applications
                        else "pending"
                    ),
                }
                for plan in self.plan.sessions
            ]
        return {
            "schema": HOST_DIAGNOSTICS_SCHEMA,
            "status": status,
            "module": {
                "protocol": self.plan.module_protocol,
                "integration_revision": self.plan.integration_revision,
            },
            "bridge": {
                "host": "127.0.0.1",
                "port": self.plan.bridge.port,
                "status": "running"
                if status in ("waiting-for-game", "ready")
                else status,
            },
            "control": {
                "host": "127.0.0.1",
                "port": self.plan.control.port,
                "status": "running"
                if status in ("waiting-for-game", "ready")
                else status,
            },
            "sessions": sessions,
        }

    def refresh(self, session_id):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("application sessions are not ready")
            try:
                application = self._applications[session_id]
            except KeyError as exc:
                raise KeyError("Unknown application session") from exc
        refresh = getattr(application, "queue_observation_refresh", None)
        if not callable(refresh):
            raise ValueError("application session does not support explicit refresh")
        jobs = refresh()
        if type(jobs) is int:
            count = 1
        elif isinstance(jobs, dict):
            count = len(jobs)
        else:
            raise TypeError("application returned an invalid refresh result")
        return {
            "schema": "warband.agentic/host-refresh/v1",
            "session_id": session_id,
            "status": "queued",
            "job_count": count,
        }

    def stop(self):
        with self._lock:
            if self._state == "stopped":
                return
            self._stopping.set()
            servers = [*self._agent_servers]
            if self._bridge_server is not None:
                servers.append(self._bridge_server)
            if self._control_server is not None:
                servers.append(self._control_server)
            self._state = "stopping"
        for server in servers:
            try:
                server.shutdown()
            finally:
                server.server_close()
        current = threading.current_thread()
        for thread in tuple(self._threads):
            if thread is not current:
                thread.join(timeout=2)
        with self._lock:
            self._close_resources()
            self._applications = {}
            self._state = "stopped"
            self._ready.set()

    def _close_resources(self):
        if self._event_log is not None:
            self._event_log.close()
            self._event_log = None
        if self._store is not None:
            self._store.db.close()
            self._store = None

    def serve_forever(self):
        if self._state == "created":
            self.start()
        try:
            while not self._stopping.wait(0.5):
                with self._lock:
                    if self._state == "failed":
                        raise RuntimeError(
                            f"Application host activation failed: "
                            f"{type(self._failure).__name__}"
                        )
        finally:
            self.stop()


def make_host_control_server(host, token, bind_host="127.0.0.1", port=8879):
    if not isinstance(host, AgentApplicationHost):
        raise TypeError("host must be an AgentApplicationHost")
    if not isinstance(token, str) or len(token) != 64:
        raise ValueError("control token must contain 64 characters")
    if bind_host != "127.0.0.1":
        raise ValueError("host control must bind to IPv4 loopback")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args):
            pass

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def authenticate(self):
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if hmac.compare_digest(supplied.encode(), token.encode()):
                return True
            self.reply(403, {"error": "Forbidden"})
            return False

        def do_GET(self):
            if not self.authenticate():
                return
            if urlparse(self.path).path == "/v1/host/diagnostics":
                self.reply(200, host.runtime_diagnostics())
            else:
                self.reply(404, {"error": "Unknown endpoint"})

        def do_POST(self):
            if not self.authenticate():
                return
            path = urlparse(self.path).path
            prefix = "/v1/host/sessions/"
            suffix = "/refresh"
            if not path.startswith(prefix) or not path.endswith(suffix):
                self.reply(404, {"error": "Unknown endpoint"})
                return
            session_id = unquote(path[len(prefix) : -len(suffix)])
            try:
                if int(self.headers.get("Content-Length", "0")) != 0:
                    raise ValueError("Refresh request body must be empty")
                self.reply(202, host.refresh(session_id))
            except KeyError as exc:
                self.reply(404, {"error": str(exc)})
            except RuntimeError as exc:
                self.reply(409, {"error": str(exc)})
            except (TypeError, ValueError) as exc:
                self.reply(400, {"error": str(exc)})

    return ThreadingHTTPServer((bind_host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = load_agent_host_plan(args.config)
        if args.check:
            json.dump(plan.diagnostics(), sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        else:
            host = AgentApplicationHost(plan)
            host.start()
            json.dump(host.runtime_diagnostics(), sys.stdout, sort_keys=True)
            sys.stdout.write("\n")
            sys.stdout.flush()
            try:
                host.serve_forever()
            except KeyboardInterrupt:
                pass
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
