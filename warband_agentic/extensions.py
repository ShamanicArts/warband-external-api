"""Trusted Python extension declarations and constrained backend composition.

Installed extension code runs with the host process's authority and is not a
sandbox boundary. This module instead makes compatibility, resource ownership,
configuration and game-operation access explicit and reviewable before an
untrusted agent is attached to the resulting constrained session.
"""

import re
from dataclasses import dataclass, field
from importlib import metadata
from types import MappingProxyType
from typing import Mapping

from warband_agentic.agent_api import ConstrainedAgentSession
from warband_agentic.capabilities import validate_json_object, validate_object_schema
from warband_agentic.contracts import (
    CONTRACT_VERSION,
    RoleId,
    _freeze_json,
    to_wire,
)

EXTENSION_SCHEMA = "warband.agentic/extension/v1"
EXTENSION_CATALOG_SCHEMA = "warband.agentic/extensions/v1"
EXTENSION_ENTRY_POINT_GROUP = "warband_agentic.extensions"
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)+$")


def _nonempty(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _unique_strings(name, values):
    result = tuple(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{name} must contain non-empty strings")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    return result


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    """One exact builder/runtime resource owned by an extension."""

    namespace: str
    identifier: str | int

    def __post_init__(self):
        _nonempty("resource namespace", self.namespace)
        if type(self.identifier) is int:
            if self.identifier < 0:
                raise ValueError("numeric resource identifiers must be non-negative")
        elif not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("resource identifier must be a string or integer")

    def manifest(self):
        return {"namespace": self.namespace, "identifier": self.identifier}


@dataclass(frozen=True, slots=True)
class OwnershipRule:
    """Derive an exclusive host-level ownership claim from application settings."""

    namespace: str
    setting: str | None = None
    constant: str | int | None = None
    many: bool = False

    def __post_init__(self):
        _nonempty("ownership namespace", self.namespace)
        if (self.setting is None) == (self.constant is None):
            raise ValueError("ownership requires exactly one setting or constant")
        if self.setting is not None:
            _nonempty("ownership setting", self.setting)
        if self.constant is not None and (
            type(self.constant) not in (str, int)
            or (isinstance(self.constant, str) and not self.constant.strip())
        ):
            raise ValueError("ownership constant must be a string or integer")
        if type(self.many) is not bool:
            raise TypeError("ownership many must be boolean")

    def resolve(self, settings):
        value = self.constant if self.setting is None else settings[self.setting]
        values = value if self.many else (value,)
        if self.many and not isinstance(values, tuple):
            raise ValueError("multi-value ownership setting must be an array")
        claims = []
        for item in values:
            if type(item) not in (str, int) or (
                isinstance(item, str) and not item.strip()
            ):
                raise ValueError("ownership values must be strings or integers")
            claims.append((self.namespace, str(item)))
        if len(claims) != len(set(claims)):
            raise ValueError("application ownership claims must be unique")
        return tuple(claims)

    def manifest(self):
        body = {"namespace": self.namespace, "many": self.many}
        body["setting" if self.setting is not None else "constant"] = (
            self.setting if self.setting is not None else self.constant
        )
        return body


@dataclass(frozen=True, slots=True)
class ApplicationKind:
    """Public declaration for one constrained application factory."""

    kind: str
    description: str
    settings_schema: Mapping
    roles: tuple[RoleId, ...]
    capabilities: tuple[str, ...]
    backend_operations: tuple[str, ...]
    ownership: tuple[OwnershipRule, ...]
    refreshable: bool

    def __post_init__(self):
        if not isinstance(self.kind, str) or not _IDENTIFIER.fullmatch(self.kind):
            raise ValueError("application kind must be a namespaced identifier")
        _nonempty("application description", self.description)
        schema = validate_object_schema(self.settings_schema)
        if schema.get("additionalProperties", False):
            raise ValueError("application settings must reject additional properties")
        object.__setattr__(self, "settings_schema", schema)
        roles = tuple(self.roles)
        if not roles or any(not isinstance(role, RoleId) for role in roles):
            raise TypeError("application roles must contain RoleId values")
        if len(roles) != len(set(roles)):
            raise ValueError("application roles must be unique")
        object.__setattr__(self, "roles", roles)
        object.__setattr__(
            self,
            "capabilities",
            _unique_strings("application capabilities", self.capabilities),
        )
        object.__setattr__(
            self,
            "backend_operations",
            _unique_strings("backend operations", self.backend_operations),
        )
        ownership = tuple(self.ownership)
        if any(not isinstance(rule, OwnershipRule) for rule in ownership):
            raise TypeError("ownership must contain OwnershipRule values")
        properties = schema.get("properties", {})
        required = set(schema.get("required", ()))
        for rule in ownership:
            if rule.setting is not None and (
                rule.setting not in properties or rule.setting not in required
            ):
                raise ValueError("ownership settings must be required schema fields")
        object.__setattr__(self, "ownership", ownership)
        if type(self.refreshable) is not bool:
            raise TypeError("refreshable must be boolean")

    def manifest(self):
        return {
            "kind": self.kind,
            "description": self.description,
            "settings_schema": to_wire(self.settings_schema),
            "roles": [role.value for role in self.roles],
            "capabilities": list(self.capabilities),
            "backend_operations": list(self.backend_operations),
            "ownership": [rule.manifest() for rule in self.ownership],
            "refreshable": self.refreshable,
        }


@dataclass(frozen=True, slots=True)
class AgenticExtension:
    """Versioned declaration loaded by an explicitly trusted host launcher."""

    extension_id: str
    version: str
    description: str
    protocol: int
    integration_revision_min: int
    integration_revision_max: int
    applications: tuple[ApplicationKind, ...]
    resources: tuple[ResourceClaim, ...] = ()
    contract_schema: str = CONTRACT_VERSION
    schema: str = EXTENSION_SCHEMA

    def __post_init__(self):
        if not isinstance(self.extension_id, str) or not _IDENTIFIER.fullmatch(
            self.extension_id
        ):
            raise ValueError("extension_id must be a namespaced identifier")
        if not isinstance(self.version, str) or not _SEMVER.fullmatch(self.version):
            raise ValueError("extension version must be semantic versioning")
        _nonempty("extension description", self.description)
        if type(self.protocol) is not int or self.protocol <= 0:
            raise ValueError("extension protocol must be a positive integer")
        revisions = (self.integration_revision_min, self.integration_revision_max)
        if any(type(value) is not int or value < 0 for value in revisions):
            raise ValueError("integration revisions must be non-negative integers")
        if self.integration_revision_min > self.integration_revision_max:
            raise ValueError("integration revision range is inverted")
        applications = tuple(self.applications)
        if not applications or any(
            not isinstance(item, ApplicationKind) for item in applications
        ):
            raise TypeError("applications must contain ApplicationKind values")
        kinds = [item.kind for item in applications]
        if len(kinds) != len(set(kinds)):
            raise ValueError("extension application kinds must be unique")
        object.__setattr__(self, "applications", applications)
        resources = tuple(self.resources)
        if any(not isinstance(item, ResourceClaim) for item in resources):
            raise TypeError("resources must contain ResourceClaim values")
        keys = [(item.namespace, item.identifier) for item in resources]
        if len(keys) != len(set(keys)):
            raise ValueError("extension resource claims must be unique")
        object.__setattr__(self, "resources", resources)
        if self.contract_schema != CONTRACT_VERSION:
            raise ValueError("extension contract schema is incompatible")
        if self.schema != EXTENSION_SCHEMA:
            raise ValueError("extension schema is incompatible")

    def manifest(self):
        return {
            "schema": self.schema,
            "extension_id": self.extension_id,
            "version": self.version,
            "description": self.description,
            "contract_schema": self.contract_schema,
            "compatibility": {
                "protocol": self.protocol,
                "integration_revision": {
                    "minimum": self.integration_revision_min,
                    "maximum": self.integration_revision_max,
                },
            },
            "applications": [item.manifest() for item in self.applications],
            "resources": [item.manifest() for item in self.resources],
        }


@dataclass(frozen=True, slots=True)
class ExtensionBundle:
    """One installed extension declaration plus its trusted private callables."""

    extension: AgenticExtension
    factories: Mapping
    settings_validators: Mapping = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.extension, AgenticExtension):
            raise TypeError("extension bundle requires an AgenticExtension")
        for name, value in (
            ("factories", self.factories),
            ("settings_validators", self.settings_validators),
        ):
            if not isinstance(value, Mapping):
                raise TypeError(f"extension bundle {name} must be a mapping")
            object.__setattr__(self, name, MappingProxyType(dict(value)))

    def register(self, registry):
        if not isinstance(registry, ExtensionRegistry):
            raise TypeError("registry must be an ExtensionRegistry")
        registry.register(
            self.extension,
            self.factories,
            self.settings_validators,
        )


class ScopedGameBackend:
    """Expose Store reads and only the operations declared by an app kind."""

    def __init__(self, store, operations):
        required = ("snapshot", "enqueue_operation", "command")
        if any(not callable(getattr(store, name, None)) for name in required):
            raise TypeError("game backend does not provide the required Store surface")
        self._store = store
        self._operations = frozenset(_unique_strings("backend operations", operations))
        self.module_catalog = _freeze_json(
            getattr(store, "module_catalog", {}), "module catalog"
        )

    def snapshot(self):
        return self._store.snapshot()

    def menu_options(self):
        if "select_menu" not in self._operations:
            raise PermissionError("menu reads were not declared by this application")
        return self._store.menu_options()

    def enqueue_operation(self, kind, arguments):
        if kind not in self._operations:
            raise PermissionError(f"backend operation {kind!r} was not declared")
        return self._store.enqueue_operation(kind, arguments)

    def command(self, command_id):
        command = self._store.command(command_id)
        self._check_command(command)
        return command

    def _result(self, method, command_id):
        self.command(command_id)
        callback = getattr(self._store, method, None)
        if not callable(callback):
            raise TypeError(f"game backend does not provide {method}()")
        return callback(command_id)

    def scan_result(self, command_id):
        return self._result("scan_result", command_id)

    def dialogue_result(self, command_id):
        return self._result("dialogue_result", command_id)

    def world_result(self, command_id):
        return self._result("world_result", command_id)

    def _check_command(self, command):
        if (
            not isinstance(command, Mapping)
            or command.get("kind") not in self._operations
        ):
            raise PermissionError(
                "command operation was not declared by this application"
            )


class ExtensionRegistry:
    """Atomic registry of declarations, trusted factories and private validators."""

    def __init__(self, *, protocol, integration_revision):
        if type(protocol) is not int or protocol <= 0:
            raise ValueError("protocol must be a positive integer")
        if type(integration_revision) is not int or integration_revision < 0:
            raise ValueError("integration_revision must be non-negative")
        self.protocol = protocol
        self.integration_revision = integration_revision
        self._extensions = {}
        self._applications = {}
        self._resource_owners = {}

    def register(self, extension, factories, settings_validators=None):
        if not isinstance(extension, AgenticExtension):
            raise TypeError("extension must be an AgenticExtension")
        if extension.protocol != self.protocol:
            raise ValueError("extension protocol is incompatible with this host")
        if not (
            extension.integration_revision_min
            <= self.integration_revision
            <= extension.integration_revision_max
        ):
            raise ValueError("extension integration revision is incompatible")
        if extension.extension_id in self._extensions:
            raise ValueError("extension ID is already registered")
        if not isinstance(factories, Mapping):
            raise TypeError("factories must be a mapping")
        expected = {item.kind for item in extension.applications}
        if set(factories) != expected or any(
            not callable(factory) for factory in factories.values()
        ):
            raise ValueError("factories must exactly match declared application kinds")
        validators = dict(settings_validators or {})
        if set(validators) - expected or any(
            not callable(validator) for validator in validators.values()
        ):
            raise ValueError("settings validators must match application kinds")
        collisions = expected & set(self._applications)
        if collisions:
            raise ValueError(
                "application kind collision: " + ", ".join(sorted(collisions))
            )
        for claim in extension.resources:
            key = (claim.namespace, claim.identifier)
            if key in self._resource_owners:
                raise ValueError(
                    "resource claim collision with " + self._resource_owners[key]
                )

        self._extensions[extension.extension_id] = extension
        for definition in extension.applications:
            self._applications[definition.kind] = (
                extension,
                definition,
                factories[definition.kind],
                validators.get(definition.kind),
            )
        for claim in extension.resources:
            self._resource_owners[(claim.namespace, claim.identifier)] = (
                extension.extension_id
            )

    def application(self, kind):
        if not isinstance(kind, str):
            raise ValueError("unsupported application kind")
        try:
            return self._applications[kind][1]
        except KeyError as exc:
            raise ValueError("unsupported application kind") from exc

    def extension_for(self, kind):
        if not isinstance(kind, str):
            raise ValueError("unsupported application kind")
        try:
            return self._applications[kind][0]
        except KeyError as exc:
            raise ValueError("unsupported application kind") from exc

    def validate_settings(self, kind, settings):
        definition = self.application(kind)
        validated = validate_json_object(
            definition.settings_schema, settings, f"{kind} settings"
        )
        validator = self._applications[kind][3]
        if validator is not None:
            validator(validated)
        return validated

    def control_claims(self, kind, settings):
        definition = self.application(kind)
        settings = self.validate_settings(kind, settings)
        claims = []
        for rule in definition.ownership:
            claims.extend(rule.resolve(settings))
        return tuple(claims)

    def create(self, kind, store, session_id, event_log, settings):
        extension, definition, factory, _ = self._applications.get(
            kind, (None, None, None, None)
        )
        if extension is None:
            raise ValueError("unsupported application kind")
        validated = self.validate_settings(kind, settings)
        backend = ScopedGameBackend(store, definition.backend_operations)
        application = factory(
            backend,
            session_id,
            event_log=event_log,
            **to_wire(validated),
        )
        if not isinstance(
            getattr(application, "session", None), ConstrainedAgentSession
        ):
            raise TypeError("application factory must expose a constrained session")
        supports_refresh = callable(
            getattr(application, "queue_observation_refresh", None)
        )
        if supports_refresh != definition.refreshable:
            raise TypeError(
                "application refresh behavior does not match its declaration"
            )
        return application

    def catalog(self):
        return {
            "schema": EXTENSION_CATALOG_SCHEMA,
            "contract_schema": CONTRACT_VERSION,
            "protocol": self.protocol,
            "integration_revision": self.integration_revision,
            "extensions": [
                extension.manifest()
                for extension in sorted(
                    self._extensions.values(), key=lambda item: item.extension_id
                )
            ],
        }

    def summaries(self):
        return tuple(
            {
                "extension_id": extension.extension_id,
                "version": extension.version,
            }
            for extension in sorted(
                self._extensions.values(), key=lambda item: item.extension_id
            )
        )


def load_named_extension_entry_points(registry, names):
    """Load only explicitly named installed extension bundles into a registry."""
    if not isinstance(registry, ExtensionRegistry):
        raise TypeError("registry must be an ExtensionRegistry")
    requested = tuple(names)
    if len(requested) > 32 or any(
        not isinstance(name, str) or not name.strip() for name in requested
    ):
        raise ValueError("extension names must contain at most 32 non-empty values")
    if len(requested) != len(set(requested)):
        raise ValueError("extension names must be unique")
    available = metadata.entry_points(group=EXTENSION_ENTRY_POINT_GROUP)
    by_name = {}
    for entry_point in available:
        by_name.setdefault(entry_point.name, []).append(entry_point)
    for name in requested:
        matches = by_name.get(name, ())
        if not matches:
            raise ValueError(f"Requested extension {name} is not installed")
        if len(matches) != 1:
            raise ValueError(f"Requested extension {name} is ambiguous")
        try:
            provider = matches[0].load()
            if not callable(provider):
                raise TypeError("extension entry point must be callable")
            bundle = provider()
        except Exception as exc:
            raise ValueError(f"Cannot load requested extension {name}") from exc
        if not isinstance(bundle, ExtensionBundle):
            raise ValueError(f"Requested extension {name} returned no bundle")
        if bundle.extension.extension_id != name:
            raise ValueError(f"Requested extension {name} declared another ID")
        bundle.register(registry)
    return registry
