"""Non-blocking orchestration for evidenced multi-faction benchmark runs."""

from dataclasses import dataclass
from enum import StrEnum

from bridge.campaign_epoch_driver import CampaignAdvanceState, CampaignEpochDriver
from bridge.campaign_metric_collector import (
    CampaignMetricCollectionState,
    CampaignMetricCollector,
)
from warband_agentic import (
    BenchmarkEpochState,
    BenchmarkScenario,
    FactionBenchmarkRun,
    SynchronizedFactionEpoch,
    to_wire,
)


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
        self._run.append_epoch(self._epoch.transcript(), snapshot)
        self._completed_epochs += 1
        self._collector = None
        self._epoch = None
        self._driver = None
        self._epoch_id = None
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
