"""Validated multi-session application-host configuration and CLI."""

import argparse
import hashlib
import hmac
import json
import queue
import stat
import sys
import threading
import time
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType
from urllib.parse import unquote, urlparse

from bridge.application_extensions import built_in_extension_registry
from bridge.game_bridge import Store, make_server
from warband_agentic.agent_http import make_agent_server
from warband_agentic.contracts import (
    ContextRef,
    Evidence,
    EvidenceLevel,
    GameEvent,
    to_wire,
)
from warband_agentic.events import SemanticEventLog
from warband_agentic.extensions import (
    ExtensionRegistry,
    load_named_extension_entry_points,
)
from warband_agentic.proposals import MechanicalProposalBroker
from warband_agentic.voice import (
    SpeechRequest,
    VoiceDelivery,
    VoiceOutcome,
    VoiceState,
)
from warband_agentic.voice_http import VoiceHttpClient, VoiceHttpError

HOST_CONFIG_SCHEMA_V1 = "warband.agentic/host-config/v1"
HOST_CONFIG_SCHEMA = "warband.agentic/host-config/v2"
HOST_DIAGNOSTICS_SCHEMA = "warband.agentic/host-diagnostics/v1"
EXPECTED_PROTOCOL = 2
EXPECTED_INTEGRATION_REVISION = 16
_MECHANICAL_PROPOSAL_EVENT = "dialogue.mechanical-proposal-transition"


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
class VoiceHostPlan:
    endpoint: str
    token_file: Path
    token: str
    timeout_ms: int
    port: int


