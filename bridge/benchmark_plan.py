"""Validate complete faction benchmark plans without starting runtime resources."""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from bridge.agent_host import AgentHostPlan, load_agent_host_plan
from warband_agentic import (
    BenchmarkScenario,
    DecisionBudget,
    ProviderAssignment,
    RoleId,
    benchmark_scenario_from_manifest,
)

BENCHMARK_PLAN_SCHEMA = "warband.agentic/benchmark-plan/v1"
BENCHMARK_PLAN_CHECK_SCHEMA = "warband.agentic/benchmark-plan-check/v1"
_SHA256 = re.compile("[0-9a-f]{64}")


def _exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"{label} fields do not match the benchmark schema")


def _identifier(value, label, *, maximum=200):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or not value.isprintable()
        or any(character in value for character in "\r\n\x00/\\")
    ):
        raise ValueError(f"{label} must be 1-{maximum} safe printable characters")
    return value


def _bounded_integer(name, value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} through {maximum}")
    return value


def _read_config(path):
    target = Path(path).resolve()
    try:
        if target.stat().st_size > 256 * 1024:
            raise ValueError("benchmark configuration exceeds its size limit")
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read benchmark configuration") from exc
    if not isinstance(value, dict):
        raise ValueError("benchmark configuration must contain an object")
    return target, value


def _json_copy(value, label, *, limit=64 * 1024):
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain only finite JSON values") from exc
    if len(encoded.encode()) > limit:
        raise ValueError(f"{label} exceeds its size limit")
    return json.loads(encoded), hashlib.sha256(encoded.encode()).hexdigest()


