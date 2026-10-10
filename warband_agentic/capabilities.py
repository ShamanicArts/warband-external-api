"""Role-scoped capability discovery and single-use affordance validation."""

import secrets
from dataclasses import dataclass
from threading import RLock
from typing import Mapping

from warband_agentic.contracts import (
    CONTRACT_VERSION,
    ActionSubmission,
    ActorRef,
    Affordance,
    AuthorityClass,
    ContextKind,
    ContextRef,
    ControlLease,
    EvidenceLevel,
    JsonValue,
    RiskClass,
    RoleGrant,
    _freeze_json,
    to_wire,
)


def _nonempty(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _timestamp(name, value):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _active_grant(grant, actor, authority, domain, now_ms):
    if not isinstance(grant, RoleGrant):
        raise TypeError("grant must be a RoleGrant")
    _timestamp("now_ms", now_ms)
    if grant.grantee != actor:
        raise ValueError("Role grant belongs to a different actor")
    if now_ms < grant.issued_at_ms:
        raise ValueError("Role grant is not active yet")
    if grant.expires_at_ms is not None and now_ms >= grant.expires_at_ms:
        raise ValueError("Role grant has expired")
    if authority not in grant.authorities:
        raise ValueError("Role grant lacks required authority")
    if domain not in grant.domains and "*" not in grant.domains:
        raise ValueError("Role grant lacks required domain")


def _type_matches(kind, value):
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": type(value) in (int, float) and type(value) is not bool,
        "string": isinstance(value, str),
        "array": isinstance(value, tuple),
        "object": isinstance(value, Mapping),
    }.get(kind, False)


def _validate_value(schema, value, path):
    expected_type = schema.get("type")
    if expected_type is not None and not _type_matches(expected_type, value):
        raise ValueError(f"{path} must be {expected_type}")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} does not match its required value")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")
    if type(value) in (int, float) and type(value) is not bool:
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path} is below its minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path} is above its maximum")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ValueError(f"{path} is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ValueError(f"{path} is too long")
    if isinstance(value, tuple) and "items" in schema:
        for index, item in enumerate(value):
            _validate_value(schema["items"], item, f"{path}[{index}]")
    if isinstance(value, Mapping):
        _validate_object(schema, value, path)


def _validate_object(schema, value, path="arguments"):
    properties = schema.get("properties", {})
    required = tuple(schema.get("required", ()))
    missing = [name for name in required if name not in value]
    if missing:
        raise ValueError(f"{path} is missing required fields: {', '.join(missing)}")
    extras = set(value) - set(properties)
    if extras and schema.get("additionalProperties", False) is not True:
        raise ValueError(f"{path} has unexpected fields: {', '.join(sorted(extras))}")
    for name, item in value.items():
        if name in properties:
            _validate_value(properties[name], item, f"{path}.{name}")


def _validate_parameter_schema(schema):
    if schema.get("type") != "object" or not isinstance(
        schema.get("properties", {}), Mapping
    ):
        raise ValueError("Capability parameters must use an object schema")
    properties = schema.get("properties", {})
    required = schema.get("required", ())
    if not isinstance(required, tuple) or any(
        not isinstance(name, str) for name in required
    ):
        raise ValueError("Schema required must be an array of strings")
    if set(required) - set(properties):
        raise ValueError("Schema requires an undeclared property")
    if schema.get("additionalProperties", False) not in (False, True):
        raise ValueError("Schema additionalProperties must be boolean")


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    name: str
    description: str
    domain: str
    authority: AuthorityClass
    contexts: tuple[ContextKind, ...]
    parameters: Mapping[str, JsonValue]
    risk: RiskClass
    reversible: bool
    consequence_warning: str | None
    required_evidence: EvidenceLevel
    handler_id: str
    requires_lease: bool = False
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        for name in ("name", "description", "domain", "handler_id"):
            _nonempty(name, getattr(self, name))
        if not isinstance(self.authority, AuthorityClass):
            raise TypeError("authority must be an AuthorityClass")
        contexts = tuple(self.contexts)
        if not contexts or any(
            not isinstance(context, ContextKind) for context in contexts
        ):
            raise TypeError("contexts must contain ContextKind values")
        object.__setattr__(self, "contexts", contexts)
        frozen = _freeze_json(self.parameters, "parameters")
        _validate_parameter_schema(frozen)
        object.__setattr__(self, "parameters", frozen)
        if not isinstance(self.risk, RiskClass):
            raise TypeError("risk must be a RiskClass")
        if type(self.reversible) is not bool or type(self.requires_lease) is not bool:
            raise TypeError("reversible and requires_lease must be booleans")
        if self.consequence_warning is not None:
            _nonempty("consequence_warning", self.consequence_warning)
        if not isinstance(self.required_evidence, EvidenceLevel):
            raise TypeError("required_evidence must be an EvidenceLevel")
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")

    def manifest(self):
        manifest = to_wire(self)
        del manifest["handler_id"]
        return manifest


@dataclass(frozen=True, slots=True)
class ValidatedAction:
    submission: ActionSubmission
    affordance: Affordance
    capability: CapabilityDefinition
    grant_id: str


@dataclass(slots=True)
class _Issued:
    affordance: Affordance
    capability: CapabilityDefinition
    grant_id: str
    consumed_by: str | None = None


