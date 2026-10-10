"""Transport- and provider-neutral semantic contracts.

These types describe what an agent may observe or do without exposing bridge
routes, MCP tool names, Warband opcode encoding, or model-provider concepts.
Payload values are recursively copied and frozen so evidence cannot change after
it has been issued or persisted.
"""

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

CONTRACT_VERSION = "warband.agentic/v1"

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


class ActorKind(StrEnum):
    PLAYER = "player"
    AGENT = "agent"
    TROOP = "troop"
    PARTY = "party"
    FACTION = "faction"
    SETTLEMENT = "settlement"
    SYSTEM = "system"


class ContextKind(StrEnum):
    CAMPAIGN = "campaign"
    MENU = "menu"
    TRADE = "trade"
    MISSION = "mission"
    DIALOGUE = "dialogue"
    PRESENTATION = "presentation"


class FactSource(StrEnum):
    ENGINE_OBSERVED = "engine-observed"
    DEFINITION_METADATA = "definition-metadata"
    INFERRED = "inferred"
    APPLICATION_MEMORY = "application-memory"


class EvidenceLevel(StrEnum):
    DECLARED = "declared"
    STRUCTURAL = "structural"
    BRIDGE_SIMULATED = "bridge-simulated"
    ENGINE_ACKNOWLEDGED = "engine-acknowledged"
    ENGINE_OBSERVED = "engine-observed"
    VISUALLY_VERIFIED = "visually-verified"
    AGENT_USABLE = "agent-usable"

    @property
    def rank(self):
        return list(type(self)).index(self) + 1


class RoleId(StrEnum):
    OBSERVER_READONLY = "observer.readonly"
    PLAYER_STRATEGIC = "player.strategic"
    NPC_SELF = "npc.self"
    PARTY_COMMANDER = "party.commander"
    FACTION_SOVEREIGN = "faction.sovereign"
    TEST_DIRECTOR = "test.director"
    OPERATOR_FULL = "operator.full"


class AuthorityClass(StrEnum):
    OBSERVE = "observe"
    ACTOR_CONTROL = "actor-control"
    PARTY_COMMAND = "party-command"
    FACTION_CONTROL = "faction-control"
    TEST_ADMIN = "test-admin"
    OPERATOR = "operator"


class RiskClass(StrEnum):
    READ_ONLY = "read-only"
    REVERSIBLE = "reversible"
    CONSEQUENTIAL = "consequential"
    ADMINISTRATIVE = "administrative"
    DEBUG = "debug"