def _reject_credentials(value, path="run_metadata"):
    blocked = {
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "authorization",
        "bearer_token",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower().replace("-", "_").replace(" ", "_")
            if normalized in blocked:
                raise ValueError(f"run metadata has credential-like field {path}.{key}")
            _reject_credentials(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_credentials(item, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class BenchmarkParticipantPlan:
    faction_id: int
    session_id: str
    assignment: ProviderAssignment

    def diagnostics(self):
        assignment = self.assignment.manifest()
        return {
            "faction_id": self.faction_id,
            "session_id": self.session_id,
            "provider": assignment["provider"],
            "model": assignment["model"],
            "settings": assignment["settings"],
        }


@dataclass(frozen=True, slots=True)
class FactionBenchmarkPlan:
    run_id: str
    host: AgentHostPlan
    scenario: BenchmarkScenario
    participants: tuple[BenchmarkParticipantPlan, ...]
    settlement_party_ids: tuple[int, ...]
    epoch_count: int
    epoch_hours: int
    epoch_speed: int
    budget: DecisionBudget
    run_metadata: dict
    run_metadata_sha256: str

    def diagnostics(self):
        return {
            "schema": BENCHMARK_PLAN_CHECK_SCHEMA,
            "status": "ready",
            "run_id": self.run_id,
            "module": {
                "protocol": self.host.module_protocol,
                "integration_revision": self.host.integration_revision,
            },
            "scenario": self.scenario.manifest(),
            "participants": [item.diagnostics() for item in self.participants],
            "settlement_party_ids": list(self.settlement_party_ids),
            "epochs": {
                "count": self.epoch_count,
                "hours": self.epoch_hours,
                "speed": self.epoch_speed,
            },
            "budget": self.budget.manifest(),
            "run_metadata_sha256": self.run_metadata_sha256,
        }


def load_faction_benchmark_plan(path):
    config_path, config = _read_config(path)
    _exact(
        config,
        (
            "schema",
            "run_id",
            "host_config",
            "scenario",
            "participants",
            "settlement_party_ids",
            "epochs",
            "budget",
            "run_metadata",
        ),
        "benchmark configuration",
    )
    if config["schema"] != BENCHMARK_PLAN_SCHEMA:
        raise ValueError("Unsupported benchmark configuration schema")
    host_value = config["host_config"]
    if (
        not isinstance(host_value, str)
        or not host_value.strip()
        or "\x00" in host_value
    ):
        raise ValueError("host_config must be a non-empty path")
    host_path = Path(host_value)
    if not host_path.is_absolute():
        host_path = config_path.parent / host_path
    host = load_agent_host_plan(host_path)
    scenario = benchmark_scenario_from_manifest(config["scenario"])
    native_metrics = {
        "active_world_parties",
        "military_strength",
        "settlements",
        "surviving",
    }
    if {rule.key for rule in scenario.metrics} != native_metrics:
        raise ValueError(
            "scenario metrics do not match the Native collector metric set"
        )
    sessions = {session.session_id: session for session in host.sessions}

    values = config["participants"]
    if not isinstance(values, list) or not 2 <= len(values) <= 16:
        raise ValueError("participants must contain 2-16 faction assignments")
    participants = []
    seen_sessions = set()
    for index, value in enumerate(values):
        _exact(
            value,
            ("faction_id", "session_id", "provider", "model", "settings"),
            f"participant {index}",
        )
        faction_id = _bounded_integer(
            f"participant {index} faction_id", value["faction_id"], 0, 999_999
        )
        session_id = _identifier(value["session_id"], "participant session_id")
        if session_id in seen_sessions:
            raise ValueError("benchmark participant sessions must be unique")
        try:
            session = sessions[session_id]
        except KeyError as exc:
            raise ValueError("benchmark participant session does not exist") from exc
        definition = host.extensions.application(session.kind)
        if RoleId.FACTION_SOVEREIGN not in definition.roles:
            raise ValueError("benchmark participant session is not faction-sovereign")
        if session.settings.get("faction_id") != faction_id:
            raise ValueError("benchmark participant faction does not match its session")
        seen_sessions.add(session_id)
        participants.append(
            BenchmarkParticipantPlan(
                faction_id,
                session_id,
                ProviderAssignment(
                    value["provider"],
                    value["model"],
                    value["settings"],
                ),
            )
        )
    participants.sort(key=lambda item: item.faction_id)
    if tuple(item.faction_id for item in participants) != scenario.faction_ids:
        raise ValueError("benchmark participants do not match scenario factions")

    settlements = config["settlement_party_ids"]
    if not isinstance(settlements, list) or not 1 <= len(settlements) <= 4096:
        raise ValueError("settlement_party_ids must contain 1-4096 values")
    if any(type(item) is not int or not 0 <= item < 1_000_000 for item in settlements):
        raise ValueError("settlement_party_ids must contain bounded integers")
    if len(settlements) != len(set(settlements)):
        raise ValueError("settlement_party_ids must be unique")

    epochs = config["epochs"]
    _exact(epochs, ("count", "hours", "speed"), "epochs")
    epoch_count = _bounded_integer("epoch count", epochs["count"], 1, 10_000)
    epoch_hours = _bounded_integer("epoch hours", epochs["hours"], 1, 24)
    epoch_speed = _bounded_integer("epoch speed", epochs["speed"], 1, 5)
    budget = config["budget"]
    _exact(
        budget,
        (
            "max_input_tokens",
            "max_output_tokens",
            "timeout_ms",
            "max_cost_microusd",
        ),
        "budget",
    )
    budget_contract = DecisionBudget(**budget)

    metadata, metadata_hash = _json_copy(config["run_metadata"], "run_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("run_metadata must be an object")
    _reject_credentials(metadata)
    required_metadata = {
        "module_sha256",
        "save_sha256",
        "scenario_seed",
        "runner_version",
    }
    if not required_metadata <= set(metadata):
        raise ValueError("run_metadata lacks reproducibility fields")
    for name in ("module_sha256", "save_sha256"):
        if not isinstance(metadata[name], str) or not _SHA256.fullmatch(metadata[name]):
            raise ValueError(f"run_metadata {name} must be a SHA-256 digest")
    _bounded_integer("scenario_seed", metadata["scenario_seed"], 0, 2**63 - 1)
    _identifier(metadata["runner_version"], "runner_version")

    return FactionBenchmarkPlan(
        _identifier(config["run_id"], "run_id"),
        host,
        scenario,
        tuple(participants),
        tuple(settlements),
        epoch_count,
        epoch_hours,
        epoch_speed,
        budget_contract,
        metadata,
        metadata_hash,
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("only --check is available until live benchmark execution ships")
    try:
        plan = load_faction_benchmark_plan(args.config)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    json.dump(plan.diagnostics(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
