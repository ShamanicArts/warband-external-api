"""Evidence-gated scenario scoring and canonical faction benchmark reports."""

import hashlib
import hmac
import json
import math
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from warband_agentic.contracts import Evidence, EvidenceLevel, to_wire

SCORECARD_SCHEMA = "warband.agentic/scorecard/v1"
BENCHMARK_RUN_SCHEMA = "warband.agentic/benchmark-run/v1"
BENCHMARK_RUN_CHECKPOINT_SCHEMA = "warband.agentic/benchmark-run-checkpoint/v1"
METRIC_SNAPSHOT_SCHEMA = "warband.agentic/metric-snapshot/v1"
SCENARIO_SCHEMA = "warband.agentic/benchmark-scenario/v1"
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _nonempty(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _number(name, value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _json_copy(value, name):
    try:
        encoded = json.dumps(
            value, allow_nan=False, separators=(",", ":"), sort_keys=True
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only finite JSON values") from exc
    return json.loads(encoded)


def _canonical_hash(value):
    encoded = json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _scenario_from_manifest(value):
    expected = {
        "schema",
        "scenario_id",
        "version",
        "description",
        "faction_ids",
        "metrics",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid benchmark scenario checkpoint")
    metrics = value["metrics"]
    if not isinstance(metrics, list):
        raise ValueError("invalid benchmark scenario metrics checkpoint")
    rules = []
    rule_fields = {"key", "description", "unit", "objective", "weight", "scale"}
    for item in metrics:
        if not isinstance(item, dict) or set(item) != rule_fields:
            raise ValueError("invalid benchmark metric rule checkpoint")
        try:
            objective = MetricObjective(item["objective"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid benchmark metric objective checkpoint") from exc
        rules.append(
            MetricRule(
                item["key"],
                item["description"],
                item["unit"],
                objective,
                item["weight"],
                item["scale"],
            )
        )
    return BenchmarkScenario(
        value["scenario_id"],
        value["version"],
        value["description"],
        tuple(value["faction_ids"]),
        tuple(rules),
        value["schema"],
    )


def _snapshot_from_manifest(value):
    expected = {"schema", "snapshot_id", "game_time", "factions"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid metric snapshot checkpoint")
    factions = value["factions"]
    if not isinstance(factions, dict):
        raise ValueError("invalid metric snapshot factions checkpoint")
    decoded = {}
    for raw_faction_id, items in factions.items():
        try:
            faction_id = int(raw_faction_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid metric snapshot faction ID checkpoint") from exc
        if str(faction_id) != raw_faction_id or faction_id in decoded:
            raise ValueError("invalid metric snapshot faction ID checkpoint")
        if not isinstance(items, list):
            raise ValueError("invalid metric observations checkpoint")
        observations = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                "key",
                "value",
                "evidence",
            }:
                raise ValueError("invalid metric observation checkpoint")
            evidence = item["evidence"]
            if not isinstance(evidence, dict) or set(evidence) != {
                "level",
                "source",
                "detail",
                "event_sequence",
            }:
                raise ValueError("invalid metric evidence checkpoint")
            try:
                level = EvidenceLevel(evidence["level"])
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid metric evidence level checkpoint") from exc
            observations.append(
                MetricObservation(
                    item["key"],
                    item["value"],
                    Evidence(
                        level,
                        evidence["source"],
                        evidence["detail"],
                        evidence["event_sequence"],
                    ),
                )
            )
        decoded[faction_id] = tuple(observations)
    return FactionMetricSnapshot(
        value["snapshot_id"],
        value["game_time"],
        decoded,
        value["schema"],
    )


class MetricObjective(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"
    BINARY = "binary"


@dataclass(frozen=True, slots=True)
class MetricRule:
    key: str
    description: str
    unit: str
    objective: MetricObjective
    weight: int | float
    scale: int | float | None

    def __post_init__(self):
        for name in ("key", "description", "unit"):
            _nonempty(name, getattr(self, name))
        if not isinstance(self.objective, MetricObjective):
            raise TypeError("objective must be a MetricObjective")
        _number("weight", self.weight, positive=True)
        if self.objective is MetricObjective.BINARY:
            if self.scale is not None:
                raise ValueError("binary metrics do not use a scale")
        else:
            _number("scale", self.scale, positive=True)

    def manifest(self):
        return to_wire(self)


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    scenario_id: str
    version: str
    description: str
    faction_ids: tuple[int, ...]
    metrics: tuple[MetricRule, ...]
    schema: str = SCENARIO_SCHEMA

    def __post_init__(self):
        _nonempty("scenario_id", self.scenario_id)
        if not isinstance(self.version, str) or not _SEMVER.fullmatch(self.version):
            raise ValueError("scenario version must use semantic versioning")
        _nonempty("description", self.description)
        factions = tuple(self.faction_ids)
        if len(factions) < 2 or any(
            type(faction_id) is not int or faction_id < 0 for faction_id in factions
        ):
            raise ValueError("scenario requires at least two non-negative factions")
        if len(factions) != len(set(factions)):
            raise ValueError("scenario faction IDs must be unique")
        object.__setattr__(self, "faction_ids", tuple(sorted(factions)))
        metrics = tuple(self.metrics)
        if not metrics or any(not isinstance(rule, MetricRule) for rule in metrics):
            raise TypeError("scenario metrics must contain MetricRule values")
        keys = [rule.key for rule in metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("scenario metric keys must be unique")
        object.__setattr__(self, "metrics", metrics)
        if self.schema != SCENARIO_SCHEMA:
            raise ValueError("unsupported scenario schema")

    def manifest(self):
        return {
            "schema": self.schema,
            "scenario_id": self.scenario_id,
            "version": self.version,
            "description": self.description,
            "faction_ids": list(self.faction_ids),
            "metrics": [rule.manifest() for rule in self.metrics],
        }


@dataclass(frozen=True, slots=True)
class MetricObservation:
    key: str
    value: bool | int | float
    evidence: Evidence

    def __post_init__(self):
        _nonempty("metric key", self.key)
        if type(self.value) not in (bool, int, float) or (
            type(self.value) is float and not math.isfinite(self.value)
        ):
            raise ValueError("metric value must be a finite number or boolean")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("metric evidence must be Evidence")
        if self.evidence.level.rank < EvidenceLevel.ENGINE_OBSERVED.rank:
            raise ValueError("benchmark metrics require engine-observed evidence")

    def manifest(self):
        return {
            "key": self.key,
            "value": self.value,
            "evidence": to_wire(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class FactionMetricSnapshot:
    snapshot_id: str
    game_time: int
    factions: Mapping[int, tuple[MetricObservation, ...]]
    schema: str = METRIC_SNAPSHOT_SCHEMA

    def __post_init__(self):
        _nonempty("snapshot_id", self.snapshot_id)
        if type(self.game_time) is not int or self.game_time < 0:
            raise ValueError("metric snapshot game_time must be non-negative")
        if not isinstance(self.factions, Mapping) or not self.factions:
            raise ValueError("metric snapshot requires faction observations")
        normalized = {}
        for faction_id, observations in self.factions.items():
            if type(faction_id) is not int or faction_id < 0:
                raise ValueError("metric snapshot faction IDs must be non-negative")
            values = tuple(observations)
            if not values or any(
                not isinstance(item, MetricObservation) for item in values
            ):
                raise TypeError(
                    "faction metric observations must contain MetricObservation values"
                )
            keys = [item.key for item in values]
            if len(keys) != len(set(keys)):
                raise ValueError("faction metric keys must be unique")
            normalized[faction_id] = values
        object.__setattr__(
            self, "factions", MappingProxyType(dict(sorted(normalized.items())))
        )
        if self.schema != METRIC_SNAPSHOT_SCHEMA:
            raise ValueError("unsupported metric snapshot schema")

    def manifest(self):
        return {
            "schema": self.schema,
            "snapshot_id": self.snapshot_id,
            "game_time": self.game_time,
            "factions": {
                str(faction_id): [item.manifest() for item in observations]
                for faction_id, observations in self.factions.items()
            },
        }

    def metric_map(self, faction_id):
        try:
            return {item.key: item for item in self.factions[faction_id]}
        except KeyError as exc:
            raise ValueError("metric snapshot does not contain the faction") from exc


def score_scenario(scenario, baseline, final):
    """Score final engine evidence against a baseline under explicit rules."""
    if not isinstance(scenario, BenchmarkScenario):
        raise TypeError("scenario must be a BenchmarkScenario")
    if not isinstance(baseline, FactionMetricSnapshot) or not isinstance(
        final, FactionMetricSnapshot
    ):
        raise TypeError("baseline and final must be FactionMetricSnapshot values")
    expected_factions = set(scenario.faction_ids)
    if set(baseline.factions) != expected_factions or set(final.factions) != (
        expected_factions
    ):
        raise ValueError("metric snapshot factions do not match the scenario")
    if final.game_time < baseline.game_time:
        raise ValueError("final metrics precede the baseline")
    expected_metrics = {rule.key for rule in scenario.metrics}
    rows = {}
    for faction_id in scenario.faction_ids:
        start = baseline.metric_map(faction_id)
        end = final.metric_map(faction_id)
        if set(start) != expected_metrics or set(end) != expected_metrics:
            raise ValueError("metric set does not match the scenario")
        metric_rows = {}
        total = 0.0
        for rule in scenario.metrics:
            before = start[rule.key]
            after = end[rule.key]
            if rule.objective is MetricObjective.BINARY:
                if type(before.value) is not bool or type(after.value) is not bool:
                    raise ValueError("binary metric values must be booleans")
                delta = None
                normalized = 1.0 if after.value else 0.0
            else:
                if type(before.value) not in (int, float) or type(after.value) not in (
                    int,
                    float,
                ):
                    raise ValueError("continuous metric values must be numbers")
                delta = after.value - before.value
                direction = 1 if rule.objective is MetricObjective.MAXIMIZE else -1
                normalized = max(-1.0, min(1.0, direction * delta / rule.scale))
            points = round(float(rule.weight) * normalized, 6)
            total = round(total + points, 6)
            metric_rows[rule.key] = {
                "objective": rule.objective.value,
                "unit": rule.unit,
                "weight": rule.weight,
                "scale": rule.scale,
                "baseline": before.value,
                "final": after.value,
                "delta": delta,
                "normalized": round(normalized, 6),
                "points": points,
                "baseline_evidence": to_wire(before.evidence),
                "final_evidence": to_wire(after.evidence),
            }
        rows[str(faction_id)] = {
            "faction_id": faction_id,
            "total_points": total,
            "metrics": metric_rows,
        }
    ranking = sorted(
        scenario.faction_ids,
        key=lambda faction_id: (-rows[str(faction_id)]["total_points"], faction_id),
    )
    previous_score = None
    previous_rank = 0
    for index, faction_id in enumerate(ranking, start=1):
        score = rows[str(faction_id)]["total_points"]
        rank = previous_rank if score == previous_score else index
        rows[str(faction_id)]["rank"] = rank
        previous_score, previous_rank = score, rank
    inputs = {
        "scenario": scenario.manifest(),
        "baseline": baseline.manifest(),
        "final": final.manifest(),
    }
    return {
        "schema": SCORECARD_SCHEMA,
        "scenario_id": scenario.scenario_id,
        "scenario_version": scenario.version,
        "baseline_snapshot_id": baseline.snapshot_id,
        "final_snapshot_id": final.snapshot_id,
        "baseline_game_time": baseline.game_time,
        "final_game_time": final.game_time,
        "input_sha256": _canonical_hash(inputs),
        "ranking": ranking,
        "factions": rows,
    }


class FactionBenchmarkRun:
    """Accumulate resolved epochs and finalize one canonical scored run."""

    def __init__(self, run_id, scenario, *, run_metadata):
        _nonempty("run_id", run_id)
        if not isinstance(scenario, BenchmarkScenario):
            raise TypeError("scenario must be a BenchmarkScenario")
        self.run_id = run_id
        self.scenario = scenario
        self.run_metadata = _json_copy(run_metadata, "run_metadata")
        self._baseline = None
        self._epochs = []
        self._epoch_ids = set()
        self._report = None

    def set_baseline(self, snapshot):
        if self._report is not None:
            raise RuntimeError("benchmark run is finalized")
        if self._baseline is not None:
            raise RuntimeError("benchmark baseline was already recorded")
        self._validate_snapshot(snapshot)
        self._baseline = snapshot

    def append_epoch(self, transcript, metrics):
        if self._report is not None:
            raise RuntimeError("benchmark run is finalized")
        if self._baseline is None:
            raise RuntimeError("benchmark run requires a baseline")
        self._validate_snapshot(metrics)
        value = _json_copy(transcript, "epoch transcript")
        expected = {
            "schema",
            "epoch_id",
            "state",
            "run_metadata",
            "campaign_game_time",
            "turn_set_sha256",
            "refresh_jobs",
            "turns",
            "decisions",
            "decision_records",
            "campaign_advance",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("invalid benchmark epoch transcript fields")
        if (
            value["schema"] != "warband.agentic/benchmark-epoch/v1"
            or value["state"] != "resolved"
        ):
            raise ValueError("benchmark epoch must be resolved")
        epoch_id = value["epoch_id"]
        _nonempty("epoch_id", epoch_id)
        if epoch_id in self._epoch_ids:
            raise ValueError("benchmark epoch ID is duplicated")
        if value["run_metadata"] != self.run_metadata:
            raise ValueError("benchmark epoch run metadata does not match")
        for field in ("refresh_jobs", "turns", "decisions", "decision_records"):
            self._validate_faction_map(value[field], field.replace("_", " "))
        if not isinstance(value["turn_set_sha256"], str) or not re.fullmatch(
            "[0-9a-f]{64}", value["turn_set_sha256"]
        ):
            raise ValueError("benchmark epoch turn-set hash is invalid")
        if value["turn_set_sha256"] != _canonical_hash(value["turns"]):
            raise ValueError("benchmark epoch turn-set hash does not match")
        if (
            type(value["campaign_game_time"]) is not int
            or value["campaign_game_time"] < 0
        ):
            raise ValueError("benchmark epoch campaign game time is invalid")
        advance = value["campaign_advance"]
        if not isinstance(advance, dict) or (
            advance.get("state") != "complete"
            or advance.get("epoch_id") != epoch_id
            or advance.get("start_clock") != value["campaign_game_time"]
            or advance.get("current_clock") != metrics.game_time
            or advance.get("target_reached") is not True
            or advance.get("stop_acknowledged") is not True
            or advance.get("stop_command_status") != "acknowledged"
        ):
            raise ValueError("benchmark epoch lacks matching advance/metric proof")
        clock_fields = (
            "start_clock",
            "target_clock",
            "current_clock",
            "elapsed_hours",
        )
        if any(type(advance.get(field)) is not int for field in clock_fields) or (
            advance["target_clock"] <= advance["start_clock"]
            or advance["current_clock"] < advance["target_clock"]
            or advance["elapsed_hours"]
            != advance["current_clock"] - advance["start_clock"]
        ):
            raise ValueError("benchmark epoch clock evidence is inconsistent")
        previous_time = (
            self._baseline.game_time
            if not self._epochs
            else self._epochs[-1][1].game_time
        )
        if value["campaign_game_time"] < previous_time or metrics.game_time <= (
            previous_time
        ):
            raise ValueError("benchmark epoch game time is not monotonic")
        self._epoch_ids.add(epoch_id)
        self._epochs.append((value, metrics))

    def report(self):
        if self._baseline is None or not self._epochs:
            raise RuntimeError("benchmark report requires baseline and resolved epochs")
        if self._report is None:
            scorecard = score_scenario(
                self.scenario, self._baseline, self._epochs[-1][1]
            )
            body = {
                "schema": BENCHMARK_RUN_SCHEMA,
                "run_id": self.run_id,
                "scenario": self.scenario.manifest(),
                "run_metadata": self.run_metadata,
                "baseline": self._baseline.manifest(),
                "epoch_count": len(self._epochs),
                "epochs": [
                    {"transcript": transcript, "metrics": metrics.manifest()}
                    for transcript, metrics in self._epochs
                ],
                "scorecard": scorecard,
            }
            self._report = {**body, "report_sha256": _canonical_hash(body)}
        return deepcopy(self._report)

    def write_checkpoint(self, path):
        """Atomically persist an unfinished run without creating a scorecard."""
        wrapper = self.checkpoint()
        target = Path(path)
        if not target.name or not target.parent.is_dir():
            raise ValueError("benchmark checkpoint parent directory must already exist")
        encoded = json.dumps(wrapper, allow_nan=False, indent=2, sort_keys=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(encoded + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target

    def checkpoint(self):
        """Return a checksummed JSON checkpoint for an unfinished run."""
        if self._report is not None:
            raise RuntimeError("finalized benchmark runs do not need checkpoints")
        if self._baseline is None:
            raise RuntimeError("benchmark checkpoint requires a baseline")
        payload = {
            "run_id": self.run_id,
            "scenario": self.scenario.manifest(),
            "run_metadata": self.run_metadata,
            "baseline": self._baseline.manifest(),
            "epochs": [
                {"transcript": transcript, "metrics": metrics.manifest()}
                for transcript, metrics in self._epochs
            ],
        }
        return {
            "schema": BENCHMARK_RUN_CHECKPOINT_SCHEMA,
            "payload_sha256": _canonical_hash(payload),
            "payload": payload,
        }

    @classmethod
    def load_checkpoint(cls, path):
        """Restore a partial run and revalidate every retained epoch."""
        try:
            wrapper = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Cannot read benchmark run checkpoint") from exc
        return cls.from_checkpoint(wrapper)

    @classmethod
    def from_checkpoint(cls, wrapper):
        """Restore a partial run from a decoded checkpoint object."""
        if not isinstance(wrapper, dict) or set(wrapper) != {
            "schema",
            "payload_sha256",
            "payload",
        }:
            raise ValueError("Invalid benchmark run checkpoint fields")
        if wrapper["schema"] != BENCHMARK_RUN_CHECKPOINT_SCHEMA:
            raise ValueError("Unsupported benchmark run checkpoint schema")
        payload = wrapper["payload"]
        if not isinstance(payload, dict) or set(payload) != {
            "run_id",
            "scenario",
            "run_metadata",
            "baseline",
            "epochs",
        }:
            raise ValueError("Invalid benchmark run checkpoint payload")
        checksum = wrapper["payload_sha256"]
        if not isinstance(checksum, str) or not hmac.compare_digest(
            checksum, _canonical_hash(payload)
        ):
            raise ValueError("Benchmark run checkpoint checksum does not match")
        scenario = _scenario_from_manifest(payload["scenario"])
        run = cls(payload["run_id"], scenario, run_metadata=payload["run_metadata"])
        run.set_baseline(_snapshot_from_manifest(payload["baseline"]))
        epochs = payload["epochs"]
        if not isinstance(epochs, list):
            raise ValueError("Invalid benchmark run checkpoint epochs")
        for item in epochs:
            if not isinstance(item, dict) or set(item) != {"transcript", "metrics"}:
                raise ValueError("Invalid benchmark run checkpoint epoch")
            run.append_epoch(
                item["transcript"],
                _snapshot_from_manifest(item["metrics"]),
            )
        return run

    def write_report(self, path):
        target = Path(path)
        if not target.name or not target.parent.is_dir():
            raise ValueError("benchmark report parent directory must already exist")
        payload = json.dumps(self.report(), allow_nan=False, indent=2, sort_keys=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(payload + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target

    def _validate_snapshot(self, snapshot):
        if not isinstance(snapshot, FactionMetricSnapshot):
            raise TypeError("metrics must be a FactionMetricSnapshot")
        if set(snapshot.factions) != set(self.scenario.faction_ids):
            raise ValueError("metric snapshot factions do not match the scenario")

    def _validate_faction_map(self, value, label):
        if not isinstance(value, dict):
            raise ValueError(f"benchmark epoch {label} must be an object")
        try:
            factions = {int(key) for key in value}
        except (TypeError, ValueError) as exc:
            raise ValueError(f"benchmark epoch {label} has invalid factions") from exc
        if len(factions) != len(value) or factions != set(self.scenario.faction_ids):
            raise ValueError(f"benchmark epoch {label} factions do not match")