class ActionState(StrEnum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    DISPATCHED = "dispatched"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INTERRUPTED = "interrupted"
    OBSERVED = "observed"


class LeaseMode(StrEnum):
    EXCLUSIVE = "exclusive"
    SHARED = "shared"


def _nonempty(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _nonnegative(name, value):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _freeze_json(value, path="payload"):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError(f"{path} cannot contain a non-finite float")
        return value
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{path}[{index}]") for index, item in enumerate(value)
        )
    raise TypeError(f"{path} contains non-JSON value {type(value).__name__}")


def _tuple_of(name, value, expected):
    result = tuple(value)
    if any(not isinstance(item, expected) for item in result):
        raise TypeError(f"{name} must contain only {expected.__name__}")
    return result


def to_wire(value: Any):
    """Convert a contract or frozen payload to ordinary JSON-serializable values."""
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_wire(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {key: to_wire(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_wire(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ActorRef:
    runtime_id: str
    kind: ActorKind
    game_id: int | None = None

    def __post_init__(self):
        _nonempty("runtime_id", self.runtime_id)
        if not isinstance(self.kind, ActorKind):
            raise TypeError("kind must be an ActorKind")
        if self.game_id is not None and type(self.game_id) is not int:
            raise TypeError("game_id must be an integer or None")


@dataclass(frozen=True, slots=True)
class ContextRef:
    kind: ContextKind
    scope_id: str
    revision: int
    session_id: str | int | None = None
    game_time: int | float | None = None

    def __post_init__(self):
        if not isinstance(self.kind, ContextKind):
            raise TypeError("kind must be a ContextKind")
        _nonempty("scope_id", self.scope_id)
        _nonnegative("revision", self.revision)
        if self.session_id is not None and type(self.session_id) not in (str, int):
            raise TypeError("session_id must be a string, integer or None")
        if self.game_time is not None and (
            type(self.game_time) not in (int, float)
            or isinstance(self.game_time, bool)
            or not isfinite(self.game_time)
        ):
            raise ValueError("game_time must be a finite number or None")


@dataclass(frozen=True, slots=True)
class Fact:
    key: str
    value: JsonValue
    source: FactSource
    observed_revision: int

    def __post_init__(self):
        _nonempty("key", self.key)
        if not isinstance(self.source, FactSource):
            raise TypeError("source must be a FactSource")
        _nonnegative("observed_revision", self.observed_revision)
        object.__setattr__(self, "value", _freeze_json(self.value, self.key))


@dataclass(frozen=True, slots=True)
class Evidence:
    level: EvidenceLevel
    source: str
    detail: str
    event_sequence: int | None = None

    def __post_init__(self):
        if not isinstance(self.level, EvidenceLevel):
            raise TypeError("level must be an EvidenceLevel")
        _nonempty("source", self.source)
        _nonempty("detail", self.detail)
        if self.event_sequence is not None:
            _nonnegative("event_sequence", self.event_sequence)


@dataclass(frozen=True, slots=True)
class ObservationEnvelope:
    observation_id: str
    actor: ActorRef
    role: RoleId
    context: ContextRef
    facts: tuple[Fact, ...]
    omitted: tuple[str, ...]
    issued_at_ms: int
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        _nonempty("observation_id", self.observation_id)
        if not isinstance(self.actor, ActorRef):
            raise TypeError("actor must be an ActorRef")
        if not isinstance(self.role, RoleId):
            raise TypeError("role must be a RoleId")
        if not isinstance(self.context, ContextRef):
            raise TypeError("context must be a ContextRef")
        object.__setattr__(self, "facts", _tuple_of("facts", self.facts, Fact))
        omitted = tuple(self.omitted)
        if any(not isinstance(item, str) or not item for item in omitted):
            raise ValueError("omitted must contain non-empty strings")
        object.__setattr__(self, "omitted", omitted)
        _nonnegative("issued_at_ms", self.issued_at_ms)
        if any(fact.observed_revision > self.context.revision for fact in self.facts):
            raise ValueError("fact revision cannot exceed observation revision")
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


@dataclass(frozen=True, slots=True)
class Affordance:
    token: str
    capability: str
    description: str
    actor: ActorRef
    targets: tuple[ActorRef, ...]
    context: ContextRef
    authority: AuthorityClass
    parameters: Mapping[str, JsonValue]
    risk: RiskClass
    reversible: bool
    consequence_warning: str | None
    required_evidence: EvidenceLevel
    issued_at_ms: int
    expires_at_ms: int
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        for name in ("token", "capability", "description"):
            _nonempty(name, getattr(self, name))
        if not isinstance(self.actor, ActorRef):
            raise TypeError("actor must be an ActorRef")
        object.__setattr__(
            self, "targets", _tuple_of("targets", self.targets, ActorRef)
        )
        if not isinstance(self.context, ContextRef):
            raise TypeError("context must be a ContextRef")
        if not isinstance(self.authority, AuthorityClass):
            raise TypeError("authority must be an AuthorityClass")
        object.__setattr__(
            self, "parameters", _freeze_json(self.parameters, "parameters")
        )
        if not isinstance(self.risk, RiskClass):
            raise TypeError("risk must be a RiskClass")
        if type(self.reversible) is not bool:
            raise TypeError("reversible must be a boolean")
        if self.consequence_warning is not None:
            _nonempty("consequence_warning", self.consequence_warning)
        if not isinstance(self.required_evidence, EvidenceLevel):
            raise TypeError("required_evidence must be an EvidenceLevel")
        _nonnegative("issued_at_ms", self.issued_at_ms)
        _nonnegative("expires_at_ms", self.expires_at_ms)
        if self.expires_at_ms <= self.issued_at_ms:
            raise ValueError("affordance must expire after it is issued")
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


@dataclass(frozen=True, slots=True)
class ActionSubmission:
    action_id: str
    affordance_token: str
    actor: ActorRef
    arguments: Mapping[str, JsonValue]
    expected_revision: int
    submitted_at_ms: int
    lease_id: str | None = None
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        _nonempty("action_id", self.action_id)
        _nonempty("affordance_token", self.affordance_token)
        if not isinstance(self.actor, ActorRef):
            raise TypeError("actor must be an ActorRef")
        object.__setattr__(self, "arguments", _freeze_json(self.arguments, "arguments"))
        _nonnegative("expected_revision", self.expected_revision)
        _nonnegative("submitted_at_ms", self.submitted_at_ms)
        if self.lease_id is not None:
            _nonempty("lease_id", self.lease_id)
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action_id: str
    state: ActionState
    context: ContextRef
    resulting_revision: int | None
    engine_result: JsonValue
    facts: tuple[Fact, ...]
    evidence: tuple[Evidence, ...]
    reason: str | None
    recorded_at_ms: int
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        _nonempty("action_id", self.action_id)
        if not isinstance(self.state, ActionState):
            raise TypeError("state must be an ActionState")
        if not isinstance(self.context, ContextRef):
            raise TypeError("context must be a ContextRef")
        if self.resulting_revision is not None:
            _nonnegative("resulting_revision", self.resulting_revision)
        object.__setattr__(
            self, "engine_result", _freeze_json(self.engine_result, "engine_result")
        )
        object.__setattr__(self, "facts", _tuple_of("facts", self.facts, Fact))
        object.__setattr__(
            self, "evidence", _tuple_of("evidence", self.evidence, Evidence)
        )
        if self.reason is not None:
            _nonempty("reason", self.reason)
        _nonnegative("recorded_at_ms", self.recorded_at_ms)
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


@dataclass(frozen=True, slots=True)
class GameEvent:
    sequence: int
    event_type: str
    context: ContextRef
    subjects: tuple[ActorRef, ...]
    payload: Mapping[str, JsonValue]
    evidence: Evidence
    occurred_at_ms: int
    cause_action_id: str | None = None
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        _nonnegative("sequence", self.sequence)
        _nonempty("event_type", self.event_type)
        if not isinstance(self.context, ContextRef):
            raise TypeError("context must be a ContextRef")
        object.__setattr__(
            self, "subjects", _tuple_of("subjects", self.subjects, ActorRef)
        )
        object.__setattr__(self, "payload", _freeze_json(self.payload, "payload"))
        if not isinstance(self.evidence, Evidence):
            raise TypeError("evidence must be Evidence")
        _nonnegative("occurred_at_ms", self.occurred_at_ms)
        if self.cause_action_id is not None:
            _nonempty("cause_action_id", self.cause_action_id)
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


@dataclass(frozen=True, slots=True)
class RoleGrant:
    grant_id: str
    role: RoleId
    grantee: ActorRef
    authorities: tuple[AuthorityClass, ...]
    perception_policy: str
    domains: tuple[str, ...]
    issued_at_ms: int
    expires_at_ms: int | None = None
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        _nonempty("grant_id", self.grant_id)
        if not isinstance(self.role, RoleId):
            raise TypeError("role must be a RoleId")
        if not isinstance(self.grantee, ActorRef):
            raise TypeError("grantee must be an ActorRef")
        object.__setattr__(
            self,
            "authorities",
            _tuple_of("authorities", self.authorities, AuthorityClass),
        )
        _nonempty("perception_policy", self.perception_policy)
        domains = tuple(self.domains)
        if any(not isinstance(item, str) or not item for item in domains):
            raise ValueError("domains must contain non-empty strings")
        object.__setattr__(self, "domains", domains)
        _nonnegative("issued_at_ms", self.issued_at_ms)
        if self.expires_at_ms is not None:
            _nonnegative("expires_at_ms", self.expires_at_ms)
            if self.expires_at_ms <= self.issued_at_ms:
                raise ValueError("grant must expire after it is issued")
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


@dataclass(frozen=True, slots=True)
class ControlLease:
    lease_id: str
    controller: ActorRef
    target: ActorRef
    domains: tuple[str, ...]
    mode: LeaseMode
    generation: int
    issued_at_ms: int
    expires_at_ms: int
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        _nonempty("lease_id", self.lease_id)
        if not isinstance(self.controller, ActorRef) or not isinstance(
            self.target, ActorRef
        ):
            raise TypeError("controller and target must be ActorRef values")
        domains = tuple(self.domains)
        if not domains or any(
            not isinstance(item, str) or not item for item in domains
        ):
            raise ValueError("domains must contain non-empty strings")
        object.__setattr__(self, "domains", domains)
        if not isinstance(self.mode, LeaseMode):
            raise TypeError("mode must be a LeaseMode")
        _nonnegative("generation", self.generation)
        _nonnegative("issued_at_ms", self.issued_at_ms)
        _nonnegative("expires_at_ms", self.expires_at_ms)
        if self.expires_at_ms <= self.issued_at_ms:
            raise ValueError("lease must expire after it is issued")
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


def contract_manifest():
    """Return adapter-safe names and values for discovery and compatibility checks."""
    return {
        "schema": CONTRACT_VERSION,
        "roles": [item.value for item in RoleId],
        "authorities": [item.value for item in AuthorityClass],
        "contexts": [item.value for item in ContextKind],
        "fact_sources": [item.value for item in FactSource],
        "evidence_levels": [item.value for item in EvidenceLevel],
        "action_states": [item.value for item in ActionState],
    }
