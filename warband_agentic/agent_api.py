"""Restricted semantic session API for untrusted agent applications."""

import hashlib
import json
import threading
import time
from dataclasses import dataclass

from warband_agentic.authority import ObservationFilter
from warband_agentic.capabilities import CapabilityRegistry
from warband_agentic.contracts import (
    CONTRACT_VERSION,
    ActionOutcome,
    ActionState,
    ActionSubmission,
    Affordance,
    Evidence,
    EvidenceLevel,
    GameEvent,
    ObservationEnvelope,
    RoleGrant,
    to_wire,
)
from warband_agentic.events import EventPage, SemanticEventLog


class AgentConflict(ValueError):
    """The request is valid JSON but conflicts with current runtime state."""


class AgentNotFound(ValueError):
    """The requested session-owned resource does not exist."""


@dataclass(frozen=True, slots=True)
class AgentTurn:
    session_id: str
    observation: ObservationEnvelope
    capabilities: tuple[dict, ...]
    affordances: tuple[Affordance, ...]
    event_cursor: int
    schema: str = CONTRACT_VERSION


class ConstrainedAgentSession:
    """Bind one role grant to filtered perception and server-issued actions."""

    def __init__(
        self,
        session_id,
        grant,
        registry,
        observation_filter,
        observation_provider,
        affordance_provider,
        dispatcher,
        lease_selector=None,
        event_log=None,
        clock_ms=None,
        action_id_factory=None,
    ):
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(grant, RoleGrant):
            raise TypeError("grant must be a RoleGrant")
        if not isinstance(registry, CapabilityRegistry):
            raise TypeError("registry must be a CapabilityRegistry")
        if not isinstance(observation_filter, ObservationFilter):
            raise TypeError("observation_filter must be an ObservationFilter")
        if event_log is not None and not isinstance(event_log, SemanticEventLog):
            raise TypeError("event_log must be a SemanticEventLog")
        for name, callback in (
            ("observation_provider", observation_provider),
            ("affordance_provider", affordance_provider),
            ("dispatcher", dispatcher),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if lease_selector is not None and not callable(lease_selector):
            raise TypeError("lease_selector must be callable")
        self.session_id = session_id
        self._grant = grant
        self._registry = registry
        self._filter = observation_filter
        self._observation_provider = observation_provider
        self._affordance_provider = affordance_provider
        self._dispatcher = dispatcher
        self._lease_selector = lease_selector or (lambda affordance: None)
        self._event_log = event_log
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._action_id_factory = action_id_factory or (
            lambda request_id: f"action:{self.session_id}:{request_id}"
        )
        self._turn = None
        self._requests = {}
        self._lock = threading.RLock()

    def manifest(self):
        return {
            "schema": CONTRACT_VERSION,
            "session_id": self.session_id,
            "role": self._grant.role.value,
            "actor": to_wire(self._grant.grantee),
            "submission": {
                "required": [
                    "request_id",
                    "affordance_token",
                    "arguments",
                    "expected_revision",
                ],
                "server_owned": [
                    "action_id",
                    "actor",
                    "grant_id",
                    "lease_id",
                    "submitted_at_ms",
                    "handler_id",
                ],
                "expected_revision_source": "turn.observation.context.revision",
            },
        }

    def turn(self):
        with self._lock:
            canonical = self._canonical_observation()
            if (
                self._turn is not None
                and self._turn.observation.context == canonical.context
            ):
                return self._turn
            now_ms = self._now()
            observation = self._filter.apply(
                canonical,
                self._grant,
                f"{self.session_id}:observation:{canonical.context.revision}",
                now_ms,
            )
            capabilities = tuple(
                self._registry.discover(self._grant, canonical.context, now_ms)
            )
            affordances = tuple(
                self._affordance_provider(
                    self._registry,
                    self._grant,
                    observation,
                    now_ms,
                )
            )
            for affordance in affordances:
                if not isinstance(affordance, Affordance):
                    raise TypeError("Affordance provider returned a non-affordance")
                if affordance.actor != self._grant.grantee:
                    raise ValueError(
                        "Affordance provider returned another actor's token"
                    )
                if affordance.context != canonical.context:
                    raise ValueError("Affordance provider returned stale context")
            cursor = self._event_log.read().high_watermark if self._event_log else 0
            self._turn = AgentTurn(
                self.session_id,
                observation,
                capabilities,
                affordances,
                cursor,
            )
            return self._turn

    def submit(self, request):
        allowed = {
            "request_id",
            "affordance_token",
            "arguments",
            "expected_revision",
        }
        if not isinstance(request, dict) or set(request) != allowed:
            raise ValueError("Submission fields do not match constrained interface")
        request_id = request["request_id"]
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > 200
            or not request_id.isprintable()
        ):
            raise ValueError("request_id must be 1-200 printable characters")
        canonical_request = json.dumps(
            request, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        request_hash = hashlib.sha256(canonical_request).hexdigest()
        with self._lock:
            prior = self._requests.get(request_id)
            if prior is not None:
                if prior[0] != request_hash:
                    raise AgentConflict("request_id was reused with different input")
                return prior[1]
            now_ms = self._now()
            current = self._canonical_observation().context
            active_turn = self.turn()
            affordance = next(
                (
                    item
                    for item in active_turn.affordances
                    if item.token == request["affordance_token"]
                ),
                None,
            )
            if affordance is None:
                raise AgentConflict("Affordance is not part of the active turn")
            action_id = self._action_id_factory(request_id)
            submission = ActionSubmission(
                action_id,
                request["affordance_token"],
                self._grant.grantee,
                request["arguments"],
                request["expected_revision"],
                now_ms,
                self._lease_selector(affordance),
            )
            try:
                validated = self._registry.consume(
                    submission, current, self._grant, now_ms
                )
            except ValueError as exc:
                raise AgentConflict(str(exc)) from exc
            outcome = self._dispatch(validated, current, now_ms)
            self._requests[request_id] = (request_hash, outcome)
            self._record_action_event(request_id, validated.affordance, outcome)
            self._turn = None
            return outcome

    def _dispatch(self, validated, current, now_ms):
        try:
            outcome = self._dispatcher(validated)
            if not isinstance(outcome, ActionOutcome):
                raise TypeError("dispatcher returned no ActionOutcome")
            if outcome.action_id != validated.submission.action_id:
                raise ValueError("dispatcher returned another action's outcome")
            if outcome.context != validated.affordance.context:
                raise ValueError("dispatcher returned an outcome for another context")
            if (
                outcome.resulting_revision is not None
                and outcome.resulting_revision < outcome.context.revision
            ):
                raise ValueError("dispatcher returned a regressed runtime revision")
            return outcome
        except Exception as exc:
            return ActionOutcome(
                validated.submission.action_id,
                ActionState.INTERRUPTED,
                current,
                None,
                None,
                (),
                (
                    Evidence(
                        EvidenceLevel.DECLARED,
                        "constrained agent runtime",
                        "Dispatcher failed before a verified outcome",
                    ),
                ),
                f"{type(exc).__name__}: {exc}",
                now_ms,
            )

    def outcome(self, request_id):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        with self._lock:
            try:
                return self._requests[request_id][1]
            except KeyError as exc:
                raise AgentNotFound("Unknown session request") from exc

    def events(self, after_sequence=0, limit=100):
        if type(after_sequence) is not int or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be from 1 through 100")
        if self._event_log is None:
            return EventPage((), after_sequence, 0)
        selected = []
        cursor = after_sequence
        high_watermark = after_sequence
        while len(selected) < limit:
            page = self._event_log.read(cursor, 1000)
            high_watermark = page.high_watermark
            for event in page.events:
                if event.payload.get("agent_session_id") == self.session_id:
                    selected.append(event)
                    if len(selected) == limit:
                        return EventPage(
                            tuple(selected), event.sequence, high_watermark
                        )
            if page.next_sequence == cursor or page.next_sequence >= high_watermark:
                cursor = page.next_sequence
                break
            cursor = page.next_sequence
        return EventPage(tuple(selected), cursor, high_watermark)

    def _record_action_event(self, request_id, affordance, outcome):
        if self._event_log is None:
            return
        evidence = max(
            outcome.evidence,
            key=lambda item: item.level.rank,
            default=Evidence(
                EvidenceLevel.DECLARED,
                "constrained agent runtime",
                "No stronger action evidence was supplied",
            ),
        )
        event = GameEvent(
            0,
            f"action.{outcome.state.value}",
            outcome.context,
            affordance.targets,
            {
                "agent_session_id": self.session_id,
                "request_id": request_id,
                "capability": affordance.capability,
                "engine_result": outcome.engine_result,
                "facts": [to_wire(fact) for fact in outcome.facts],
                "reason": outcome.reason,
            },
            Evidence(evidence.level, evidence.source, evidence.detail),
            outcome.recorded_at_ms,
            outcome.action_id,
        )
        self._event_log.append(
            event, f"agent-session:{self.session_id}:request:{request_id}"
        )

    def _canonical_observation(self):
        observation = self._observation_provider()
        if not isinstance(observation, ObservationEnvelope):
            raise TypeError("observation_provider returned no ObservationEnvelope")
        return observation

    def _now(self):
        value = self._clock_ms()
        if type(value) is not int or value < 0:
            raise ValueError("clock must return a non-negative integer")
        return value