@dataclass(frozen=True, slots=True)
class AgentHostPlan:
    bridge: BridgeHostPlan
    control: ControlHostPlan
    events_database: Path
    sessions: tuple[SessionHostPlan, ...]
    module_protocol: int
    integration_revision: int
    extensions: ExtensionRegistry
    voice: VoiceHostPlan | None = None

    def diagnostics(self):
        voice = _voice_diagnostics(self.voice)
        automatic_sessions = [
            session.session_id
            for session in self.sessions
            if session.settings.get("automatic_voice") is not None
        ]
        if automatic_sessions:
            voice["automatic_sessions"] = automatic_sessions
        return {
            "schema": HOST_DIAGNOSTICS_SCHEMA,
            "status": "ready",
            "module": {
                "protocol": self.module_protocol,
                "integration_revision": self.integration_revision,
            },
            "bridge": {"host": "127.0.0.1", "port": self.bridge.port},
            "control": {"host": "127.0.0.1", "port": self.control.port},
            "voice": voice,
            "extensions": list(self.extensions.summaries()),
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


@dataclass(frozen=True, slots=True)
class BenchmarkHostBindings:
    """Trusted in-process resources for one validated faction benchmark."""

    store: object
    applications: object


@dataclass(frozen=True, slots=True)
class _AutomaticVoiceJob:
    session_id: str
    request: SpeechRequest
    context: ContextRef


_AUTOMATIC_VOICE_TERMINAL_STATES = {
    VoiceState.READY.value,
    VoiceState.PLAYED.value,
    VoiceState.SYNTHESIS_FAILED.value,
    VoiceState.PLAYBACK_FAILED.value,
    "failed",
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


def _voice_diagnostics(plan_or_client):
    if plan_or_client is None:
        return {"configured": False}
    endpoint = urlparse(plan_or_client.endpoint)
    return {
        "configured": True,
        "host": endpoint.hostname,
        "port": endpoint.port,
    }


def _speech_request_from_wire(value):
    fields = {
        "request_id",
        "text",
        "profile_id",
        "delivery",
        "speed",
        "output_format",
        "correlation_id",
        "schema",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Invalid automatic voice request in semantic event log")
    try:
        return SpeechRequest(
            value["request_id"],
            value["text"],
            value["profile_id"],
            VoiceDelivery(value["delivery"]),
            value["speed"],
            value["output_format"],
            value["correlation_id"],
            value["schema"],
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Invalid automatic voice request in semantic event log"
        ) from exc


def _automatic_voice_source_key(request_id, phase):
    digest = hashlib.sha256(request_id.encode()).hexdigest()
    return f"automatic-voice:{digest}:{phase}"


def _mechanical_proposal_source_key(proposal_id, transition):
    digest = hashlib.sha256(f"{proposal_id}\x00{transition}".encode()).hexdigest()
    return f"mechanical-proposal:{digest}"


def _voice_endpoint(value):
    if not isinstance(value, str):
        raise ValueError("voice endpoint must be a string")
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.path != "/v1/voice/speech"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("voice endpoint must be loopback /v1/voice/speech")
    _port(parsed.port, "voice endpoint port")
    return value, parsed.port


def _timeout_ms(value, label):
    if type(value) is not int or not 100 <= value <= 120_000:
        raise ValueError(f"{label} must be from 100 through 120000 ms")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f"{label} must be 1-128 characters")
    if not value.isprintable() or any(character in value for character in "/\\"):
        raise ValueError(f"{label} contains unsafe characters")
    return value


def _session_plan(base, value, index, extensions):
    if not isinstance(value, dict):
        raise ValueError(f"session {index} must be an object")
    common = {"kind", "session_id", "token_file", "port"}
    kind = value.get("kind")
    if not isinstance(kind, str):
        raise ValueError(f"session {index} has an unsupported kind")
    try:
        definition = extensions.application(kind)
    except ValueError as exc:
        raise ValueError(f"session {index} has an unsupported kind") from exc
    properties = set(definition.settings_schema.get("properties", {}))
    if not common <= set(value) or set(value) - common - properties:
        raise ValueError(f"session {index} fields do not match the host schema")
    token_file, token = _read_token(
        base, value["token_file"], f"session {index} token file"
    )
    settings = extensions.validate_settings(
        kind, {name: value[name] for name in properties if name in value}
    )
    return SessionHostPlan(
        kind,
        _identifier(value["session_id"], "session_id"),
        token_file,
        token,
        _port(value["port"], f"session {index} port"),
        settings,
    )


def load_agent_host_plan(path, extensions=None):
    if extensions is None:
        extensions = built_in_extension_registry()
    if not isinstance(extensions, ExtensionRegistry):
        raise TypeError("extensions must be an ExtensionRegistry")
    config_path = Path(path).resolve()
    config = _read_json(config_path, "host configuration", 256 * 1024)
    schema = config.get("schema")
    if schema == HOST_CONFIG_SCHEMA_V1:
        fields = ("schema", "bridge", "control", "events_database", "sessions")
    elif schema == HOST_CONFIG_SCHEMA:
        fields = (
            "schema",
            "bridge",
            "control",
            "voice",
            "events_database",
            "sessions",
        )
    else:
        raise ValueError("Unsupported host configuration schema")
    _exact_fields(config, fields, "host configuration")
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
    built_extensions = build.get("extensions")
    if not isinstance(built_extensions, list):
        raise ValueError("Module build manifest has no extension inventory")
    inventory = {}
    for item in built_extensions:
        if not isinstance(item, dict) or set(item) != {"extension_id", "version"}:
            raise ValueError("Module build extension inventory is malformed")
        extension_id, version = item["extension_id"], item["version"]
        if (
            not isinstance(extension_id, str)
            or not extension_id
            or not isinstance(version, str)
            or not version
            or extension_id in inventory
        ):
            raise ValueError("Module build extension inventory is malformed")
        inventory[extension_id] = version
    for requirement in extensions.required_module_extensions():
        extension_id = requirement["extension_id"]
        version = requirement["version"]
        if inventory.get(extension_id) != version:
            raise ValueError(
                f"Module does not provide required extension {extension_id} {version}"
            )
    expected_operations = [
        operation.manifest() for operation in extensions.compiled_operations()
    ]
    built_operations = build.get("compiled_operations", [])
    if (
        not isinstance(built_operations, list)
        or built_operations != expected_operations
    ):
        raise ValueError("Module compiled operation contract does not match this host")
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
    voice_plan = None
    if schema == HOST_CONFIG_SCHEMA:
        voice = config["voice"]
        _exact_fields(
            voice,
            ("endpoint", "token_file", "timeout_ms"),
            "voice configuration",
        )
        endpoint, voice_port = _voice_endpoint(voice["endpoint"])
        voice_token_file, voice_token = _read_token(
            base, voice["token_file"], "voice token file"
        )
        voice_plan = VoiceHostPlan(
            endpoint,
            voice_token_file,
            voice_token,
            _timeout_ms(voice["timeout_ms"], "voice timeout"),
            voice_port,
        )
    sessions = config["sessions"]
    if not isinstance(sessions, list) or not 1 <= len(sessions) <= 32:
        raise ValueError("sessions must contain 1-32 entries")
    plans = tuple(
        _session_plan(base, session, index, extensions)
        for index, session in enumerate(sessions)
    )
    if (
        any(plan.settings.get("automatic_voice") is not None for plan in plans)
        and voice_plan is None
    ):
        raise ValueError("automatic NPC voice requires host-config v2 voice service")
    session_ids = [plan.session_id for plan in plans]
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("session IDs must be unique")
    ports = [bridge_plan.port, control_plan.port, *(plan.port for plan in plans)]
    if voice_plan is not None:
        ports.append(voice_plan.port)
    if len(ports) != len(set(ports)):
        raise ValueError("host service ports must be unique")
    tokens = [bridge_plan.token, control_plan.token, *(plan.token for plan in plans)]
    if voice_plan is not None:
        tokens.append(voice_plan.token)
    if len(tokens) != len(set(tokens)):
        raise ValueError("host service tokens must be distinct")
    control_claims = {}
    for plan in plans:
        for claim in extensions.control_claims(plan.kind, plan.settings):
            if claim in control_claims:
                if claim[0] == "party":
                    raise ValueError("controlled parties overlap between sessions")
                if claim[0] == "agent":
                    raise ValueError("controlled agents overlap between sessions")
                if claim[0] == "player":
                    raise ValueError("only one session may control the player")
                raise ValueError("exclusive application ownership overlaps")
            control_claims[claim] = plan.session_id
    return AgentHostPlan(
        bridge_plan,
        control_plan,
        _database_path(base, config["events_database"], "semantic events database"),
        plans,
        build["protocol"],
        build["integration_revision"],
        extensions,
        voice_plan,
    )


class AgentApplicationHost:
    """Own one game bridge and the configured constrained session servers."""

    def __init__(self, plan, *, voice_client=None):
        if not isinstance(plan, AgentHostPlan):
            raise TypeError("plan must be an AgentHostPlan")
        if voice_client is not None and not isinstance(voice_client, VoiceHttpClient):
            raise TypeError("voice_client must be a VoiceHttpClient")
        if voice_client is not None and plan.voice is not None:
            raise ValueError("voice_client conflicts with configured voice service")
        self.plan = plan
        self._voice_client = voice_client
        if self._voice_client is None and plan.voice is not None:
            self._voice_client = VoiceHttpClient(
                plan.voice.endpoint,
                plan.voice.token,
                timeout_ms=plan.voice.timeout_ms,
            )
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
        self._voice_dispatch_queue = queue.Queue(maxsize=256)
        self._automatic_voice_dispatches = {}
        self._proposal_broker = MechanicalProposalBroker(
            transition_handler=self._persist_mechanical_proposal_transition
        )

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
                self._store = Store(
                    self.plan.bridge.database,
                    catalog,
                    compiled_operations=self.plan.extensions.compiled_operations(),
                )
                self._event_log = SemanticEventLog(self.plan.events_database)
                self._restore_mechanical_proposals()
                self._restore_automatic_voice_dispatches()
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
                if self._voice_client is not None:
                    voice_worker = threading.Thread(
                        target=self._run_voice_dispatches,
                        name="warband-agent-host-automatic-voice",
                        daemon=True,
                    )
                    self._threads.append(voice_worker)
                    voice_worker.start()
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
                application = self.plan.extensions.create(
                    session.kind,
                    self._store,
                    session.session_id,
                    self._event_log,
                    session.settings,
                )
                voice_policy = getattr(application, "host_voice_policy", None)
                if voice_policy is not None:
                    configure = getattr(
                        application, "set_observed_speech_handler", None
                    )
                    if not callable(configure):
                        raise TypeError(
                            "automatic voice application has no observation hook"
                        )
                    configure(
                        partial(
                            self._queue_automatic_voice,
                            session.session_id,
                            policy=voice_policy,
                        )
                    )
                configure_proposals = getattr(
                    application, "set_mechanical_proposal_broker", None
                )
                if callable(configure_proposals):
                    configure_proposals(self._proposal_broker)
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
            voice = _voice_diagnostics(self._voice_client)
            automatic_sessions = [
                session.session_id
                for session in self.plan.sessions
                if session.settings.get("automatic_voice") is not None
            ]
            if automatic_sessions:
                counts = {}
                for dispatch in self._automatic_voice_dispatches.values():
                    status_value = dispatch["status"]
                    counts[status_value] = counts.get(status_value, 0) + 1
                voice["automatic_sessions"] = automatic_sessions
                voice["automatic_dispatches"] = counts
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
            "voice": voice,
            "extensions": list(self.plan.extensions.summaries()),
            "sessions": sessions,
        }

    def _queue_automatic_voice(self, session_id, action_id, text, context, policy):
        if not isinstance(context, ContextRef):
            raise TypeError("automatic voice requires an observed action context")
        request = SpeechRequest(
            f"speech:{action_id}",
            text,
            policy["profile_id"],
            VoiceDelivery(policy["delivery"]),
            policy["speed"],
            "wav",
            action_id,
        )
        event = GameEvent(
            0,
            "voice.automatic-dispatch-requested",
            context,
            (),
            {
                "host_session_id": session_id,
                "request": to_wire(request),
            },
            Evidence(
                EvidenceLevel.ENGINE_OBSERVED,
                "NPC dialogue outcome reconciliation",
                "Warband observed the utterance before automatic voice queueing",
            ),
            time.time_ns() // 1_000_000,
            action_id,
        )
        with self._lock:
            if request.request_id in self._automatic_voice_dispatches:
                return
            if self._event_log is None:
                raise RuntimeError("semantic event log is unavailable")
            self._event_log.append(
                event,
                _automatic_voice_source_key(request.request_id, "requested"),
            )
            self._automatic_voice_dispatches[request.request_id] = {
                "session_id": session_id,
                "status": "queued",
                "correlation_id": action_id,
                "error_type": None,
            }
            job = _AutomaticVoiceJob(session_id, request, context)
        try:
            self._voice_dispatch_queue.put_nowait(job)
        except queue.Full:
            with self._lock:
                dispatch = self._automatic_voice_dispatches[request.request_id]
                dispatch["status"] = "queue-full"
                dispatch["error_type"] = "Full"

    def _run_voice_dispatches(self):
        while not self._stopping.is_set():
            try:
                job = self._voice_dispatch_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            request = job.request
            try:
                outcome = self._voice_client.speak(request)
                if not isinstance(outcome, VoiceOutcome):
                    raise TypeError("voice service returned an invalid outcome")
                status = outcome.state.value
                if status not in _AUTOMATIC_VOICE_TERMINAL_STATES:
                    raise TypeError("voice service returned a non-terminal outcome")
                error_type = None
            except Exception as exc:
                status = "failed"
                error_type = type(exc).__name__
            try:
                self._event_log.append(
                    GameEvent(
                        0,
                        "voice.automatic-dispatch-finished",
                        job.context,
                        (),
                        {
                            "host_session_id": job.session_id,
                            "request_id": request.request_id,
                            "status": status,
                            "error_type": error_type,
                        },
                        Evidence(
                            EvidenceLevel.DECLARED,
                            "host voice service",
                            "The automatic voice relay returned a terminal outcome",
                        ),
                        time.time_ns() // 1_000_000,
                        request.correlation_id,
                    ),
                    _automatic_voice_source_key(request.request_id, "finished"),
                )
            except Exception as exc:
                error_type = f"Outbox{type(exc).__name__}"
            with self._lock:
                dispatch = self._automatic_voice_dispatches[request.request_id]
                dispatch["status"] = status
                dispatch["error_type"] = error_type
            self._voice_dispatch_queue.task_done()

    def _restore_automatic_voice_dispatches(self):
        requested = {}
        finished = {}
        cursor = 0
        while True:
            page = self._event_log.read(cursor, 1000)
            for event in page.events:
                if event.event_type == "voice.automatic-dispatch-requested":
                    payload = event.payload
                    if set(payload) != {"host_session_id", "request"}:
                        raise ValueError("Invalid automatic voice outbox request")
                    session_id = payload["host_session_id"]
                    if not isinstance(session_id, str) or not session_id:
                        raise ValueError("Invalid automatic voice outbox request")
                    request = _speech_request_from_wire(to_wire(payload["request"]))
                    if request.correlation_id != event.cause_action_id:
                        raise ValueError("Automatic voice correlation is inconsistent")
                    job = _AutomaticVoiceJob(session_id, request, event.context)
                    previous = requested.setdefault(request.request_id, job)
                    if previous != job:
                        raise ValueError("Conflicting automatic voice outbox request")
                elif event.event_type == "voice.automatic-dispatch-finished":
                    payload = event.payload
                    if set(payload) != {
                        "host_session_id",
                        "request_id",
                        "status",
                        "error_type",
                    }:
                        raise ValueError("Invalid automatic voice outbox result")
                    request_id = payload["request_id"]
                    if (
                        not isinstance(payload["host_session_id"], str)
                        or not payload["host_session_id"]
                        or not isinstance(request_id, str)
                        or not request_id
                        or not isinstance(payload["status"], str)
                        or payload["status"] not in _AUTOMATIC_VOICE_TERMINAL_STATES
                        or payload["error_type"] is not None
                        and (
                            not isinstance(payload["error_type"], str)
                            or not payload["error_type"]
                        )
                    ):
                        raise ValueError("Invalid automatic voice outbox result")
                    result = {
                        "session_id": payload["host_session_id"],
                        "status": payload["status"],
                        "correlation_id": event.cause_action_id,
                        "error_type": payload["error_type"],
                    }
                    request_job = requested.get(request_id)
                    if (
                        request_job is None
                        or request_job.session_id != result["session_id"]
                        or request_job.request.correlation_id
                        != result["correlation_id"]
                        or request_job.context != event.context
                    ):
                        raise ValueError(
                            "Automatic voice outbox result does not match its request"
                        )
                    previous = finished.setdefault(request_id, result)
                    if previous != result:
                        raise ValueError("Conflicting automatic voice outbox result")
            if (
                page.next_sequence == cursor
                or page.next_sequence >= page.high_watermark
            ):
                break
            cursor = page.next_sequence
        for request_id, job in requested.items():
            if request_id in finished:
                self._automatic_voice_dispatches[request_id] = finished[request_id]
                continue
            if self._voice_client is None:
                raise ValueError(
                    "pending automatic voice outbox requires a voice service"
                )
            self._automatic_voice_dispatches[request_id] = {
                "session_id": job.session_id,
                "status": "queued",
                "correlation_id": job.request.correlation_id,
                "error_type": None,
            }
            self._voice_dispatch_queue.put_nowait(job)

    def _persist_mechanical_proposal_transition(
        self, transition, proposal, context, outcome
    ):
        if not isinstance(transition, str) or not transition:
            raise ValueError("mechanical proposal transition must be non-empty")
        if not isinstance(context, ContextRef):
            raise TypeError("mechanical proposal transition needs a context")
        if not isinstance(proposal, dict):
            raise TypeError("mechanical proposal transition needs a manifest")
        with self._lock:
            if self._event_log is None:
                raise RuntimeError("semantic event log is unavailable")
            event_log = self._event_log
        source_session_id = proposal.get("source_session_id")
        proposal_id = proposal.get("proposal_id")
        if not isinstance(source_session_id, str) or not source_session_id:
            raise ValueError("mechanical proposal source session is invalid")
        if not isinstance(proposal_id, str) or not proposal_id:
            raise ValueError("mechanical proposal ID is invalid")
        level = (
            EvidenceLevel.ENGINE_OBSERVED
            if transition == "committed"
            else EvidenceLevel.DECLARED
        )
        event_log.append(
            GameEvent(
                0,
                _MECHANICAL_PROPOSAL_EVENT,
                context,
                (),
                {
                    "host_session_id": source_session_id,
                    "transition": transition,
                    "proposal": proposal,
                    "outcome": to_wire(outcome) if outcome is not None else None,
                },
                Evidence(
                    level,
                    "mechanical proposal broker",
                    "The host recorded a fail-closed proposal lifecycle snapshot",
                ),
                time.time_ns() // 1_000_000,
                proposal["source_action_id"],
            ),
            _mechanical_proposal_source_key(proposal_id, transition),
        )

    def _restore_mechanical_proposals(self):
        latest = {}
        cursor = 0
        while True:
            page = self._event_log.read(cursor, 1000)
            for event in page.events:
                if event.event_type != _MECHANICAL_PROPOSAL_EVENT:
                    continue
                payload = to_wire(event.payload)
                if not isinstance(payload, dict) or set(payload) != {
                    "host_session_id",
                    "transition",
                    "proposal",
                    "outcome",
                }:
                    raise ValueError("Invalid mechanical proposal journal event")
                proposal = payload["proposal"]
                if (
                    not isinstance(proposal, dict)
                    or payload["host_session_id"] != proposal.get("source_session_id")
                    or not isinstance(payload["transition"], str)
                    or not payload["transition"]
                    or payload["outcome"] is not None
                    and not isinstance(payload["outcome"], dict)
                ):
                    raise ValueError("Invalid mechanical proposal journal event")
                proposal_id = proposal.get("proposal_id")
                if not isinstance(proposal_id, str) or not proposal_id:
                    raise ValueError("Invalid mechanical proposal journal event")
                latest[proposal_id] = proposal
            if page.next_sequence >= page.high_watermark:
                break
            cursor = page.next_sequence
        self._proposal_broker.restore(latest.values())

    def automatic_voice_dispatches(self):
        with self._lock:
            return {
                request_id: dict(dispatch)
                for request_id, dispatch in self._automatic_voice_dispatches.items()
            }

    def extension_catalog(self):
        return self.plan.extensions.catalog()

    def benchmark_bindings(self, participant_sessions):
        """Return Store/application references for explicit faction sessions."""
        if (
            not isinstance(participant_sessions, dict)
            or not 2 <= len(participant_sessions) <= 16
        ):
            raise ValueError("participant_sessions must contain 2-16 factions")
        normalized = {}
        seen_sessions = set()
        for faction_id in sorted(participant_sessions):
            session_id = participant_sessions[faction_id]
            if type(faction_id) is not int or not 0 <= faction_id < 1_000_000:
                raise ValueError("benchmark faction IDs must be bounded integers")
            _identifier(session_id, "benchmark session_id")
            if session_id in seen_sessions:
                raise ValueError("benchmark sessions must be unique")
            normalized[faction_id] = session_id
            seen_sessions.add(session_id)
        with self._lock:
            if self._state != "ready" or self._store is None:
                raise RuntimeError("application host is not ready for a benchmark")
            applications = {}
            for faction_id, session_id in normalized.items():
                try:
                    application = self._applications[session_id]
                except KeyError as exc:
                    raise ValueError("benchmark session is not hosted") from exc
                if getattr(application, "faction_id", None) != faction_id:
                    raise ValueError(
                        "benchmark session application does not match its faction"
                    )
                applications[faction_id] = application
            return BenchmarkHostBindings(
                self._store,
                MappingProxyType(applications),
            )

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

    def receive_player_utterance(self, session_id, utterance_id, text):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("application sessions are not ready")
            try:
                application = self._applications[session_id]
            except KeyError as exc:
                raise KeyError("Unknown application session") from exc
        receive = getattr(application, "receive_player_utterance", None)
        if not callable(receive):
            raise ValueError("application session does not accept player utterances")
        return receive(utterance_id, text)

    def offer_mechanical_proposal(
        self,
        source_session_id,
        title,
        target_session_id,
        affordance_token,
        arguments,
        required_acceptors,
    ):
        """Expose one exact target affordance as an NPC-visible safe option."""
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("application sessions are not ready")
            try:
                source_application = self._applications[source_session_id]
                target_application = self._applications[target_session_id]
            except KeyError as exc:
                raise KeyError("Unknown application session") from exc
        begin = getattr(source_application, "begin_mechanical_proposal_update", None)
        refresh = getattr(source_application, "refresh_mechanical_proposals", None)
        target_session = getattr(target_application, "session", None)
        if not callable(begin) or not callable(refresh):
            raise ValueError("source application does not support mechanical proposals")
        if target_session is None:
            raise ValueError("target application has no constrained session")
        source_context = begin()
        option = self._proposal_broker.offer(
            source_session_id=source_session_id,
            source_context=source_context,
            title=title,
            target_session_id=target_session_id,
            target_session=target_session,
            affordance_token=affordance_token,
            arguments=arguments,
            required_acceptors=required_acceptors,
        )
        refresh()
        return {
            "schema": "warband.agentic/mechanical-proposal-option/v1",
            "source_session_id": source_session_id,
            "target_session_id": target_session_id,
            **option,
        }

    def mechanical_proposals(self, source_session_id):
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("application sessions are not ready")
            if source_session_id not in self._applications:
                raise KeyError("Unknown application session")
        return {
            "schema": "warband.agentic/mechanical-proposals/v1",
            "source_session_id": source_session_id,
            "proposals": list(self._proposal_broker.proposals(source_session_id)),
        }

    def mechanical_proposal(self, proposal_id):
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("application sessions are not ready")
        return {
            "schema": "warband.agentic/mechanical-proposal/v1",
            **self._proposal_broker.proposal(proposal_id),
        }

    def decide_mechanical_proposal(self, proposal_id, acceptor_id, accept):
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("application sessions are not ready")
        return {
            "schema": "warband.agentic/mechanical-proposal/v1",
            **self._proposal_broker.decide(proposal_id, acceptor_id, accept=accept),
        }

    def execute_mechanical_proposal(self, proposal_id):
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("application sessions are not ready")
        outcome = self._proposal_broker.execute(proposal_id)
        return {
            "schema": "warband.agentic/mechanical-proposal-execution/v1",
            "proposal": self._proposal_broker.proposal(proposal_id),
            "outcome": to_wire(outcome),
        }

    def prepare_voice_request(
        self,
        session_id,
        action_request_id,
        profile_id,
        delivery,
        speed,
    ):
        request = self._create_voice_request(
            session_id,
            action_request_id,
            profile_id,
            delivery,
            speed,
        )
        return to_wire(request)

    def dispatch_voice_request(
        self,
        session_id,
        action_request_id,
        profile_id,
        delivery,
        speed,
    ):
        if self._voice_client is None:
            raise RuntimeError("application host has no voice service configured")
        request = self._create_voice_request(
            session_id,
            action_request_id,
            profile_id,
            delivery,
            speed,
        )
        outcome = self._voice_client.speak(request)
        if not isinstance(outcome, VoiceOutcome):
            raise TypeError("voice service returned an invalid outcome")
        return {
            "schema": "warband.agentic/host-voice-dispatch/v1",
            "session_id": session_id,
            "request_id": outcome.request_id,
            "correlation_id": outcome.correlation_id,
            "state": outcome.state.value,
            "audio_id": outcome.audio_id,
            "error": outcome.error,
        }

    def _create_voice_request(
        self,
        session_id,
        action_request_id,
        profile_id,
        delivery,
        speed,
    ):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be a non-empty string")
        with self._lock:
            if self._state != "ready":
                raise RuntimeError("application sessions are not ready")
            try:
                application = self._applications[session_id]
            except KeyError as exc:
                raise KeyError("Unknown application session") from exc
        create = getattr(application, "voice_request", None)
        if not callable(create):
            raise ValueError("application session does not support voice handoff")
        request = create(
            action_request_id,
            profile_id,
            delivery=VoiceDelivery(delivery),
            speed=speed,
        )
        if not isinstance(request, SpeechRequest):
            raise TypeError("application returned an invalid voice request")
        return request

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

        def read_json(self, label, *, maximum=8192):
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= maximum:
                raise ValueError(f"{label} body must contain 1-{maximum} bytes")
            try:
                return json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"{label} body must be JSON") from exc

        def do_GET(self):
            if not self.authenticate():
                return
            path = urlparse(self.path).path
            if path == "/v1/host/diagnostics":
                self.reply(200, host.runtime_diagnostics())
            elif path == "/v1/host/extensions":
                self.reply(200, host.extension_catalog())
            elif path.startswith("/v1/host/sessions/") and path.endswith("/proposals"):
                prefix = "/v1/host/sessions/"
                suffix = "/proposals"
                session_id = unquote(path[len(prefix) : -len(suffix)])
                try:
                    self.reply(200, host.mechanical_proposals(session_id))
                except KeyError as exc:
                    self.reply(404, {"error": str(exc)})
                except RuntimeError as exc:
                    self.reply(409, {"error": str(exc)})
                except (TypeError, ValueError) as exc:
                    self.reply(400, {"error": str(exc)})
            elif path.startswith("/v1/host/proposals/"):
                proposal_id = unquote(path.removeprefix("/v1/host/proposals/"))
                try:
                    self.reply(200, host.mechanical_proposal(proposal_id))
                except RuntimeError as exc:
                    self.reply(409, {"error": str(exc)})
                except (TypeError, ValueError) as exc:
                    self.reply(404, {"error": str(exc)})
            else:
                self.reply(404, {"error": "Unknown endpoint"})

        def do_POST(self):
            if not self.authenticate():
                return
            path = urlparse(self.path).path
            prefix = "/v1/host/sessions/"
            try:
                status = 202
                if path.startswith("/v1/host/proposals/") and path.endswith(
                    "/decisions"
                ):
                    proposal_id = unquote(
                        path[len("/v1/host/proposals/") : -len("/decisions")]
                    )
                    body = self.read_json("Proposal decision", maximum=2048)
                    if not isinstance(body, dict) or set(body) != {
                        "acceptor_id",
                        "accept",
                    }:
                        raise ValueError("Proposal decision fields do not match")
                    result = host.decide_mechanical_proposal(
                        proposal_id, body["acceptor_id"], body["accept"]
                    )
                    status = 200
                elif path.startswith("/v1/host/proposals/") and path.endswith(
                    "/execute"
                ):
                    proposal_id = unquote(
                        path[len("/v1/host/proposals/") : -len("/execute")]
                    )
                    if int(self.headers.get("Content-Length", "0")) != 0:
                        raise ValueError(
                            "Proposal execution request body must be empty"
                        )
                    result = host.execute_mechanical_proposal(proposal_id)
                    status = 200
                elif not path.startswith(prefix):
                    self.reply(404, {"error": "Unknown endpoint"})
                    return
                elif path.endswith("/proposal-options"):
                    suffix = "/proposal-options"
                    session_id = unquote(path[len(prefix) : -len(suffix)])
                    body = self.read_json("Proposal option")
                    if not isinstance(body, dict) or set(body) != {
                        "title",
                        "target_session_id",
                        "affordance_token",
                        "arguments",
                        "required_acceptors",
                    }:
                        raise ValueError("Proposal option fields do not match")
                    result = host.offer_mechanical_proposal(
                        session_id,
                        body["title"],
                        body["target_session_id"],
                        body["affordance_token"],
                        body["arguments"],
                        body["required_acceptors"],
                    )
                    status = 201
                elif path.endswith("/refresh"):
                    suffix = "/refresh"
                    session_id = unquote(path[len(prefix) : -len(suffix)])
                    if int(self.headers.get("Content-Length", "0")) != 0:
                        raise ValueError("Refresh request body must be empty")
                    result = host.refresh(session_id)
                elif path.endswith("/utterances"):
                    suffix = "/utterances"
                    session_id = unquote(path[len(prefix) : -len(suffix)])
                    body = self.read_json("Player utterance", maximum=2048)
                    if not isinstance(body, dict) or set(body) != {
                        "utterance_id",
                        "text",
                    }:
                        raise ValueError("Player utterance fields do not match")
                    result = host.receive_player_utterance(
                        session_id,
                        body["utterance_id"],
                        body["text"],
                    )
                elif path.endswith(("/voice-requests", "/voice-dispatches")):
                    dispatch = path.endswith("/voice-dispatches")
                    suffix = "/voice-dispatches" if dispatch else "/voice-requests"
                    session_id = unquote(path[len(prefix) : -len(suffix)])
                    body = self.read_json("Voice handoff", maximum=2048)
                    if not isinstance(body, dict) or set(body) != {
                        "action_request_id",
                        "profile_id",
                        "delivery",
                        "speed",
                    }:
                        raise ValueError("Voice handoff fields do not match")
                    method = (
                        host.dispatch_voice_request
                        if dispatch
                        else host.prepare_voice_request
                    )
                    result = method(
                        session_id,
                        body["action_request_id"],
                        body["profile_id"],
                        body["delivery"],
                        body["speed"],
                    )
                    status = 200
                else:
                    self.reply(404, {"error": "Unknown endpoint"})
                    return
                self.reply(status, result)
            except KeyError as exc:
                self.reply(404, {"error": str(exc)})
            except VoiceHttpError as exc:
                self.reply(502, {"error": str(exc)})
            except RuntimeError as exc:
                self.reply(409, {"error": str(exc)})
            except (TypeError, ValueError) as exc:
                self.reply(400, {"error": str(exc)})

    return ThreadingHTTPServer((bind_host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--extension", action="append", default=[])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        extensions = built_in_extension_registry()
        load_named_extension_entry_points(extensions, args.extension)
        plan = load_agent_host_plan(args.config, extensions)
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
