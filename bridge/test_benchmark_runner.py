import tempfile
import unittest
from pathlib import Path

from bridge.agent_host import AgentApplicationHost, AgentHostPlan
from bridge.application_extensions import built_in_extension_registry
from bridge.benchmark_plan import BenchmarkParticipantPlan, FactionBenchmarkPlan
from bridge.benchmark_runner import (
    FactionBenchmarkRunner,
    build_host_benchmark_runner,
)
from bridge.faction_benchmark_harness import (
    FactionBenchmarkHarness,
    FactionBenchmarkHarnessState,
)
from bridge.test_faction_benchmark_harness import (
    FakeAdvanceDriver,
    FakeFactionApplication,
    FakeMetricCollector,
    metric_snapshot,
)
from warband_agentic import (
    AgentPending,
    BenchmarkScenario,
    DecisionBudget,
    DecisionUsage,
    MetricObjective,
    MetricRule,
    ProviderAssignment,
    SubprocessProviderAdapter,
)


class OneReceiptPerPollDispatcher:
    starts = []

    def __init__(self, batch, _adapters):
        self.batch = batch
        self.state = "created"

    def start(self):
        self.state = "running"
        self.starts.append(self.batch.pending_faction_ids())
        return self.status()

    def poll(self):
        pending = self.batch.pending_faction_ids()
        if pending:
            faction_id = pending[0]
            self.batch.record_success(
                faction_id,
                {"request_id": f"decision:{faction_id}"},
                DecisionUsage(500, 40, 1000, 2_000),
            )
        if not self.batch.pending_faction_ids():
            self.state = "complete"
        return self.status()

    def status(self):
        return {
            "state": self.state,
            "pending_factions": list(self.batch.pending_faction_ids()),
        }

    def close(self):
        self.state = "closed"
        return self.status()


