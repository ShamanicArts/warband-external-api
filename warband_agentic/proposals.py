"""Participant-approved mechanical proposals bound to exact affordances."""

import secrets
import threading
import time
from dataclasses import dataclass
from enum import StrEnum

from warband_agentic.capabilities import validate_json_object
from warband_agentic.contracts import (
    ActionOutcome,
    Affordance,
    ContextRef,
    RiskClass,
    to_wire,
)


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

    def __init__(
        self,
        *,
        clock_ms=None,
        token_factory=None,
        proposal_id_factory=None,
        transition_handler=None,
    ):
        if transition_handler is not None and not callable(transition_handler):
            raise TypeError("transition_handler must be callable")
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
        self._archived_proposals = {}
        self._archived_by_source_action = {}
        self._proposal_by_source_action = {}
        self._executing = set()
        self._transition_handler = transition_handler
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
        if not isinstance(required_acceptors, (list, tuple)):
            raise TypeError("required_acceptors must be a list or tuple")
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
            if source_action_id in self._archived_by_source_action:
                raise ValueError("source action has a recovered mechanical proposal")
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
            if (
                proposal_id in self._proposals
                or proposal_id in self._archived_proposals
            ):
                raise ValueError("mechanical proposal ID collision")
            record = _ProposalRecord(
                proposal_id,
                option,
                source_action_id,
                {},
                MechanicalProposalState.PENDING,
            )
            self._emit_transition("committed", record)
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
            decisions = dict(record.decisions)
            decisions[acceptor_id] = accept
            state = record.state
            if not accept:
                state = MechanicalProposalState.REJECTED
            elif all(
                decisions.get(item) is True for item in record.option.required_acceptors
            ):
                state = MechanicalProposalState.APPROVED
            updated = _ProposalRecord(
                record.proposal_id,
                record.option,
                record.source_action_id,
                decisions,
                state,
                record.outcome,
            )
            self._emit_transition(f"decision:{acceptor_id}", updated)
            record.decisions = decisions
            record.state = state
            return self._public_proposal(record)

    def execute(self, proposal_id):
        """Submit an approved exact affordance through its owning session."""
        self._identifier("proposal_id", proposal_id)
        with self._lock:
            record = self._active_proposal(proposal_id)
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
        except Exception:
            with self._lock:
                self._executing.discard(proposal_id)
            raise
        if not isinstance(outcome, ActionOutcome):
            with self._lock:
                self._executing.discard(proposal_id)
            raise TypeError("target session returned an invalid action outcome")
        with self._lock:
            updated = _ProposalRecord(
                record.proposal_id,
                record.option,
                record.source_action_id,
                dict(record.decisions),
                MechanicalProposalState.SUBMITTED,
                outcome,
            )
            try:
                self._emit_transition("submitted", updated, outcome)
            except Exception:
                self._executing.discard(proposal_id)
                raise
            record.outcome = outcome
            record.state = MechanicalProposalState.SUBMITTED
            self._executing.discard(proposal_id)
            return outcome

    def proposal(self, proposal_id):
        self._identifier("proposal_id", proposal_id)
        with self._lock:
            record = self._proposals.get(proposal_id)
            if record is not None:
                return self._public_proposal(record)
            try:
                return to_wire(self._archived_proposals[proposal_id])
            except KeyError as exc:
                raise ValueError("unknown mechanical proposal") from exc

    def proposals(self, source_session_id=None):
        """List committed proposals, optionally scoped to one source session."""
        if source_session_id is not None:
            self._identifier("source_session_id", source_session_id)
        with self._lock:
            records = tuple(self._proposals.values())
            archived = tuple(self._archived_proposals.values())
        proposals = [self._public_proposal(record) for record in records]
        proposals.extend(to_wire(record) for record in archived)
        return tuple(
            record
            for record in sorted(proposals, key=lambda item: item["proposal_id"])
            if source_session_id is None
            or record["source_session_id"] == source_session_id
        )

    def restore(self, proposals):
        """Restore audit manifests while refusing stale authority after restart."""
        manifests = tuple(proposals)
        restored = []
        with self._lock:
            for manifest in manifests:
                value = self._validated_manifest(manifest)
                proposal_id = value["proposal_id"]
                if proposal_id in self._proposals:
                    raise ValueError("mechanical proposal ID collision")
                if value["state"] in (
                    MechanicalProposalState.PENDING.value,
                    MechanicalProposalState.APPROVED.value,
                ):
                    value["state"] = MechanicalProposalState.STALE.value
                previous = self._archived_proposals.get(proposal_id)
                if previous is not None and previous != value:
                    raise ValueError("conflicting recovered mechanical proposal")
                source_action_id = value["source_action_id"]
                previous_id = self._archived_by_source_action.get(source_action_id)
                if previous_id is not None and previous_id != proposal_id:
                    raise ValueError("conflicting recovered proposal source action")
                self._archived_proposals[proposal_id] = value
                self._archived_by_source_action[source_action_id] = proposal_id
                restored.append(to_wire(value))
        return tuple(restored)

    def _emit_transition(self, transition, record, outcome=None):
        if self._transition_handler is not None:
            self._transition_handler(
                transition,
                self._public_proposal(record),
                record.option.source_context,
                outcome,
            )

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
            "source_session_id": record.option.source_session_id,
            "target_session_id": record.option.target_session_id,
            "title": record.option.title,
            "capability": record.option.affordance.capability,
            "arguments": to_wire(record.option.arguments),
            "risk": record.option.affordance.risk.value,
            "reversible": record.option.affordance.reversible,
            "required_acceptors": list(record.option.required_acceptors),
            "accepted_by": sorted(
                item for item, accepted in record.decisions.items() if accepted
            ),
            "rejected_by": sorted(
                item for item, accepted in record.decisions.items() if not accepted
            ),
            "state": record.state.value,
            "consequence_warning": record.option.affordance.consequence_warning,
            "expires_at_ms": record.option.affordance.expires_at_ms,
        }

    def _active_proposal(self, proposal_id):
        if proposal_id in self._archived_proposals:
            raise ValueError("recovered mechanical proposal cannot be changed")
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise ValueError("unknown mechanical proposal") from exc

    def _proposal(self, proposal_id):
        return self._active_proposal(proposal_id)

    def _validated_manifest(self, manifest):
        expected = {
            "proposal_id",
            "source_action_id",
            "source_session_id",
            "target_session_id",
            "title",
            "capability",
            "arguments",
            "risk",
            "reversible",
            "required_acceptors",
            "accepted_by",
            "rejected_by",
            "state",
            "consequence_warning",
            "expires_at_ms",
        }
        if not isinstance(manifest, dict) or set(manifest) != expected:
            raise ValueError("invalid recovered mechanical proposal fields")
        value = to_wire(manifest)
        for field in (
            "proposal_id",
            "source_action_id",
            "source_session_id",
            "target_session_id",
            "title",
            "capability",
            "risk",
            "consequence_warning",
        ):
            self._identifier(field, value[field])
        state = MechanicalProposalState(value["state"])
        RiskClass(value["risk"])
        if not isinstance(value["arguments"], dict):
            raise ValueError("invalid recovered proposal arguments")
        if type(value["reversible"]) is not bool:
            raise ValueError("invalid recovered proposal reversibility")
        if type(value["expires_at_ms"]) is not int or value["expires_at_ms"] < 0:
            raise ValueError("invalid recovered proposal expiry")
        for field in ("required_acceptors", "accepted_by", "rejected_by"):
            entries = value[field]
            if not isinstance(entries, list) or len(set(entries)) != len(entries):
                raise ValueError(f"invalid recovered proposal {field}")
            for entry in entries:
                self._identifier(field, entry)
        required = set(value["required_acceptors"])
        accepted = set(value["accepted_by"])
        rejected = set(value["rejected_by"])
        if (
            not required
            or len(required) > 16
            or not accepted <= required
            or not rejected <= required
            or accepted & rejected
        ):
            raise ValueError("invalid recovered proposal decisions")
        invalid_state = (
            (
                state is MechanicalProposalState.PENDING
                and (bool(rejected) or accepted == required)
            )
            or (
                state
                in (MechanicalProposalState.APPROVED, MechanicalProposalState.SUBMITTED)
                and (bool(rejected) or accepted != required)
            )
            or (state is MechanicalProposalState.REJECTED and not rejected)
        )
        if invalid_state:
            raise ValueError("invalid recovered proposal state")
        return value

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
