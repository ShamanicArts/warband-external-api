"""Durable, transport-neutral semantic event history."""

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from warband_agentic.contracts import (
    ActorKind,
    ActorRef,
    ContextKind,
    ContextRef,
    Evidence,
    EvidenceLevel,
    GameEvent,
    to_wire,
)

EVENT_STORE_SCHEMA_VERSION = 1
_TERMINAL_COMMAND_STATES = {"acknowledged", "rejected", "expired", "interrupted"}


def _exact_fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"Invalid persisted {label} fields")


def game_event_from_wire(value):
    """Rebuild and validate a :class:`GameEvent` from persisted JSON data."""
    _exact_fields(
        value,
        (
            "sequence",
            "event_type",
            "context",
            "subjects",
            "payload",
            "evidence",
            "occurred_at_ms",
            "cause_action_id",
            "schema",
        ),
        "event",
    )
    context = value["context"]
    _exact_fields(
        context,
        ("kind", "scope_id", "revision", "session_id", "game_time"),
        "context",
    )
    evidence = value["evidence"]
    _exact_fields(
        evidence,
        ("level", "source", "detail", "event_sequence"),
        "evidence",
    )
    if not isinstance(value["subjects"], list):
        raise ValueError("Invalid persisted event subjects")
    subjects = []
    for subject in value["subjects"]:
        _exact_fields(subject, ("runtime_id", "kind", "game_id"), "subject")
        subjects.append(
            ActorRef(
                subject["runtime_id"],
                ActorKind(subject["kind"]),
                subject["game_id"],
            )
        )
    return GameEvent(
        value["sequence"],
        value["event_type"],
        ContextRef(
            ContextKind(context["kind"]),
            context["scope_id"],
            context["revision"],
            context["session_id"],
            context["game_time"],
        ),
        tuple(subjects),
        value["payload"],
        Evidence(
            EvidenceLevel(evidence["level"]),
            evidence["source"],
            evidence["detail"],
            evidence["event_sequence"],
        ),
        value["occurred_at_ms"],
        value["cause_action_id"],
        value["schema"],
    )


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[GameEvent, ...]
    next_sequence: int
    high_watermark: int


@dataclass(frozen=True, slots=True)
class AppendResult:
    event: GameEvent
    inserted: bool