class FactionBenchmarkRunnerTests(unittest.TestCase):
    def setUp(self):
        OneReceiptPerPollDispatcher.starts.clear()
        FakeAdvanceDriver.begins.clear()
        FakeAdvanceDriver.restores.clear()
        self.calls = []
        self.scenario = BenchmarkScenario(
            "two-factions",
            "1.0.0",
            "Two factions maximize evidenced military strength",
            (15, 16),
            (
                MetricRule(
                    "military_strength",
                    "Current active-party member count",
                    "troops",
                    MetricObjective.MAXIMIZE,
                    100,
                    100,
                ),
            ),
        )
        self.apps = {
            15: FakeFactionApplication(15, 500, self.calls),
            16: FakeFactionApplication(16, 600, self.calls),
        }
        self.baseline = metric_snapshot("run:1:baseline", 90, {15: 100, 16: 100})
        self.final = metric_snapshot("run:1:epoch:1:metrics", 91, {15: 125, 16: 90})
        assignments = {
            15: ProviderAssignment("provider-a", "model-a", {}),
            16: ProviderAssignment("provider-b", "model-b", {}),
        }
        self.host_plan = AgentHostPlan(
            None,
            None,
            Path("unused-events.sqlite3"),
            (),
            2,
            16,
            built_in_extension_registry(),
        )
        self.plan = FactionBenchmarkPlan(
            "run:1",
            self.host_plan,
            self.scenario,
            tuple(
                BenchmarkParticipantPlan(
                    faction_id,
                    f"session:{faction_id}",
                    assignments[faction_id],
                )
                for faction_id in self.scenario.faction_ids
            ),
            (1, 2),
            1,
            1,
            2,
            DecisionBudget(1000, 100, 30_000, 10_000),
            {"seed": 42, "runner_version": "test"},
            "a" * 64,
        )
        self.adapters = {
            "provider-a": SubprocessProviderAdapter(("/bin/false",), {}),
            "provider-b": SubprocessProviderAdapter(("/bin/false",), {}),
        }

    def _harness(self):
        def collector_factory(_store, snapshot_id, **_kwargs):
            snapshot = (
                self.baseline if snapshot_id.endswith(":baseline") else self.final
            )
            return FakeMetricCollector(snapshot)

        return FactionBenchmarkHarness(
            object(),
            "run:1",
            self.scenario,
            self.apps,
            settlement_party_ids=(1, 2),
            run_metadata={"seed": 42, "runner_version": "test"},
            epoch_hours=1,
            epoch_speed=2,
            metric_collector_factory=collector_factory,
            advance_driver_factory=FakeAdvanceDriver,
        )

    def test_partial_provider_checkpoint_restarts_only_missing_faction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "run.checkpoint.json"
            report = root / "run.report.json"
            runner = FactionBenchmarkRunner(
                self.plan,
                self._harness(),
                self.adapters,
                checkpoint_path=checkpoint,
                report_path=report,
                dispatcher_factory=OneReceiptPerPollDispatcher,
            )
            runner.start()
            runner.poll()
            runner.poll()
            runner.poll()
            self.assertIs(
                runner.status().harness_state,
                FactionBenchmarkHarnessState.DECISIONS,
            )

            runner.poll()
            self.assertEqual(OneReceiptPerPollDispatcher.starts, [(15, 16)])
            self.assertEqual(
                runner.harness.provider_batch().pending_faction_ids(), (16,)
            )
            self.assertTrue(checkpoint.is_file())

            restored_harness = FactionBenchmarkHarness.load_checkpoint(
                checkpoint,
                object(),
                self.apps,
                metric_collector_factory=lambda _store, snapshot_id, **_kwargs: (
                    FakeMetricCollector(self.final)
                ),
                advance_driver_factory=FakeAdvanceDriver,
            )
            restored = FactionBenchmarkRunner(
                self.plan,
                restored_harness,
                self.adapters,
                checkpoint_path=checkpoint,
                report_path=report,
                dispatcher_factory=OneReceiptPerPollDispatcher,
            )

            for _ in range(20):
                status = restored.poll()
                if status.state == "complete":
                    break

            self.assertEqual(OneReceiptPerPollDispatcher.starts, [(15, 16), (16,)])
            self.assertEqual(status.state, "complete")
            self.assertEqual(restored.report()["epoch_count"], 1)
            self.assertTrue(report.is_file())

    def test_pending_engine_refresh_is_not_misreported_as_failure(self):
        original_turn = self.apps[15].session.turn
        calls = 0

        def pending_once():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise AgentPending("Fresh faction observation is still pending")
            return original_turn()

        self.apps[15].session.turn = pending_once
        runner = FactionBenchmarkRunner(
            self.plan,
            self._harness(),
            self.adapters,
            dispatcher_factory=OneReceiptPerPollDispatcher,
        )
        runner.start()
        runner.poll()
        runner.poll()

        waiting = runner.poll()
        ready = runner.poll()

        self.assertEqual(waiting.state, "running")
        self.assertIs(waiting.harness_state, FactionBenchmarkHarnessState.REFRESHING)
        self.assertIs(ready.harness_state, FactionBenchmarkHarnessState.DECISIONS)

    def test_host_builder_binds_ready_resources_without_launching_any_process(self):
        host = AgentApplicationHost(self.host_plan)
        store = object()
        host._store = store
        host._state = "ready"
        host._applications = {
            "session:15": self.apps[15],
            "session:16": self.apps[16],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "run.checkpoint.json"
            report = root / "run.report.json"
            runner = build_host_benchmark_runner(
                self.plan,
                host,
                self.adapters,
                checkpoint_path=checkpoint,
                report_path=report,
                metric_collector_factory=lambda _store, snapshot_id, **_kwargs: (
                    FakeMetricCollector(
                        self.baseline
                        if snapshot_id.endswith(":baseline")
                        else self.final
                    )
                ),
                advance_driver_factory=FakeAdvanceDriver,
                dispatcher_factory=OneReceiptPerPollDispatcher,
            )

            self.assertEqual(runner.status().state, "created")
            self.assertIs(runner.harness.store, store)
            self.assertEqual(list(runner.harness.applications), [15, 16])
            checkpoint.write_text("occupied")
            with self.assertRaisesRegex(ValueError, "already exists"):
                build_host_benchmark_runner(
                    self.plan,
                    host,
                    self.adapters,
                    checkpoint_path=checkpoint,
                    report_path=report,
                    metric_collector_factory=lambda *_args, **_kwargs: None,
                    advance_driver_factory=FakeAdvanceDriver,
                    dispatcher_factory=OneReceiptPerPollDispatcher,
                )


if __name__ == "__main__":
    unittest.main()
