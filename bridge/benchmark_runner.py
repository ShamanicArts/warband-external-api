"""Non-blocking composition of benchmark plans, harnesses and provider dispatch."""

from dataclasses import dataclass
from pathlib import Path

from bridge.agent_host import AgentApplicationHost
from bridge.benchmark_plan import FactionBenchmarkPlan
from bridge.campaign_epoch_driver import CampaignEpochDriver
from bridge.campaign_metric_collector import CampaignMetricCollector
from bridge.faction_benchmark_harness import (
    FactionBenchmarkHarness,
    FactionBenchmarkHarnessState,
)
from warband_agentic import (
    AgentPending,
    ProviderDecisionBatch,
    SubprocessDecisionDispatcher,
)

BENCHMARK_RUNNER_STATUS_SCHEMA = "warband.agentic/benchmark-runner-status/v1"


@dataclass(frozen=True, slots=True)
class FactionBenchmarkRunnerStatus:
    state: str
    harness_state: FactionBenchmarkHarnessState
    run_id: str
    epoch_id: str | None
    completed_epochs: int
    target_epochs: int
    provider_dispatch: dict | None
    reason: str | None
    schema: str = BENCHMARK_RUNNER_STATUS_SCHEMA


class FactionBenchmarkRunner:
    """Drive one validated benchmark run one non-blocking poll at a time."""

    _CHECKPOINTABLE = {
        FactionBenchmarkHarnessState.READY,
        FactionBenchmarkHarnessState.DECISIONS,
        FactionBenchmarkHarnessState.RESOLVING,
        FactionBenchmarkHarnessState.ADVANCING,
        FactionBenchmarkHarnessState.METRICS,
    }

    def __init__(
        self,
        plan,
        harness,
        adapters,
        *,
        checkpoint_path=None,
        report_path=None,
        dispatcher_factory=SubprocessDecisionDispatcher,
    ):
        if not isinstance(plan, FactionBenchmarkPlan):
            raise TypeError("plan must be a FactionBenchmarkPlan")
        if not isinstance(harness, FactionBenchmarkHarness):
            raise TypeError("harness must be a FactionBenchmarkHarness")
        if not isinstance(adapters, dict):
            raise TypeError("adapters must be a provider-to-adapter mapping")
        if not callable(dispatcher_factory):
            raise TypeError("dispatcher_factory must be callable")
        if harness.run_id != plan.run_id:
            raise ValueError("runner plan and harness run IDs do not match")
        if harness.scenario.manifest() != plan.scenario.manifest():
            raise ValueError("runner plan and harness scenarios do not match")
        if harness.settlement_party_ids != plan.settlement_party_ids:
            raise ValueError("runner plan and harness settlements do not match")
        if (harness.epoch_hours, harness.epoch_speed) != (
            plan.epoch_hours,
            plan.epoch_speed,
        ):
            raise ValueError("runner plan and harness epoch bounds do not match")
        if harness.run_metadata != plan.run_metadata:
            raise ValueError("runner plan and harness metadata do not match")
        assignments = {item.faction_id: item.assignment for item in plan.participants}
        if set(assignments) != set(plan.scenario.faction_ids):
            raise ValueError("runner participants do not match scenario factions")
        providers = {assignment.provider for assignment in assignments.values()}
        if not providers <= set(adapters):
            raise ValueError("runner lacks an adapter for a participant provider")
        for path, label in (
            (checkpoint_path, "checkpoint"),
            (report_path, "report"),
        ):
            if path is not None:
                target = Path(path)
                if not target.name or not target.parent.is_dir():
                    raise ValueError(f"runner {label} parent directory must exist")

        self.plan = plan
        self.harness = harness
        self.adapters = dict(adapters)
        self.checkpoint_path = (
            Path(checkpoint_path) if checkpoint_path is not None else None
        )
        self.report_path = Path(report_path) if report_path is not None else None
        self._dispatcher_factory = dispatcher_factory
        self._assignments = assignments
        self._dispatcher = None
        self._report = None
        harness_state = harness.status().state
        self._state = (
            "created"
            if harness_state is FactionBenchmarkHarnessState.CREATED
            else "running"
        )
        if harness_state is FactionBenchmarkHarnessState.INTERRUPTED:
            self._state = "interrupted"
        elif harness_state is FactionBenchmarkHarnessState.COMPLETE:
            raise ValueError("runner cannot attach to an already finalized harness")

    def start(self):
        if self._state != "created":
            raise RuntimeError("benchmark runner was already started")
        self.harness.begin()
        self._state = "running"
        return self.status()

    def poll(self):
        if self._state == "created":
            raise RuntimeError("benchmark runner has not started")
        if self._state in {"complete", "interrupted", "closed"}:
            return self.status()

        status = self.harness.status()
        if status.state in {
            FactionBenchmarkHarnessState.BASELINE,
            FactionBenchmarkHarnessState.RESOLVING,
            FactionBenchmarkHarnessState.ADVANCING,
            FactionBenchmarkHarnessState.METRICS,
        }:
            self.harness.poll()
        elif status.state is FactionBenchmarkHarnessState.READY:
            if status.completed_epochs >= self.plan.epoch_count:
                self._report = self.harness.finalize()
                if self.report_path is not None:
                    self.harness.write_report(self.report_path)
                self._state = "complete"
            else:
                epoch_number = status.completed_epochs + 1
                self.harness.start_epoch(f"epoch:{epoch_number}")
        elif status.state is FactionBenchmarkHarnessState.REFRESHING:
            try:
                turns = self.harness.collect_turns()
            except AgentPending:
                return self.status()
            epoch_id = self.harness.status().epoch_id
            batch = ProviderDecisionBatch(
                f"{self.plan.run_id}:batch:{status.completed_epochs + 1}",
                epoch_id,
                turns,
                self._assignments,
                self.plan.budget,
            )
            self.harness.bind_provider_batch(batch)
            self._start_dispatcher(batch)
        elif status.state is FactionBenchmarkHarnessState.DECISIONS:
            if self._dispatcher is None:
                self._start_dispatcher(self.harness.provider_batch())
            dispatch_status = self._dispatcher.poll()
            if dispatch_status["state"] == "complete":
                self.harness.submit_provider_batch()
                self._dispatcher = None
        elif status.state is FactionBenchmarkHarnessState.INTERRUPTED:
            self._state = "interrupted"
        else:
            raise RuntimeError(f"runner cannot poll harness state {status.state.value}")

        current = self.harness.status()
        if current.state is FactionBenchmarkHarnessState.INTERRUPTED:
            self._state = "interrupted"
        self._write_safe_checkpoint()
        return self.status()

    def status(self):
        harness_status = self.harness.status()
        provider_status = (
            self._dispatcher.status() if self._dispatcher is not None else None
        )
        return FactionBenchmarkRunnerStatus(
            self._state,
            harness_status.state,
            self.plan.run_id,
            harness_status.epoch_id,
            harness_status.completed_epochs,
            self.plan.epoch_count,
            provider_status,
            harness_status.reason,
        )

    def report(self):
        if self._state != "complete" or self._report is None:
            raise RuntimeError("benchmark report is not complete")
        return self._report

    def close(self):
        if self._state in {"complete", "interrupted", "closed"}:
            return self.status()
        if self._dispatcher is not None:
            self._dispatcher.close()
            self._dispatcher = None
        self._write_safe_checkpoint()
        self._state = "closed"
        return self.status()

    def _start_dispatcher(self, batch):
        self._dispatcher = self._dispatcher_factory(batch, self.adapters)
        self._dispatcher.start()

    def _write_safe_checkpoint(self):
        if (
            self.checkpoint_path is not None
            and self.harness.status().state in self._CHECKPOINTABLE
        ):
            self.harness.write_checkpoint(self.checkpoint_path)


