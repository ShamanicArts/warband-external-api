"""Non-blocking orchestration for evidenced multi-faction benchmark runs."""

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from bridge.campaign_epoch_driver import CampaignAdvanceState, CampaignEpochDriver
from bridge.campaign_metric_collector import (
    CampaignMetricCollectionState,
    CampaignMetricCollector,
)
from warband_agentic import (
    BenchmarkEpochState,
    BenchmarkScenario,
    FactionBenchmarkRun,
    ProviderDecisionBatch,
    SynchronizedFactionEpoch,
    to_wire,
)
from warband_agentic.provider_decisions import validate_provider_decision_audit


class FactionBenchmarkHarnessState(StrEnum):
    CREATED = "created"
    BASELINE = "collecting-baseline"
    READY = "ready"
    REFRESHING = "refreshing"
    DECISIONS = "awaiting-decisions"
    RESOLVING = "resolving-actions"
    ADVANCING = "advancing-campaign"
    METRICS = "collecting-metrics"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class FactionBenchmarkHarnessStatus:
    state: FactionBenchmarkHarnessState
    run_id: str
    epoch_id: str | None
    completed_epochs: int
    reason: str | None
    schema: str = "warband.agentic/benchmark-harness-status/v1"


class FactionBenchmarkHarness:
    """Coordinate one live campaign run without owning its polling loop."""

    def __init__(
        self,
        store,
        run_id,
        scenario,
        applications,
        *,
        settlement_party_ids,
        run_metadata,
        epoch_hours=1,
        epoch_speed=2,
        metric_collector_factory=CampaignMetricCollector,
        advance_driver_factory=CampaignEpochDriver,
        epoch_factory=SynchronizedFactionEpoch,
    ):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(scenario, BenchmarkScenario):
            raise TypeError("scenario must be a BenchmarkScenario")
        if not isinstance(applications, dict) or set(applications) != set(
            scenario.faction_ids
        ):
            raise ValueError("applications must exactly match scenario factions")
        settlements = tuple(settlement_party_ids)
        if not settlements or any(
            type(party_id) is not int or not 0 <= party_id < 1_000_000
            for party_id in settlements
        ):
            raise ValueError("settlement_party_ids must contain bounded integers")
        if len(settlements) != len(set(settlements)):
            raise ValueError("settlement_party_ids must be unique")
        if type(epoch_hours) is not int or not 1 <= epoch_hours <= 24:
            raise ValueError("epoch_hours must be an integer from 1 through 24")
        if type(epoch_speed) is not int or not 1 <= epoch_speed <= 5:
            raise ValueError("epoch_speed must be an integer from 1 through 5")
        for name, factory in (
            ("metric_collector_factory", metric_collector_factory),
            ("advance_driver_factory", advance_driver_factory),
            ("epoch_factory", epoch_factory),
        ):
            if not callable(factory):
                raise TypeError(f"{name} must be callable")

        self.store = store
        self.run_id = run_id
        self.scenario = scenario
        self.applications = dict(sorted(applications.items()))
        self.settlement_party_ids = settlements
        self.epoch_hours = epoch_hours
        self.epoch_speed = epoch_speed
        self._metric_collector_factory = metric_collector_factory
        self._advance_driver_factory = advance_driver_factory
        self._epoch_factory = epoch_factory
        self._run = FactionBenchmarkRun(
            run_id,
            scenario,
            run_metadata=run_metadata,
        )
        self.run_metadata = self._run.run_metadata
        self.state = FactionBenchmarkHarnessState.CREATED
        self._collector = None
        self._epoch = None
        self._driver = None
        self._epoch_id = None
        self._provider_batch = None
        self._provider_audit = None
        self._completed_epochs = 0
        self._reason = None

    def begin(self):
        """Start fixed-clock baseline collection."""
        if self.state is not FactionBenchmarkHarnessState.CREATED:
            raise RuntimeError("benchmark baseline was already started")
        self._collector = self._new_collector(f"{self.run_id}:baseline")
        self._collector.begin()
        self.state = FactionBenchmarkHarnessState.BASELINE
        return self.status()

    def start_epoch(self, epoch_id):
        """Queue synchronized faction refreshes for one decision epoch."""
        if self.state is not FactionBenchmarkHarnessState.READY:
            if self._epoch_id is not None:
                raise RuntimeError("a benchmark epoch is already active")
            raise RuntimeError("benchmark baseline is not ready")
        self._epoch = self._epoch_factory(
            epoch_id,
            self.applications,
            run_metadata=self.run_metadata,
        )
        self._epoch_id = epoch_id
        jobs = self._epoch.queue_observation_refreshes()
        self.state = FactionBenchmarkHarnessState.REFRESHING
        return jobs

    def collect_turns(self):
        """Freeze the equal-time turn set after the host completes refresh jobs."""
        if self.state is not FactionBenchmarkHarnessState.REFRESHING:
            raise RuntimeError("benchmark turns are not ready for collection")
        turns = self._epoch.collect_turns()
        self.state = FactionBenchmarkHarnessState.DECISIONS
        return turns

    def submit_decisions(self, decisions):
        """Commit exactly one externally obtained decision per faction."""
        if self.state is not FactionBenchmarkHarnessState.DECISIONS:
            raise RuntimeError("benchmark turns are not awaiting decisions")
        records = self._epoch.commit_decisions(decisions)
        self._provider_batch = None
        self._provider_audit = None
        self.state = FactionBenchmarkHarnessState.RESOLVING
        return records

    def bind_provider_batch(self, batch):
        """Bind a partial provider batch to the current frozen turn set."""
        if self.state is not FactionBenchmarkHarnessState.DECISIONS:
            raise RuntimeError("benchmark turns are not awaiting decisions")
        self._validate_provider_batch(batch)
        if self._provider_batch is not None:
            if self._provider_batch.checkpoint() != batch.checkpoint():
                raise ValueError("another provider decision batch is already bound")
            return False
        self._provider_batch = batch
        return True

    def provider_batch(self):
        """Return the bound partial provider batch for dispatch or recovery."""
        if self.state is not FactionBenchmarkHarnessState.DECISIONS:
            raise RuntimeError("benchmark turns are not awaiting decisions")
        if self._provider_batch is None:
            raise RuntimeError("no provider decision batch is bound")
        return self._provider_batch

    def submit_provider_batch(self, batch=None):
        """Commit one complete equal-budget batch and retain its provider audit."""
        if self.state is not FactionBenchmarkHarnessState.DECISIONS:
            raise RuntimeError("benchmark turns are not awaiting decisions")
        if batch is not None:
            self.bind_provider_batch(batch)
        batch = self.provider_batch()
        audit = batch.audit()
        decisions = batch.decisions()
        records = self._epoch.commit_decisions(decisions)
        self._provider_batch = None
        self._provider_audit = audit
        self.state = FactionBenchmarkHarnessState.RESOLVING
        return records

    def poll(self):
        """Advance at most one non-blocking orchestration step."""
        if self.state in (
            FactionBenchmarkHarnessState.BASELINE,
            FactionBenchmarkHarnessState.METRICS,
        ):
            self._poll_metrics()
        elif self.state is FactionBenchmarkHarnessState.RESOLVING:
            self._poll_actions()
        elif self.state is FactionBenchmarkHarnessState.ADVANCING:
            self._poll_advance()
        return self.status()

    def finalize(self):
        """Freeze and return the canonical scored report."""
        if (
            self.state is not FactionBenchmarkHarnessState.READY
            or self._completed_epochs == 0
        ):
            raise RuntimeError("benchmark report requires a resolved epoch")
        report = self._run.report()
        self.state = FactionBenchmarkHarnessState.COMPLETE
        return report

    def write_report(self, path):
        if self.state is not FactionBenchmarkHarnessState.COMPLETE:
            self.finalize()
        return self._run.write_report(path)

    def write_checkpoint(self, path):
        """Atomically retain a safely resumable top-level orchestration state."""
        resumable = {
            FactionBenchmarkHarnessState.READY,
            FactionBenchmarkHarnessState.DECISIONS,
            FactionBenchmarkHarnessState.RESOLVING,
            FactionBenchmarkHarnessState.ADVANCING,
            FactionBenchmarkHarnessState.METRICS,
        }
        if self.state not in resumable:
            raise RuntimeError("benchmark harness state is not safely resumable")
        epoch = self._epoch.checkpoint() if self._epoch is not None else None
        driver = (
            self._driver.checkpoint()
            if self.state is FactionBenchmarkHarnessState.ADVANCING
            else None
        )
        payload = {
            "run_id": self.run_id,
            "state": self.state.value,
            "epoch_id": self._epoch_id,
            "epoch_hours": self.epoch_hours,
            "epoch_speed": self.epoch_speed,
            "settlement_party_ids": list(self.settlement_party_ids),
            "run": self._run.checkpoint(),
            "epoch": epoch,
            "driver": driver,
            "provider_batch": (
                self._provider_batch.checkpoint()
                if self._provider_batch is not None
                else None
            ),
            "provider_audit": self._provider_audit,
        }
        wrapper = {
            "schema": "warband.agentic/benchmark-harness-checkpoint/v3",
            "payload_sha256": self._canonical_hash(payload),
            "payload": payload,
        }
        target = Path(path)
        if not target.name or not target.parent.is_dir():
            raise ValueError("harness checkpoint parent directory must already exist")
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

    @classmethod
    def load_checkpoint(
        cls,
        path,
        store,
        applications,
        *,
        metric_collector_factory=CampaignMetricCollector,
        advance_driver_factory=CampaignEpochDriver,
        epoch_factory=SynchronizedFactionEpoch,
    ):
        """Restore safe state without replaying decisions or campaign waits."""
        try:
            wrapper = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Cannot read benchmark harness checkpoint") from exc
        if not isinstance(wrapper, dict) or set(wrapper) != {
            "schema",
            "payload_sha256",
            "payload",
        }:
            raise ValueError("Invalid benchmark harness checkpoint fields")
        if wrapper["schema"] not in {
            "warband.agentic/benchmark-harness-checkpoint/v2",
            "warband.agentic/benchmark-harness-checkpoint/v3",
        }:
            raise ValueError("Unsupported benchmark harness checkpoint schema")
        payload = wrapper["payload"]
        expected = {
            "run_id",
            "state",
            "epoch_id",
            "epoch_hours",
            "epoch_speed",
            "settlement_party_ids",
            "run",
            "epoch",
            "driver",
            "provider_audit",
        }
        if wrapper["schema"].endswith("/v3"):
            expected.add("provider_batch")
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("Invalid benchmark harness checkpoint payload")
        checksum = wrapper["payload_sha256"]
        if not isinstance(checksum, str) or not hmac.compare_digest(
            checksum, cls._canonical_hash(payload)
        ):
            raise ValueError("Benchmark harness checkpoint checksum does not match")
        try:
            state = FactionBenchmarkHarnessState(payload["state"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid benchmark harness checkpoint state") from exc
        if state not in {
            FactionBenchmarkHarnessState.READY,
            FactionBenchmarkHarnessState.DECISIONS,
            FactionBenchmarkHarnessState.RESOLVING,
            FactionBenchmarkHarnessState.ADVANCING,
            FactionBenchmarkHarnessState.METRICS,
        }:
            raise ValueError("Benchmark harness checkpoint is not safely resumable")
        run = FactionBenchmarkRun.from_checkpoint(payload["run"])
        if run.run_id != payload["run_id"]:
            raise ValueError("Benchmark harness run ID does not match run checkpoint")
        harness = cls(
            store,
            payload["run_id"],
            run.scenario,
            applications,
            settlement_party_ids=tuple(payload["settlement_party_ids"]),
            run_metadata=run.run_metadata,
            epoch_hours=payload["epoch_hours"],
            epoch_speed=payload["epoch_speed"],
            metric_collector_factory=metric_collector_factory,
            advance_driver_factory=advance_driver_factory,
            epoch_factory=epoch_factory,
        )
        harness._run = run
        harness._completed_epochs = len(payload["run"]["payload"]["epochs"])
        harness.state = state
        harness._epoch_id = payload["epoch_id"]
        harness._provider_audit = payload["provider_audit"]
        provider_batch_checkpoint = payload.get("provider_batch")
        if state is FactionBenchmarkHarnessState.READY:
            if any(
                value is not None
                for value in (
                    payload["epoch_id"],
                    payload["epoch"],
                    payload["driver"],
                    provider_batch_checkpoint,
                    payload["provider_audit"],
                )
            ):
                raise ValueError("Ready harness checkpoint contains active state")
            return harness
        if not isinstance(payload["epoch_id"], str) or not payload["epoch_id"].strip():
            raise ValueError("Active harness checkpoint has no epoch ID")
        if payload["epoch"] is None:
            raise ValueError("Active harness checkpoint has no epoch state")
        restore_epoch = getattr(epoch_factory, "from_checkpoint", None)
        if not callable(restore_epoch):
            raise ValueError("Harness epoch factory cannot restore checkpoints")
        harness._epoch = restore_epoch(payload["epoch"], applications)
        if harness._epoch.epoch_id != payload["epoch_id"]:
            raise ValueError("Harness and epoch checkpoint IDs do not match")
        if harness._epoch.run_metadata != run.run_metadata:
            raise ValueError("Harness and epoch run metadata do not match")
        if state is not FactionBenchmarkHarnessState.DECISIONS:
            if provider_batch_checkpoint is not None:
                raise ValueError("Later harness checkpoint contains provider batch")
        elif payload["driver"] is not None or payload["provider_audit"] is not None:
            raise ValueError("Decision harness checkpoint contains later state")
        if provider_batch_checkpoint is not None:
            restored_batch = ProviderDecisionBatch.from_checkpoint(
                provider_batch_checkpoint
            )
            harness.bind_provider_batch(restored_batch)
        if harness._provider_audit is not None:
            transcript = harness._epoch.transcript()
            harness._provider_audit = validate_provider_decision_audit(
                harness._provider_audit,
                epoch_id=harness._epoch_id,
                faction_ids=harness.scenario.faction_ids,
                turn_set_sha256=transcript["turn_set_sha256"],
                decisions=transcript["decisions"],
            )
        if state is FactionBenchmarkHarnessState.DECISIONS:
            if harness._epoch.state is not BenchmarkEpochState.COLLECTING:
                raise ValueError("Decision harness epoch has no frozen turn set")
        elif state is FactionBenchmarkHarnessState.RESOLVING:
            if payload["driver"] is not None:
                raise ValueError("Resolving harness checkpoint contains a driver")
        elif state is FactionBenchmarkHarnessState.ADVANCING:
            if harness._epoch.state is not BenchmarkEpochState.RESOLVED:
                raise ValueError("Advancing harness epoch is not resolved")
            restore = getattr(advance_driver_factory, "restore", None)
            if not callable(restore) or payload["driver"] is None:
                raise ValueError(
                    "Advancing harness checkpoint has no restorable driver"
                )
            harness._driver = restore(store, payload["driver"])
            if harness._driver.epoch_id != harness._epoch_id:
                raise ValueError("Harness and driver checkpoint IDs do not match")
        else:
            if harness._epoch.state is not BenchmarkEpochState.RESOLVED:
                raise ValueError("Metric harness epoch is not resolved")
            if payload["driver"] is not None:
                raise ValueError("Metric harness checkpoint contains an active driver")
            advance = harness._epoch.transcript()["campaign_advance"]
            if not isinstance(advance, dict) or advance.get("state") != "complete":
                raise ValueError("Metric harness checkpoint lacks campaign advance")
            harness._collector = harness._new_collector(
                f"{harness.run_id}:{harness._epoch_id}:metrics"
            )
            harness._collector.begin()
        return harness

    def status(self):
        return FactionBenchmarkHarnessStatus(
            self.state,
            self.run_id,
            self._epoch_id,
            self._completed_epochs,
            self._reason,
        )

    def _new_collector(self, snapshot_id):
        return self._metric_collector_factory(
            self.store,
            snapshot_id,
            faction_ids=self.scenario.faction_ids,
            settlement_party_ids=self.settlement_party_ids,
        )

    def _poll_metrics(self):
        status = self._collector.status()
        if status.state is CampaignMetricCollectionState.INTERRUPTED:
            self._interrupt(status.reason or "Metric collection was interrupted")
            return
        if status.state is not CampaignMetricCollectionState.COMPLETE:
            return
        snapshot = self._collector.snapshot()
        if self.state is FactionBenchmarkHarnessState.BASELINE:
            self._run.set_baseline(snapshot)
            self._collector = None
            self.state = FactionBenchmarkHarnessState.READY
            return
        self._run.append_epoch(
            self._epoch.transcript(),
            snapshot,
            provider_audit=self._provider_audit,
        )
        self._completed_epochs += 1
        self._collector = None
        self._epoch = None
        self._driver = None
        self._epoch_id = None
        self._provider_batch = None
        self._provider_audit = None
        self.state = FactionBenchmarkHarnessState.READY

    def _poll_actions(self):
        self._epoch.refresh_outcomes()
        if self._epoch.state is not BenchmarkEpochState.RESOLVED:
            return
        self._driver = self._advance_driver_factory(self.store, self._epoch_id)
        self._driver.begin(hours=self.epoch_hours, speed=self.epoch_speed)
        self.state = FactionBenchmarkHarnessState.ADVANCING

    def _poll_advance(self):
        status = self._driver.status()
        if status.state is CampaignAdvanceState.TARGET_REACHED:
            self._driver.request_stop()
            return
        if status.state in (
            CampaignAdvanceState.INTERRUPTED,
            CampaignAdvanceState.FAILED,
        ):
            self._interrupt(status.reason or f"Campaign advance {status.state.value}")
            return
        if status.state is not CampaignAdvanceState.COMPLETE:
            return
        self._epoch.record_campaign_advance(to_wire(status))
        self._collector = self._new_collector(f"{self.run_id}:{self._epoch_id}:metrics")
        self._collector.begin()
        self.state = FactionBenchmarkHarnessState.METRICS

    def _interrupt(self, reason):
        self._reason = reason
        self.state = FactionBenchmarkHarnessState.INTERRUPTED

    def _validate_provider_batch(self, batch):
        if not isinstance(batch, ProviderDecisionBatch):
            raise TypeError("batch must be a ProviderDecisionBatch")
        transcript = self._epoch.transcript()
        tasks = batch.tasks()
        if set(tasks) != set(self.scenario.faction_ids):
            raise ValueError("provider decision batch uses another faction set")
        for task in tasks.values():
            if task["epoch_id"] != self._epoch_id:
                raise ValueError("provider decision batch belongs to another epoch")
            if task["turn_set_sha256"] != transcript["turn_set_sha256"]:
                raise ValueError("provider decision batch uses another turn set")

    @staticmethod
    def _canonical_hash(value):
        encoded = json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
