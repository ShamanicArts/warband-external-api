"""Restricted semantic session API for untrusted agent applications."""

import hashlib
import json
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace

from warband_agentic.authority import ObservationFilter
from warband_agentic.capabilities import CapabilityRegistry
from warband_agentic.contracts import (
    CONTRACT_VERSION,
    ActionOutcome,
    ActionState,
    ActionSubmission,
    Affordance,
    ContextKind,
    ContextRef,
    Evidence,
    EvidenceLevel,
    Fact,
    FactSource,
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


class AgentPending(RuntimeError):
    """Fresh engine-backed state was requested but is not complete yet."""


@dataclass(frozen=True, slots=True)
class AgentTurn:
    session_id: str
    observation: ObservationEnvelope
    capabilities: tuple[dict, ...]
    affordances: tuple[Affordance, ...]
    event_cursor: int
    schema: str = CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class _StoredRequest:
    request_hash: str
    outcome: ActionOutcome
    capability: str
    targets: tuple
    application_recovery: dict | None


def _exact_fields(value, expected, label):
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError(f"Invalid recovered {label} fields")


def _outcome_from_wire(value):
    _exact_fields(
        value,
        (
            "action_id",
            "state",
            "context",
            "resulting_revision",
            "engine_result",
            "facts",
            "evidence",
            "reason",
            "recorded_at_ms",
            "schema",
        ),
        "outcome",
    )
    context = value["context"]
    _exact_fields(
        context,
        ("kind", "scope_id", "revision", "session_id", "game_time"),
        "outcome context",
    )
    if not isinstance(value["facts"], (list, tuple)):
        raise ValueError("Invalid recovered outcome facts")
    facts = []
    for item in value["facts"]:
        _exact_fields(
            item,
            ("key", "value", "source", "observed_revision"),
            "outcome fact",
        )
        facts.append(
            Fact(
                item["key"],
                item["value"],
                FactSource(item["source"]),
                item["observed_revision"],
            )
        )
    if not isinstance(value["evidence"], (list, tuple)):
        raise ValueError("Invalid recovered outcome evidence")
    evidence = []
    for item in value["evidence"]:
        _exact_fields(
            item,
            ("level", "source", "detail", "event_sequence"),
            "outcome evidence",
        )
        evidence.append(
            Evidence(
                EvidenceLevel(item["level"]),
                item["source"],
                item["detail"],
                item["event_sequence"],
            )
        )
    return ActionOutcome(
        value["action_id"],
        ActionState(value["state"]),
        ContextRef(
            ContextKind(context["kind"]),
            context["scope_id"],
            context["revision"],
            context["session_id"],
            context["game_time"],
        ),
        value["resulting_revision"],
        value["engine_result"],
        tuple(facts),
        tuple(evidence),
        value["reason"],
        value["recorded_at_ms"],
        value["schema"],
    )


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
        outcome_refresher=None,
        recovery_exporter=None,
        recovery_importer=None,
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
        if outcome_refresher is not None and not callable(outcome_refresher):
            raise TypeError("outcome_refresher must be callable")
        if (recovery_exporter is None) != (recovery_importer is None):
            raise ValueError(
                "recovery_exporter and recovery_importer must be supplied together"
            )
        if recovery_exporter is not None and not callable(recovery_exporter):
            raise TypeError("recovery_exporter must be callable")
        if recovery_importer is not None and not callable(recovery_importer):
            raise TypeError("recovery_importer must be callable")
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
        self._outcome_refresher = outcome_refresher
        self._recovery_exporter = recovery_exporter
        self._recovery_importer = recovery_importer
        self._turn = None
        self._requests = {}
        self._unrecoverable_requests = set()
        self._lock = threading.RLock()
        self._restore_requests()

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
                "request_id": {
                    "type": "client_chosen_idempotency_key",
                    "constraints": "1-200 printable characters",
                    "retry_rule": (
                        "reuse only for an identical submission; use a new value "
                        "for changed intent"
                    ),
                    "example": "decision:epoch-12:party-17",
                },
                "authorization": {
                    "source": "turn.affordances[]",
                    "capabilities": (
                        "descriptive schemas only; capability presence does not "
                        "authorize an action"
                    ),
                },
                "arguments": {
                    "schema_source": "turn.affordances[].parameters",
                    "required_properties_source": (
                        "turn.affordances[].parameters.required"
                    ),
                    "const_properties": "submit_the_exact_value",
                },
                "affordance_time": {
                    "fields": ["issued_at_ms", "expires_at_ms"],
                    "unit": "milliseconds",
                    "clock": "session_runtime_clock",
                    "client_rule": (
                        "treat_as_same_session_validity_metadata_and_fetch_a_fresh_"
                        "turn_after_expiry_or_conflict"
                    ),
                },
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

    def invalidate_turn(self):
        """Discard one cached public turn after trusted application-state change."""
        with self._lock:
            self._turn = None

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
                if prior.request_hash != request_hash:
                    raise AgentConflict("request_id was reused with different input")
                return prior.outcome
            if request_id in self._unrecoverable_requests:
                raise AgentConflict(
                    "request_id exists in older durable history and cannot be "
                    "safely replayed"
                )
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
            application_recovery = None
            if self._recovery_exporter is not None:
                application_recovery = self._recovery_exporter(validated, outcome)
                if not isinstance(application_recovery, Mapping):
                    raise TypeError("recovery_exporter must return a mapping")
                application_recovery = json.loads(
                    json.dumps(
                        application_recovery,
                        allow_nan=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
            record = _StoredRequest(
                request_hash,
                outcome,
                validated.affordance.capability,
                validated.affordance.targets,
                application_recovery,
            )
            self._requests[request_id] = record
            self._record_action_event(request_id, record)
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
            if request_id in self._unrecoverable_requests:
                raise AgentNotFound(
                    "Request predates durable recovery; outcome lookup is unavailable"
                )
            try:
                record = self._requests[request_id]
            except KeyError as exc:
                raise AgentNotFound("Unknown session request") from exc
            outcome = record.outcome
            if self._outcome_refresher is None:
                return outcome
            refreshed = self._outcome_refresher(request_id, outcome)
            self._validate_refreshed_outcome(outcome, refreshed)
            if refreshed != outcome:
                record = replace(record, outcome=refreshed)
                self._requests[request_id] = record
                self._record_action_event(request_id, record)
            return refreshed

    @staticmethod
    def _validate_refreshed_outcome(previous, refreshed):
        if not isinstance(refreshed, ActionOutcome):
            raise TypeError("outcome_refresher returned no ActionOutcome")
        if refreshed.action_id != previous.action_id:
            raise ValueError("outcome_refresher changed the action ID")
        if refreshed.context != previous.context:
            raise ValueError("outcome_refresher changed the action context")
        allowed = {
            ActionState.SUBMITTED: tuple(ActionState),
            ActionState.ACCEPTED: (
                ActionState.ACCEPTED,
                ActionState.DISPATCHED,
                ActionState.ACKNOWLEDGED,
                ActionState.REJECTED,
                ActionState.EXPIRED,
                ActionState.INTERRUPTED,
                ActionState.OBSERVED,
            ),
            ActionState.DISPATCHED: (
                ActionState.DISPATCHED,
                ActionState.ACKNOWLEDGED,
                ActionState.REJECTED,
                ActionState.EXPIRED,
                ActionState.INTERRUPTED,
                ActionState.OBSERVED,
            ),
            ActionState.ACKNOWLEDGED: (
                ActionState.ACKNOWLEDGED,
                ActionState.OBSERVED,
            ),
            ActionState.REJECTED: (ActionState.REJECTED,),
            ActionState.EXPIRED: (
                ActionState.EXPIRED,
                ActionState.ACKNOWLEDGED,
                ActionState.REJECTED,
                ActionState.OBSERVED,
            ),
            ActionState.INTERRUPTED: (
                ActionState.INTERRUPTED,
                ActionState.ACKNOWLEDGED,
                ActionState.REJECTED,
                ActionState.OBSERVED,
            ),
            ActionState.OBSERVED: (ActionState.OBSERVED,),
        }
        if refreshed.state not in allowed[previous.state]:
            raise ValueError("outcome_refresher returned an invalid state transition")

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
                    selected.append(self._public_event(event))
                    if len(selected) == limit:
                        return EventPage(
                            tuple(selected), event.sequence, high_watermark
                        )
            if page.next_sequence == cursor or page.next_sequence >= high_watermark:
                cursor = page.next_sequence
                break
            cursor = page.next_sequence
        return EventPage(tuple(selected), cursor, high_watermark)

    @staticmethod
    def _public_event(event):
        if "_recovery" not in event.payload:
            return event
        return replace(
            event,
            payload={
                key: value for key, value in event.payload.items() if key != "_recovery"
            },
        )

    def _record_action_event(self, request_id, record):
        if self._event_log is None:
            return
        outcome = record.outcome
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
            record.targets,
            {
                "agent_session_id": self.session_id,
                "request_id": request_id,
                "capability": record.capability,
                "engine_result": outcome.engine_result,
                "facts": [to_wire(fact) for fact in outcome.facts],
                "reason": outcome.reason,
                "_recovery": {
                    "request_hash": record.request_hash,
                    "outcome": to_wire(outcome),
                    "application": record.application_recovery,
                },
            },
            Evidence(evidence.level, evidence.source, evidence.detail),
            outcome.recorded_at_ms,
            outcome.action_id,
        )
        self._event_log.append(
            event,
            f"agent-session:{self.session_id}:request:{request_id}:"
            f"state:{outcome.state.value}",
        )

    def _restore_requests(self):
        if self._event_log is None:
            return
        cursor = 0
        while True:
            page = self._event_log.read(cursor, 1000)
            for event in page.events:
                payload = event.payload
                if payload.get("agent_session_id") != self.session_id:
                    continue
                if not event.event_type.startswith("action."):
                    continue
                recovery = payload.get("_recovery")
                if recovery is None:
                    request_id = payload.get("request_id")
                    if isinstance(request_id, str) and request_id:
                        self._unrecoverable_requests.add(request_id)
                    continue
                _exact_fields(
                    recovery,
                    ("request_hash", "outcome", "application"),
                    "request metadata",
                )
                request_id = payload.get("request_id")
                capability = payload.get("capability")
                request_hash = recovery["request_hash"]
                if not isinstance(request_id, str) or not request_id:
                    raise ValueError("Invalid recovered request ID")
                if not isinstance(capability, str) or not capability:
                    raise ValueError("Invalid recovered capability")
                if (
                    not isinstance(request_hash, str)
                    or len(request_hash) != 64
                    or any(c not in "0123456789abcdef" for c in request_hash)
                ):
                    raise ValueError("Invalid recovered request hash")
                outcome = _outcome_from_wire(recovery["outcome"])
                application_recovery = recovery["application"]
                if application_recovery is not None:
                    if not isinstance(application_recovery, Mapping):
                        raise ValueError("Invalid application recovery metadata")
                    application_recovery = to_wire(application_recovery)
                if event.event_type != f"action.{outcome.state.value}":
                    raise ValueError("Recovered action event state does not match")
                if event.cause_action_id != outcome.action_id:
                    raise ValueError("Recovered action ID does not match event")
                if event.context != outcome.context:
                    raise ValueError("Recovered action context does not match event")
                record = _StoredRequest(
                    request_hash,
                    outcome,
                    capability,
                    event.subjects,
                    application_recovery,
                )
                previous = self._requests.get(request_id)
                if previous is not None:
                    if (
                        previous.request_hash != record.request_hash
                        or previous.capability != record.capability
                        or previous.targets != record.targets
                        or previous.application_recovery != record.application_recovery
                        or previous.outcome.action_id != record.outcome.action_id
                        or previous.outcome.context != record.outcome.context
                    ):
                        raise ValueError("Conflicting recovered request history")
                    self._validate_refreshed_outcome(previous.outcome, record.outcome)
                self._requests[request_id] = record
                self._unrecoverable_requests.discard(request_id)
            if (
                page.next_sequence == cursor
                or page.next_sequence >= page.high_watermark
            ):
                break
            cursor = page.next_sequence
        if self._recovery_importer is not None:
            for record in self._requests.values():
                if record.application_recovery is None:
                    raise ValueError(
                        "Application recovery metadata is missing from action history"
                    )
                self._recovery_importer(
                    record.outcome.action_id,
                    record.application_recovery,
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