def build_host_benchmark_runner(
    plan,
    host,
    adapters,
    *,
    checkpoint_path,
    report_path,
    resume=False,
    metric_collector_factory=CampaignMetricCollector,
    advance_driver_factory=CampaignEpochDriver,
    dispatcher_factory=SubprocessDecisionDispatcher,
):
    """Bind one ready application host to a new or restored benchmark runner."""
    if not isinstance(plan, FactionBenchmarkPlan):
        raise TypeError("plan must be a FactionBenchmarkPlan")
    if not isinstance(host, AgentApplicationHost):
        raise TypeError("host must be an AgentApplicationHost")
    if host.plan != plan.host:
        raise ValueError("benchmark plan belongs to another application host")
    if type(resume) is not bool:
        raise TypeError("resume must be a boolean")
    checkpoint = Path(checkpoint_path)
    report = Path(report_path)
    if checkpoint.resolve() == report.resolve():
        raise ValueError("benchmark checkpoint and report paths must differ")
    if not checkpoint.name or not checkpoint.parent.is_dir():
        raise ValueError("benchmark checkpoint parent directory must exist")
    if not report.name or not report.parent.is_dir():
        raise ValueError("benchmark report parent directory must exist")
    if report.exists():
        raise ValueError("benchmark report already exists")
    if resume:
        if not checkpoint.is_file():
            raise ValueError("benchmark resume checkpoint does not exist")
    elif checkpoint.exists():
        raise ValueError("benchmark checkpoint already exists")

    participant_sessions = {
        participant.faction_id: participant.session_id
        for participant in plan.participants
    }
    bindings = host.benchmark_bindings(participant_sessions)
    if resume:
        harness = FactionBenchmarkHarness.load_checkpoint(
            checkpoint,
            bindings.store,
            dict(bindings.applications),
            metric_collector_factory=metric_collector_factory,
            advance_driver_factory=advance_driver_factory,
        )
    else:
        harness = FactionBenchmarkHarness(
            bindings.store,
            plan.run_id,
            plan.scenario,
            dict(bindings.applications),
            settlement_party_ids=plan.settlement_party_ids,
            run_metadata=plan.run_metadata,
            epoch_hours=plan.epoch_hours,
            epoch_speed=plan.epoch_speed,
            metric_collector_factory=metric_collector_factory,
            advance_driver_factory=advance_driver_factory,
        )
    return FactionBenchmarkRunner(
        plan,
        harness,
        adapters,
        checkpoint_path=checkpoint,
        report_path=report,
        dispatcher_factory=dispatcher_factory,
    )