class SemanticEventLog:
    """SQLite event log with strict decoding and source-level idempotency."""

    def __init__(self, database):
        if not isinstance(database, (str, Path)):
            raise TypeError("database must be a path")
        self._lock = threading.RLock()
        self._db = sqlite3.connect(database, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._initialize_schema()
        except Exception:
            self._db.close()
            raise

    def _initialize_schema(self):
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS agentic_store_meta "
                "(name TEXT PRIMARY KEY, version INTEGER NOT NULL)"
            )
            row = self._db.execute(
                "SELECT version FROM agentic_store_meta WHERE name='events'"
            ).fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO agentic_store_meta VALUES ('events', 0)"
                )
                version = 0
            else:
                version = row["version"]
            if type(version) is not int or version < 0:
                raise ValueError("Invalid semantic event store schema version")
            if version > EVENT_STORE_SCHEMA_VERSION:
                raise ValueError("Semantic event store schema is newer than runtime")
            if version < 1:
                self._db.execute(
                    "CREATE TABLE agentic_events ("
                    "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "source_key TEXT NOT NULL UNIQUE, "
                    "input_hash TEXT NOT NULL, schema TEXT NOT NULL, "
                    "event_type TEXT NOT NULL, occurred_at_ms INTEGER NOT NULL, "
                    "data TEXT NOT NULL)"
                )
                self._db.execute(
                    "CREATE INDEX agentic_events_type_sequence "
                    "ON agentic_events(event_type, sequence)"
                )
                self._db.execute(
                    "UPDATE agentic_store_meta SET version=1 WHERE name='events'"
                )

    def append(self, event, source_key):
        """Assign a sequence to an uncommitted event and persist it once."""
        if not isinstance(event, GameEvent):
            raise TypeError("event must be a GameEvent")
        if event.sequence != 0 or event.evidence.event_sequence not in (None, 0):
            raise ValueError("new events must use unassigned sequence zero")
        if not isinstance(source_key, str) or not source_key.strip():
            raise ValueError("source_key must be a non-empty string")
        if len(source_key) > 512:
            raise ValueError("source_key cannot exceed 512 characters")
        unassigned = replace(
            event,
            sequence=0,
            evidence=replace(event.evidence, event_sequence=None),
        )
        canonical = json.dumps(
            to_wire(unassigned), sort_keys=True, separators=(",", ":")
        ).encode()
        input_hash = hashlib.sha256(canonical).hexdigest()
        with self._lock, self._db:
            existing = self._db.execute(
                "SELECT input_hash,data FROM agentic_events WHERE source_key=?",
                (source_key,),
            ).fetchone()
            if existing is not None:
                if existing["input_hash"] != input_hash:
                    raise ValueError("Conflicting event source key reuse")
                return AppendResult(
                    game_event_from_wire(json.loads(existing["data"])), False
                )
            cursor = self._db.execute(
                "INSERT INTO agentic_events "
                "(source_key,input_hash,schema,event_type,occurred_at_ms,data) "
                "VALUES (?,?,?,?,?,?)",
                (
                    source_key,
                    input_hash,
                    event.schema,
                    event.event_type,
                    event.occurred_at_ms,
                    "",
                ),
            )
            sequence = cursor.lastrowid
            evidence = replace(event.evidence, event_sequence=sequence)
            committed = replace(event, sequence=sequence, evidence=evidence)
            data = json.dumps(
                to_wire(committed), sort_keys=True, separators=(",", ":")
            )
            self._db.execute(
                "UPDATE agentic_events SET data=? WHERE sequence=?",
                (data, sequence),
            )
            return AppendResult(committed, True)

    def read(self, after_sequence=0, limit=100):
        if type(after_sequence) is not int or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be from 1 through 1000")
        with self._lock:
            rows = self._db.execute(
                "SELECT sequence,data FROM agentic_events "
                "WHERE sequence>? ORDER BY sequence LIMIT ?",
                (after_sequence, limit),
            ).fetchall()
            high_watermark = self._db.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM agentic_events"
            ).fetchone()[0]
        events = tuple(
            game_event_from_wire(json.loads(row["data"])) for row in rows
        )
        next_sequence = events[-1].sequence if events else after_sequence
        return EventPage(events, next_sequence, high_watermark)

    def migrate_legacy_bridge(self):
        """Import terminal bridge commands and committed Native dialogue rows.

        Legacy records lack enough context for modern semantic claims. Imported
        event names and evidence details retain that limitation explicitly.
        """
        with self._lock:
            drafts = self._legacy_dialogue_drafts() + self._legacy_command_drafts()
            inserted = 0
            for _, source_key, event in sorted(
                drafts, key=lambda item: (item[0], item[1])
            ):
                inserted += self.append(event, source_key).inserted
            return inserted

    def _has_table(self, name):
        return (
            self._db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )

    def _legacy_dialogue_drafts(self):
        if not self._has_table("native_dialogue_events"):
            return []
        rows = self._db.execute(
            "SELECT sequence,received,event,entry_id,data "
            "FROM native_dialogue_events ORDER BY sequence"
        ).fetchall()
        drafts = []
        for row in rows:
            data = json.loads(row["data"])
            if not isinstance(data, dict):
                raise ValueError("Invalid legacy Native dialogue event")
            session = data.get("mission_session")
            context_code = data.get("context")
            scope = (
                f"legacy:mission-session:{session}"
                if context_code == 1 and type(session) is int and session >= 0
                else f"legacy:conversation-context:{context_code}"
            )
            subjects = []
            for prefix, key, kind in (
                ("agent", "conversation_agent_id", ActorKind.AGENT),
                ("troop", "conversation_troop_id", ActorKind.TROOP),
            ):
                game_id = data.get(key)
                if type(game_id) is int and game_id >= 0:
                    subjects.append(ActorRef(f"{prefix}:{game_id}", kind, game_id))
            event = GameEvent(
                0,
                f"legacy.dialogue.{str(row['event']).replace('_', '-')}",
                ContextRef(
                    ContextKind.DIALOGUE,
                    scope,
                    0,
                    session if type(session) is int and session >= 0 else None,
                ),
                tuple(subjects),
                {
                    "legacy_table": "native_dialogue_events",
                    "source_sequence": row["sequence"],
                    "entry_id": row["entry_id"],
                    "symbol": data.get("symbol"),
                    "text_template": data.get("text_template"),
                    "input_state_id": data.get("input_state_id"),
                    "output_state_id": data.get("output_state_id"),
                },
                Evidence(
                    EvidenceLevel.ENGINE_OBSERVED,
                    data.get("source", "legacy Native dialogue table"),
                    "Imported committed entry; original scene/revision unavailable",
                ),
                round(float(row["received"]) * 1000),
            )
            drafts.append(
                (
                    event.occurred_at_ms,
                    f"bridge.native-dialogue:{row['sequence']}",
                    event,
                )
            )
        return drafts

    def _legacy_command_drafts(self):
        if not self._has_table("commands"):
            return []
        columns = {
            row[1] for row in self._db.execute("PRAGMA table_info(commands)")
        }
        required = {"id", "created", "status"}
        if not required <= columns:
            raise ValueError("Legacy commands table lacks required fields")
        selected = [
            name
            for name in (
                "id",
                "text",
                "created",
                "status",
                "kind",
                "arguments",
                "scene",
                "session",
                "result",
            )
            if name in columns
        ]
        rows = self._db.execute(
            f"SELECT {','.join(selected)} FROM commands ORDER BY id"
        ).fetchall()
        drafts = []
        for row in rows:
            data = dict(row)
            status = data["status"]
            if status not in _TERMINAL_COMMAND_STATES:
                continue
            scene = data.get("scene")
            session = data.get("session")
            if type(scene) is int and scene >= 0:
                context = ContextRef(
                    ContextKind.MISSION,
                    f"legacy:scene:{scene}",
                    0,
                    session if type(session) is int and session >= 0 else None,
                )
            else:
                context = ContextRef(ContextKind.CAMPAIGN, "legacy:campaign", 0)
            arguments = data.get("arguments", "{}")
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            level = (
                EvidenceLevel.ENGINE_ACKNOWLEDGED
                if status == "acknowledged" and data.get("result") == 0
                else EvidenceLevel.BRIDGE_SIMULATED
            )
            event = GameEvent(
                0,
                f"legacy.command.{status}",
                context,
                (),
                {
                    "legacy_table": "commands",
                    "command_id": data["id"],
                    "kind": data.get("kind", "message"),
                    "text": data.get("text"),
                    "arguments": arguments,
                    "result": data.get("result"),
                },
                Evidence(
                    level,
                    "legacy bridge command table",
                    "Imported terminal record; not independent outcome evidence",
                ),
                round(float(data["created"]) * 1000),
            )
            drafts.append(
                (
                    event.occurred_at_ms,
                    f"bridge.command:{data['id']}:terminal",
                    event,
                )
            )
        return drafts

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