class CapabilityRegistry:
    """Register semantic capabilities and issue context-bound action tokens."""

    def __init__(self, token_factory=None, lease_resolver=None):
        self._definitions = {}
        self._issued = {}
        self._action_ids = set()
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(24))
        self._lease_resolver = lease_resolver
        self._lock = RLock()

    def register(self, definition):
        if not isinstance(definition, CapabilityDefinition):
            raise TypeError("definition must be a CapabilityDefinition")
        with self._lock:
            if definition.name in self._definitions:
                raise ValueError(f"Capability already registered: {definition.name}")
            self._definitions[definition.name] = definition

    def discover(self, grant, context, now_ms):
        if not isinstance(grant, RoleGrant) or not isinstance(context, ContextRef):
            raise TypeError("discover requires a RoleGrant and ContextRef")
        _timestamp("now_ms", now_ms)
        if now_ms < grant.issued_at_ms:
            return []
        if grant.expires_at_ms is not None and now_ms >= grant.expires_at_ms:
            return []
        return [
            definition.manifest()
            for definition in sorted(
                self._definitions.values(), key=lambda item: item.name
            )
            if definition.authority in grant.authorities
            and (definition.domain in grant.domains or "*" in grant.domains)
            and context.kind in definition.contexts
        ]

    def issue(
        self,
        capability,
        actor,
        targets,
        context,
        grant,
        issued_at_ms,
        expires_at_ms,
        parameters=None,
    ):
        if not isinstance(actor, ActorRef) or not isinstance(context, ContextRef):
            raise TypeError("issue requires ActorRef and ContextRef values")
        with self._lock:
            definition = self._definitions.get(capability)
            if definition is None:
                raise ValueError("Unknown capability")
            _active_grant(
                grant,
                actor,
                definition.authority,
                definition.domain,
                issued_at_ms,
            )
            if context.kind not in definition.contexts:
                raise ValueError("Capability is invalid in this context")
            if grant.expires_at_ms is not None and expires_at_ms > grant.expires_at_ms:
                raise ValueError("Affordance cannot outlive its role grant")
            issued_parameters = (
                definition.parameters
                if parameters is None
                else _freeze_json(parameters, "parameters")
            )
            _validate_parameter_schema(issued_parameters)
            token = self._token_factory()
            _nonempty("token", token)
            if token in self._issued:
                raise ValueError("Affordance token collision")
            affordance = Affordance(
                token,
                definition.name,
                definition.description,
                actor,
                tuple(targets),
                context,
                definition.authority,
                issued_parameters,
                definition.risk,
                definition.reversible,
                definition.consequence_warning,
                definition.required_evidence,
                issued_at_ms,
                expires_at_ms,
            )
            self._issued[token] = _Issued(affordance, definition, grant.grant_id)
            return affordance

    def consume(self, submission, current_context, grant, now_ms):
        if not isinstance(submission, ActionSubmission) or not isinstance(
            current_context, ContextRef
        ):
            raise TypeError("consume requires ActionSubmission and ContextRef values")
        with self._lock:
            issued = self._issued.get(submission.affordance_token)
            if issued is None:
                raise ValueError("Unknown affordance token")
            affordance, definition = issued.affordance, issued.capability
            if issued.consumed_by is not None:
                raise ValueError("Affordance token was already consumed")
            if submission.action_id in self._action_ids:
                raise ValueError("Action ID was already used")
            if issued.grant_id != grant.grant_id:
                raise ValueError("Affordance belongs to a different role grant")
            _active_grant(
                grant,
                submission.actor,
                definition.authority,
                definition.domain,
                now_ms,
            )
            if now_ms >= affordance.expires_at_ms:
                raise ValueError("Affordance has expired")
            if not affordance.issued_at_ms <= submission.submitted_at_ms <= now_ms:
                raise ValueError(
                    "Submission timestamp is outside the affordance window"
                )
            if submission.actor != affordance.actor:
                raise ValueError("Affordance belongs to a different actor")
            if submission.expected_revision != affordance.context.revision:
                raise ValueError("Submission uses a stale observation revision")
            if current_context != affordance.context:
                raise ValueError("Game context changed after affordance issuance")
            _validate_object(affordance.parameters, submission.arguments)
            if definition.requires_lease:
                if self._lease_resolver is None:
                    raise ValueError(
                        "Capability registry has no trusted lease resolver"
                    )
                if submission.lease_id is None:
                    raise ValueError("Capability requires a control lease ID")
                lease = self._lease_resolver(submission.lease_id, now_ms)
                self._validate_lease(
                    lease, submission.actor, affordance, definition, now_ms
                )
            issued.consumed_by = submission.action_id
            self._action_ids.add(submission.action_id)
            return ValidatedAction(
                submission,
                affordance,
                definition,
                grant.grant_id,
            )

    @staticmethod
    def _validate_lease(lease, actor, affordance, definition, now_ms):
        if not isinstance(lease, ControlLease):
            raise ValueError("Capability requires an active control lease")
        if lease.controller != actor:
            raise ValueError("Control lease belongs to a different controller")
        if now_ms < lease.issued_at_ms or now_ms >= lease.expires_at_ms:
            raise ValueError("Control lease is not active")
        if definition.domain not in lease.domains and "*" not in lease.domains:
            raise ValueError("Control lease lacks required domain")
        if affordance.targets and lease.target not in affordance.targets:
            raise ValueError("Control lease target is outside this affordance")
