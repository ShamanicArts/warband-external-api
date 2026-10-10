"""Secret-safe configuration for trusted subprocess provider wrappers."""

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from warband_agentic import SubprocessProviderAdapter

SUBPROCESS_ADAPTER_CONFIG_SCHEMA = "warband.agentic/subprocess-adapters/v1"
SUBPROCESS_ADAPTER_CHECK_SCHEMA = "warband.agentic/subprocess-adapters-check/v1"
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_CREDENTIAL_ARGUMENTS = {
    "--api-key",
    "--auth-token",
    "--authorization",
    "--credential",
    "--password",
    "--secret",
    "--token",
}


def _provider_name(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 200
        or not value.isprintable()
        or any(character in value for character in "\r\n\x00/\\")
    ):
        raise ValueError("provider must be 1-200 safe printable characters")
    return value


@dataclass(frozen=True, slots=True)
class SubprocessAdapterRegistry:
    adapters: Mapping[str, SubprocessProviderAdapter] = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, "adapters", MappingProxyType(dict(self.adapters)))

    def diagnostics(self):
        return {
            "schema": SUBPROCESS_ADAPTER_CHECK_SCHEMA,
            "status": "ready",
            "providers": sorted(self.adapters),
        }


def load_subprocess_adapter_config(path, *, required_providers=(), environ=None):
    """Load argv and selected environment values without serializing secrets."""
    target = Path(path).resolve()
    try:
        if target.stat().st_size > 256 * 1024:
            raise ValueError("provider adapter configuration exceeds its size limit")
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read provider adapter configuration") from exc
    if not isinstance(value, dict) or set(value) != {"schema", "adapters"}:
        raise ValueError("provider adapter configuration fields do not match")
    if value["schema"] != SUBPROCESS_ADAPTER_CONFIG_SCHEMA:
        raise ValueError("Unsupported provider adapter configuration schema")
    entries = value["adapters"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
        raise ValueError("provider adapters must contain 1-16 entries")
    source_environment = os.environ if environ is None else environ
    if not isinstance(source_environment, Mapping):
        raise TypeError("environ must be a mapping")

    adapters = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
            "provider",
            "argv",
            "pass_environment",
        }:
            raise ValueError(f"provider adapter {index} fields do not match")
        provider = _provider_name(entry["provider"])
        if provider in adapters:
            raise ValueError("provider adapter names must be unique")
        argv = entry["argv"]
        if not isinstance(argv, list) or not 1 <= len(argv) <= 64:
            raise ValueError("provider adapter argv must contain 1-64 values")
        executable = argv[0]
        if not isinstance(executable, str) or not executable or "\x00" in executable:
            raise ValueError("provider adapter executable is invalid")
        executable_path = Path(executable)
        if not executable_path.is_absolute():
            executable_path = target.parent / executable_path
        executable_path = executable_path.resolve()
        if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
            raise ValueError("provider adapter executable is not an executable file")
        resolved_argv = [str(executable_path), *argv[1:]]
        for argument in resolved_argv[1:]:
            if isinstance(argument, str) and any(
                argument.lower() == blocked
                or argument.lower().startswith(blocked + "=")
                for blocked in _CREDENTIAL_ARGUMENTS
            ):
                raise ValueError(
                    "provider adapter credentials must use pass_environment"
                )

        names = entry["pass_environment"]
        if not isinstance(names, list) or len(names) > 64:
            raise ValueError("pass_environment must contain at most 64 names")
        if any(not isinstance(name, str) for name in names):
            raise ValueError("provider adapter environment variable name is invalid")
        if len(names) != len(set(names)):
            raise ValueError("pass_environment names must be unique")
        environment = {}
        for name in names:
            if not isinstance(name, str) or not _ENVIRONMENT_NAME.fullmatch(name):
                raise ValueError(
                    "provider adapter environment variable name is invalid"
                )
            environment_value = source_environment.get(name)
            if not isinstance(environment_value, str):
                raise ValueError(
                    f"provider adapter environment variable {name} is unavailable"
                )
            environment[name] = environment_value
        adapters[provider] = SubprocessProviderAdapter(
            tuple(resolved_argv),
            environment,
        )

    required = {_provider_name(provider) for provider in required_providers}
    missing = sorted(required - set(adapters))
    if missing:
        raise ValueError(
            "provider adapter configuration lacks required provider " + missing[0]
        )
    return SubprocessAdapterRegistry(adapters)
