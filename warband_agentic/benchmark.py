"""Provider-neutral synchronized decision epochs for faction benchmarks."""

import hashlib
import hmac
import json
import os
import tempfile
from copy import deepcopy
from enum import StrEnum
from pathlib import Path

from warband_agentic.agent_api import AgentConflict, AgentTurn
from warband_agentic.contracts import ActionOutcome, ActionState, ContextKind, to_wire


class BenchmarkEpochState(StrEnum):
    CREATED = "created"
    REFRESHING = "refreshing"
    COLLECTING = "collecting"
    COMMITTED = "committed"
    RESOLVED = "resolved"


def _json_copy(value, name):
    try:
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only finite JSON values") from exc
    return deepcopy(value)


class SynchronizedFactionEpoch:
    """Collect equal-time faction turns and commit decisions deterministically."""

    def __init__(self, epoch_id, applications, *, run_metadata):
        if not isinstance(epoch_id, str) or not epoch_id.strip():
            raise ValueError("epoch_id must be a non-empty string")
        if not isinstance(applications, dict) or len(applications) < 2:
            raise ValueError("applications must contain at least two factions")
        normalized = {}
        owners = {}
        for faction_id, application in applications.items():
            if type(faction_id) is not int or faction_id < 0:
                raise ValueError("faction IDs must be non-negative integers")
            if getattr(application, "faction_id", None) != faction_id:
                raise ValueError("application faction ID does not match its key")
            if not callable(getattr(application, "queue_observation_refresh", None)):
                raise TypeError("faction application must support observation refresh")
            session = getattr(application, "session", None)
            if any(
                not callable(getattr(session, name, None))
                for name in ("turn", "submit", "outcome")
            ):
                raise TypeError("faction application must expose a constrained session")
            parties = tuple(getattr(application, "controlled_party_ids", ()))
            if not parties:
                raise ValueError("each faction application must control a party")
            for party_id in parties:
                if type(party_id) is not int or party_id < 0:
                    raise ValueError(
                        "controlled party IDs must be non-negative integers"
                    )
                if party_id in owners:
                    raise ValueError(
                        f"party {party_id} is controlled by factions "
                        f"{owners[party_id]} and {faction_id}"
                    )
                owners[party_id] = faction_id
            normalized[faction_id] = application
        self.epoch_id = epoch_id
        self._applications = dict(sorted(normalized.items()))
        self.run_metadata = _json_copy(run_metadata, "run_metadata")
        self.state = BenchmarkEpochState.CREATED
        self._refresh_jobs = None
        self._turns = None
        self._turn_set_sha256 = None
        self._campaign_game_time = None
        self._decisions = None
        self._records = None
        self._campaign_advance = None

    def queue_observation_refreshes(self):
        if self.state is not BenchmarkEpochState.CREATED:
            raise RuntimeError("observation refreshes were already queued")
        jobs = {}
        for faction_id, application in self._applications.items():
            jobs[faction_id] = _json_copy(
                application.queue_observation_refresh(),
                f"faction {faction_id} refresh jobs",
            )
        self._refresh_jobs = jobs
        self.state = BenchmarkEpochState.REFRESHING
        return _json_copy(jobs, "refresh jobs")

    def collect_turns(self):
        if self.state is not BenchmarkEpochState.REFRESHING:
            raise RuntimeError("turns require queued and completed refreshes")
        turns = {}
        game_times = set()
        scopes = set()
        for faction_id, application in self._applications.items():
            turn = application.session.turn()
            if not isinstance(turn, AgentTurn):
                raise TypeError("faction session returned no AgentTurn")
            context = turn.observation.context
            if context.kind is not ContextKind.CAMPAIGN:
                raise ValueError("faction benchmark turn is not in campaign context")
            if type(context.game_time) is not int or context.game_time < 0:
                raise ValueError("faction benchmark turn has no valid engine time")
            game_times.add(context.game_time)
            scopes.add(context.scope_id)
            turns[faction_id] = to_wire(turn)
        if len(scopes) != 1:
            raise ValueError("faction turns do not share one campaign scope")
        if len(game_times) != 1:
            raise ValueError("faction turns do not share one campaign game time")
        canonical = json.dumps(
            turns, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode()
        self._turns = turns
        self._turn_set_sha256 = hashlib.sha256(canonical).hexdigest()
        self._campaign_game_time = next(iter(game_times))
        self.state = BenchmarkEpochState.COLLECTING
        return _json_copy(turns, "turns")

    def commit_decisions(self, decisions):
        if self.state is not BenchmarkEpochState.COLLECTING:
            raise RuntimeError("decisions require a synchronized turn set")
        if not isinstance(decisions, dict) or set(decisions) != set(self._applications):
            raise ValueError("decisions must contain exactly one response per faction")
        copied = {
            faction_id: _json_copy(decisions[faction_id], "decision")
            for faction_id in self._applications
        }
        records = {}
        for faction_id, application in self._applications.items():
            request = copied[faction_id]
            request_id = (
                request.get("request_id") if isinstance(request, dict) else None
            )
            try:
                outcome = application.session.submit(request)
                if not isinstance(outcome, ActionOutcome):
                    raise TypeError("faction session returned no ActionOutcome")
                records[faction_id] = {
                    "accepted": True,
                    "request_id": request_id,
                    "outcome": to_wire(outcome),
                }
            except (AgentConflict, TypeError, ValueError) as exc:
                records[faction_id] = {
                    "accepted": False,
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
        self._decisions = copied
        self._records = records
        self.state = BenchmarkEpochState.COMMITTED
        return _json_copy(records, "decision records")

    def refresh_outcomes(self):
        if self.state not in (
            BenchmarkEpochState.COMMITTED,
            BenchmarkEpochState.RESOLVED,
        ):
            raise RuntimeError("no committed decisions to refresh")
        unresolved = False
        for faction_id, record in self._records.items():
            if not record["accepted"]:
                continue
            outcome = self._applications[faction_id].session.outcome(
                record["request_id"]
            )
            if not isinstance(outcome, ActionOutcome):
                raise TypeError("faction session returned no ActionOutcome")
            record["outcome"] = to_wire(outcome)
            if outcome.state in (
                ActionState.ACCEPTED,
                ActionState.DISPATCHED,
                ActionState.ACKNOWLEDGED,
            ):
                unresolved = True
        self.state = (
            BenchmarkEpochState.COMMITTED
            if unresolved
            else BenchmarkEpochState.RESOLVED
        )
        return _json_copy(self._records, "decision records")

    def record_campaign_advance(self, status):
        """Attach one completed, matching fixed-time advance to the transcript."""
        if self.state is not BenchmarkEpochState.RESOLVED:
            raise RuntimeError("campaign time cannot advance before actions resolve")
        value = _json_copy(status, "campaign advance")
        if not isinstance(value, dict):
            raise TypeError("campaign advance must be an object")
        if value.get("epoch_id") != self.epoch_id:
            raise ValueError("campaign advance belongs to another epoch")
        if value.get("state") != "complete":
            raise ValueError("campaign advance is not complete")
        if value.get("start_clock") != self._campaign_game_time:
            raise ValueError("campaign advance did not start at the decision time")
        if (
            value.get("target_reached") is not True
            or value.get("stop_acknowledged") is not True
            or value.get("stop_command_status") != "acknowledged"
        ):
            raise ValueError("campaign advance lacks target and stop proof")
        for name in ("start_clock", "target_clock", "current_clock", "elapsed_hours"):
            if type(value.get(name)) is not int:
                raise ValueError(f"campaign advance {name} must be an integer")
        if (
            value["target_clock"] <= value["start_clock"]
            or value["current_clock"] < value["target_clock"]
            or value["elapsed_hours"] != value["current_clock"] - value["start_clock"]
        ):
            raise ValueError("campaign advance clock evidence is inconsistent")
        self._campaign_advance = value
        return _json_copy(value, "campaign advance")

    def transcript(self):
        if self._turns is None:
            raise RuntimeError("transcript requires a synchronized turn set")
        return _json_copy(
            {
                "schema": "warband.agentic/benchmark-epoch/v1",
                "epoch_id": self.epoch_id,
                "state": self.state.value,
                "run_metadata": self.run_metadata,
                "campaign_game_time": self._campaign_game_time,
                "turn_set_sha256": self._turn_set_sha256,
                "refresh_jobs": self._refresh_jobs,
                "turns": self._turns,
                "decisions": self._decisions,
                "decision_records": self._records,
                "campaign_advance": self._campaign_advance,
            },
            "transcript",
        )

    def write_transcript(self, path):
        """Atomically persist one completed epoch transcript as canonical JSON."""
        if self.state is not BenchmarkEpochState.RESOLVED:
            raise RuntimeError("only a resolved epoch can be persisted")
        if self._campaign_advance is None:
            raise RuntimeError("epoch has no completed campaign advance")
        return self._atomic_write(path, self.transcript(), "transcript")

    def write_checkpoint(self, path):
        """Persist a committed/resolved coordinator state without replaying it."""
        return self._atomic_write(path, self.checkpoint(), "checkpoint")

    def checkpoint(self):
        """Return a checksummed JSON checkpoint for committed coordinator state."""
        if self.state not in (
            BenchmarkEpochState.COMMITTED,
            BenchmarkEpochState.RESOLVED,
        ):
            raise RuntimeError("checkpoint requires committed decisions")
        payload = self.transcript()
        canonical = json.dumps(
            payload, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode()
        return {
            "schema": "warband.agentic/benchmark-checkpoint/v1",
            "payload_sha256": hashlib.sha256(canonical).hexdigest(),
            "payload": payload,
        }

    @classmethod
    def load_checkpoint(cls, path, applications):
        """Restore coordinator state; constrained sessions restore action state."""
        target = Path(path)
        try:
            wrapper = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Cannot read benchmark checkpoint") from exc
        return cls.from_checkpoint(wrapper, applications)

    @classmethod
    def from_checkpoint(cls, wrapper, applications):
        """Restore coordinator state from a decoded checkpoint object."""
        if not isinstance(wrapper, dict) or set(wrapper) != {
            "schema",
            "payload_sha256",
            "payload",
        }:
            raise ValueError("Invalid benchmark checkpoint fields")
        if wrapper["schema"] != "warband.agentic/benchmark-checkpoint/v1":
            raise ValueError("Unsupported benchmark checkpoint schema")
        payload = wrapper["payload"]
        if not isinstance(payload, dict):
            raise ValueError("Invalid benchmark checkpoint payload")
        canonical = json.dumps(
            payload, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode()
        if not isinstance(wrapper["payload_sha256"], str) or not hmac.compare_digest(
            wrapper["payload_sha256"], hashlib.sha256(canonical).hexdigest()
        ):
            raise ValueError("Benchmark checkpoint checksum does not match")
        expected = {
            "schema",
            "epoch_id",
            "state",
            "run_metadata",
            "campaign_game_time",
            "turn_set_sha256",
            "refresh_jobs",
            "turns",
            "decisions",
            "decision_records",
            "campaign_advance",
        }
        if set(payload) != expected:
            raise ValueError("Invalid benchmark checkpoint payload fields")
        if payload["schema"] != "warband.agentic/benchmark-epoch/v1":
            raise ValueError("Unsupported benchmark epoch schema")
        try:
            state = BenchmarkEpochState(payload["state"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid benchmark checkpoint state") from exc
        if state not in (
            BenchmarkEpochState.COMMITTED,
            BenchmarkEpochState.RESOLVED,
        ):
            raise ValueError("Benchmark checkpoint is not safely resumable")
        epoch = cls(
            payload["epoch_id"],
            applications,
            run_metadata=payload["run_metadata"],
        )
        faction_ids = set(epoch._applications)

        def faction_map(name, *, optional=False):
            value = payload[name]
            if optional and value is None:
                return None
            if not isinstance(value, dict):
                raise ValueError(f"Checkpoint {name} must be an object")
            try:
                converted = {int(key): item for key, item in value.items()}
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Checkpoint {name} has invalid faction IDs") from exc
            if set(converted) != faction_ids or len(converted) != len(value):
                raise ValueError(
                    f"Checkpoint {name} factions do not match applications"
                )
            return converted

        turns = faction_map("turns")
        turn_canonical = json.dumps(
            turns, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode()
        turn_hash = hashlib.sha256(turn_canonical).hexdigest()
        if payload["turn_set_sha256"] != turn_hash:
            raise ValueError("Checkpoint turn-set hash does not match")
        epoch.state = state
        epoch._refresh_jobs = faction_map("refresh_jobs")
        epoch._turns = turns
        epoch._turn_set_sha256 = turn_hash
        game_time = payload["campaign_game_time"]
        if type(game_time) is not int or game_time < 0:
            raise ValueError("Checkpoint campaign game time is invalid")
        epoch._campaign_game_time = game_time
        epoch._decisions = faction_map("decisions")
        epoch._records = faction_map("decision_records")
        epoch._campaign_advance = _json_copy(
            payload["campaign_advance"], "campaign advance"
        )
        return epoch

    @staticmethod
    def _atomic_write(path, value, label):
        target = Path(path)
        if not target.name or not target.parent.is_dir():
            raise ValueError(f"{label} parent directory must already exist")
        payload = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target
