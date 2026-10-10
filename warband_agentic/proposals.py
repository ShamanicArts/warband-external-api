"""Participant-approved mechanical proposals bound to exact affordances."""

import secrets
import threading
import time
from dataclasses import dataclass
from enum import StrEnum

from warband_agentic.capabilities import validate_json_object
from warband_agentic.contracts import ActionOutcome, Affordance, ContextRef, to_wire


class MechanicalProposalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STALE = "stale"
    SUBMITTED = "submitted"


@dataclass(frozen=True, slots=True)
class _ProposalOption:
    token: str
    source_session_id: str
    source_context: ContextRef
    title: str
    target_session_id: str
    target_session: object
    affordance: Affordance
    arguments: object
    required_acceptors: tuple[str, ...]


@dataclass(slots=True)
class _ProposalRecord:
    proposal_id: str
    option: _ProposalOption
    source_action_id: str
    decisions: dict
    state: MechanicalProposalState
    outcome: ActionOutcome | None = None


class MechanicalProposalBroker:
    """Keep generated intent separate from authority and game execution."""

    def __init__(self, *, clock_ms=None, token_factory=None, proposal_id_factory=None):
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._token_factory = token_factory or (
            lambda: "proposal-option:" + secrets.token_urlsafe(18)
        )
        self._proposal_id_factory = proposal_id_factory or (
            lambda: "proposal:" + secrets.token_urlsafe(18)
        )
        self._options = {}
        self._option_committed_by = {}
        self._proposals = {}
        self._proposal_by_source_action = {}
        self._executing = set()
        self._lock = threading.RLock()

    def offer(
        self,
        *,
        source_session_id,
        source_context,
        title,
        target_session_id,
        target_session,
        affordance_token,
        arguments,
        required_acceptors,
    ):
        """Bind one public proposal option to a current private affordance."""
        for label, value in (
            ("source_session_id", source_session_id),
            ("title", title),
            ("target_session_id", target_session_id),
            ("affordance_token", affordance_token),
        ):
            self._identifier(label, value)
        if not isinstance(source_context, ContextRef):
            raise TypeError("source_context must be a ContextRef")
        if not callable(getattr(target_session, "turn", None)) or not callable(
            getattr(target_session, "submit", None)
        ):
            raise TypeError("target_session must provide turn() and submit()")
        acceptors = tuple(required_acceptors)
        if not 1 <= len(acceptors) <= 16 or len(set(acceptors)) != len(acceptors):
            raise ValueError("required_acceptors must contain 1-16 unique IDs")
        for acceptor in acceptors:
            self._identifier("acceptor", acceptor)
        now_ms = self._now()
        turn = target_session.turn()
        affordance = next(
            (item for item in turn.affordances if item.token == affordance_token),
            None,
        )
        if affordance is None or affordance.context != turn.observation.context:
            raise ValueError("proposal must bind a current target affordance")
        if now_ms >= affordance.expires_at_ms:
            raise ValueError("proposal target affordance has expired")
        bound_arguments = validate_json_object(
            affordance.parameters, arguments, "proposal arguments"
        )
        token = self._token_factory()
        self._identifier("proposal option token", token)
        option = _ProposalOption(
            token,
            source_session_id,
            source_context,
            title,
            target_session_id,
            target_session,
            affordance,
            bound_arguments,
            acceptors,
        )
        with self._lock:
            if token in self._options:
                raise ValueError("proposal option token collision")
            self._options[token] = option
        return self._public_option(option)

    def options(self, source_session_id, source_context):
        """Return current safe option manifests for one dialogue turn."""
        self._identifier("source_session_id", source_session_id)
        if not isinstance(source_context, ContextRef):
            raise TypeError("source_context must be a ContextRef")
        now_ms = self._now()
        with self._lock:
            candidates = tuple(self._options.values())
            committed = set(self._option_committed_by)
        result = []
        for option in candidates:
            if (
                option.source_session_id != source_session_id
                or option.source_context != source_context
                or now_ms >= option.affordance.expires_at_ms
                or option.token in committed
            ):
                continue
            target_turn = option.target_session.turn()
            if target_turn.observation.context != option.affordance.context or all(
                item.token != option.affordance.token
                for item in target_turn.affordances
            ):
                continue
            result.append(self._public_option(option))
        return tuple(result)

    def commit(self, option_token, source_action_id, source_context):
        """Create a pending proposal only after the dialogue action is observed."""
        self._identifier("option_token", option_token)
        self._identifier("source_action_id", source_action_id)
        if not isinstance(source_context, ContextRef):
            raise TypeError("source_context must be a ContextRef")
        now_ms = self._now()
        with self._lock:
            existing_id = self._proposal_by_source_action.get(source_action_id)
            if existing_id is not None:
                existing = self._proposals[existing_id]
                if existing.option.token != option_token:
                    raise ValueError("source action already committed another proposal")
                return self._public_proposal(existing)
            option = self._options.get(option_token)
            if option is None:
                raise ValueError("unknown mechanical proposal option")
            committed_by = self._option_committed_by.get(option_token)
            if committed_by is not None:
                raise ValueError("mechanical proposal option was already committed")
            if option.source_context != source_context:
                raise ValueError("mechanical proposal uses a stale dialogue context")
            if now_ms >= option.affordance.expires_at_ms:
                raise ValueError("mechanical proposal option has expired")
            proposal_id = self._proposal_id_factory()
            self._identifier("proposal_id", proposal_id)
            if proposal_id in self._proposals:
                raise ValueError("mechanical proposal ID collision")
            record = _ProposalRecord(
                proposal_id,
                option,
                source_action_id,
                {},
                MechanicalProposalState.PENDING,
            )
            self._proposals[proposal_id] = record
            self._proposal_by_source_action[source_action_id] = proposal_id
            self._option_committed_by[option_token] = source_action_id
            return self._public_proposal(record)

    def decide(self, proposal_id, acceptor_id, *, accept):
        self._identifier("proposal_id", proposal_id)
        self._identifier("acceptor_id", acceptor_id)
        if type(accept) is not bool:
            raise TypeError("accept must be boolean")
        with self._lock:
            record = self._proposal(proposal_id)
            if acceptor_id not in record.option.required_acceptors:
                raise ValueError("acceptor is not a required proposal participant")
            previous = record.decisions.get(acceptor_id)
            if previous is not None:
                if previous != accept:
                    raise ValueError("acceptor decision cannot be changed")
                return self._public_proposal(record)
            if record.state is not MechanicalProposalState.PENDING:
                raise ValueError("mechanical proposal no longer accepts decisions")
            record.decisions[acceptor_id] = accept
            if not accept:
                record.state = MechanicalProposalState.REJECTED
            elif all(
                record.decisions.get(item) is True
                for item in record.option.required_acceptors
            ):
                record.state = MechanicalProposalState.APPROVED
            return self._public_proposal(record)

    def execute(self, proposal_id):
        """Submit an approved exact affordance through its owning session."""
        self._identifier("proposal_id", proposal_id)
        with self._lock:
            record = self._proposal(proposal_id)
            if record.outcome is not None:
                return record.outcome
            if record.state is not MechanicalProposalState.APPROVED:
                raise ValueError("mechanical proposal is not approved")
            if proposal_id in self._executing:
                raise RuntimeError("mechanical proposal execution is in progress")
            self._executing.add(proposal_id)
            option = record.option
        try:
            target_turn = option.target_session.turn()
            now_ms = self._now()
        except Exception:
            with self._lock:
                self._executing.discard(proposal_id)
            raise
        if (
            target_turn.observation.context != option.affordance.context
            or all(
                item.token != option.affordance.token
                for item in target_turn.affordances
            )
            or now_ms >= option.affordance.expires_at_ms
        ):
            with self._lock:
                record.state = MechanicalProposalState.STALE
                self._executing.discard(proposal_id)
            raise ValueError("approved mechanical proposal became stale")
        try:
            outcome = option.target_session.submit(
                {
                    "request_id": f"mechanical:{proposal_id}",
                    "affordance_token": option.affordance.token,
                    "arguments": to_wire(option.arguments),
                    "expected_revision": option.affordance.context.revision,
                }
            )
        except (TypeError, ValueError):
            with self._lock:
                record.state = MechanicalProposalState.STALE
                self._executing.discard(proposal_id)
            raise
        if not isinstance(outcome, ActionOutcome):
            with self._lock:
                self._executing.discard(proposal_id)
            raise TypeError("target session returned an invalid action outcome")
        with self._lock:
            record.outcome = outcome
            record.state = MechanicalProposalState.SUBMITTED
            self._executing.discard(proposal_id)
            return outcome

    def proposal(self, proposal_id):
        self._identifier("proposal_id", proposal_id)
        with self._lock:
            return self._public_proposal(self._proposal(proposal_id))

    @staticmethod
    def _public_option(option):
        return {
            "proposal_token": option.token,
            "title": option.title,
            "capability": option.affordance.capability,
            "arguments": to_wire(option.arguments),
            "risk": option.affordance.risk.value,
            "reversible": option.affordance.reversible,
            "consequence_warning": option.affordance.consequence_warning,
            "required_acceptors": list(option.required_acceptors),
            "expires_at_ms": option.affordance.expires_at_ms,
        }

    @staticmethod
    def _public_proposal(record):
        return {
            "proposal_id": record.proposal_id,
            "source_action_id": record.source_action_id,
            "title": record.option.title,
            "capability": record.option.affordance.capability,
            "arguments": to_wire(record.option.arguments),
            "required_acceptors": list(record.option.required_acceptors),
            "accepted_by": sorted(
                item for item, accepted in record.decisions.items() if accepted
            ),
            "rejected_by": sorted(
                item for item, accepted in record.decisions.items() if not accepted
            ),
            "state": record.state.value,
            "consequence_warning": record.option.affordance.consequence_warning,
        }

    def _proposal(self, proposal_id):
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise ValueError("unknown mechanical proposal") from exc

    def _now(self):
        value = self._clock_ms()
        if type(value) is not int or value < 0:
            raise ValueError("clock must return a non-negative integer")
        return value

    @staticmethod
    def _identifier(label, value):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 512
            or not value.isprintable()
        ):
            raise ValueError(f"{label} must be 1-512 printable characters")
