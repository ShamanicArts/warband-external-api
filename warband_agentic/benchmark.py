"""Provider-neutral synchronized decision epochs for faction benchmarks."""

import hashlib
import json
from copy import deepcopy
from enum import StrEnum

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
            },
            "transcript",
        )
