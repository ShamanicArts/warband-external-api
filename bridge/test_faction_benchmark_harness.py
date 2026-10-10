import unittest

from bridge.campaign_epoch_driver import (
    CampaignAdvanceState,
    CampaignAdvanceStatus,
)
from bridge.campaign_metric_collector import (
    CampaignMetricCollectionState,
    CampaignMetricCollectionStatus,
)
from bridge.faction_benchmark_harness import (
    FactionBenchmarkHarness,
    FactionBenchmarkHarnessState,
)
from warband_agentic import (
    ActionOutcome,
    ActionState,
    ActorKind,
    ActorRef,
    AgentTurn,
    BenchmarkScenario,
    ContextKind,
    ContextRef,
    Evidence,
    EvidenceLevel,
    FactionMetricSnapshot,
    MetricObjective,
    MetricObservation,
    MetricRule,
    ObservationEnvelope,
    RoleId,
)


def metric_snapshot(snapshot_id, game_time, values):
    evidence = Evidence(
        EvidenceLevel.ENGINE_OBSERVED,
        "test engine getter",
        "A fixed-clock metric was read from the engine",
    )
    return FactionMetricSnapshot(
        snapshot_id,
        game_time,
        {
            faction_id: (MetricObservation("military_strength", value, evidence),)
            for faction_id, value in values.items()
        },
    )


class FakeMetricCollector:
    def __init__(self, snapshot, *, interrupted=False):
        self._snapshot = snapshot
        self._interrupted = interrupted
        self.begun = False

    def begin(self):
        self.begun = True
        return CampaignMetricCollectionStatus(
            CampaignMetricCollectionState.COLLECTING,
            self._snapshot.snapshot_id,
            self._snapshot.game_time,
            0,
            0,
            None,
        )

    def status(self):
        state = (
            CampaignMetricCollectionState.INTERRUPTED
            if self._interrupted
            else CampaignMetricCollectionState.COMPLETE
        )
        return CampaignMetricCollectionStatus(
            state,
            self._snapshot.snapshot_id,
            self._snapshot.game_time,
            1,
            2,
            "Campaign clock drifted" if self._interrupted else None,
        )

    def snapshot(self):
        return self._snapshot


class FakeAdvanceDriver:
    def __init__(self, _store, epoch_id):
        self.epoch_id = epoch_id
        self.stop_requested = False

    def _status(self, state):
        complete = state is CampaignAdvanceState.COMPLETE
        reached = state in (
            CampaignAdvanceState.TARGET_REACHED,
            CampaignAdvanceState.STOPPING,
            CampaignAdvanceState.COMPLETE,
        )
        return CampaignAdvanceStatus(
            self.epoch_id,
            state,
            90,
            91,
            91 if reached else 90,
            1 if reached else 0,
            reached,
            "acknowledged",
            "acknowledged" if complete else ("queued" if self.stop_requested else None),
            complete,
            None,
        )

    def begin(self, *, hours, speed):
        if (hours, speed) != (1, 2):
            raise AssertionError("harness changed the configured epoch bounds")
        return self._status(CampaignAdvanceState.STARTING)

    def status(self):
        return self._status(
            CampaignAdvanceState.COMPLETE
            if self.stop_requested
            else CampaignAdvanceState.TARGET_REACHED
        )

    def request_stop(self):
        self.stop_requested = True
        return self._status(CampaignAdvanceState.STOPPING)


class FakeSession:
    def __init__(self, faction_id, calls):
        self.faction_id = faction_id
        self.calls = calls
        context = ContextRef(
            ContextKind.CAMPAIGN,
            "campaign:world",
            faction_id,
            None,
            90,
        )
        actor = ActorRef(f"controller:{faction_id}", ActorKind.SYSTEM)
        observation = ObservationEnvelope(
            f"observation:{faction_id}",
            actor,
            RoleId.FACTION_SOVEREIGN,
            context,
            (),
            (),
            1000,
        )
        self._turn = AgentTurn(f"session:{faction_id}", observation, (), (), 0)
        self._outcome = None

    def turn(self):
        self.calls.append(("turn", self.faction_id))
        return self._turn

    def submit(self, request):
        self.calls.append(("submit", self.faction_id, request["request_id"]))
        self._outcome = ActionOutcome(
            f"action:{self.faction_id}",
            ActionState.ACCEPTED,
            self._turn.observation.context,
            None,
            {"status": "queued"},
            (),
            (
                Evidence(
                    EvidenceLevel.DECLARED,
                    "test queue",
                    "The decision was queued",
                ),
            ),
            None,
            1100,
        )
        return self._outcome

    def outcome(self, request_id):
        self.calls.append(("outcome", self.faction_id, request_id))
        return ActionOutcome(
            self._outcome.action_id,
            ActionState.OBSERVED,
            self._outcome.context,
            self._outcome.context.revision + 1,
            {"status": "acknowledged"},
            (),
            (
                Evidence(
                    EvidenceLevel.ENGINE_OBSERVED,
                    "test read-back",
                    "The order was read back",
                ),
            ),
            None,
            1200,
        )


class FakeFactionApplication:
    def __init__(self, faction_id, party_id, calls):
        self.faction_id = faction_id
        self.controlled_party_ids = (party_id,)
        self.session = FakeSession(faction_id, calls)
        self.calls = calls

    def queue_observation_refresh(self):
        self.calls.append(("refresh", self.faction_id))
        return {self.controlled_party_ids[0]: self.faction_id * 100}


class FactionBenchmarkHarnessTests(unittest.TestCase):
    def setUp(self):
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

    def _harness(self, *, interrupted_baseline=False):
        def collector_factory(_store, snapshot_id, **_kwargs):
            snapshot = (
                self.baseline if snapshot_id.endswith(":baseline") else self.final
            )
            return FakeMetricCollector(
                snapshot,
                interrupted=interrupted_baseline and snapshot is self.baseline,
            )

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

    def test_orchestrates_baseline_decisions_advance_metrics_and_report(self):
        harness = self._harness()

        self.assertIs(harness.begin().state, FactionBenchmarkHarnessState.BASELINE)
        self.assertIs(harness.poll().state, FactionBenchmarkHarnessState.READY)
        jobs = harness.start_epoch("epoch:1")
        self.assertEqual(list(jobs), [15, 16])
        turns = harness.collect_turns()
        self.assertEqual(list(turns), [15, 16])
        records = harness.submit_decisions(
            {
                15: {"request_id": "decision:15"},
                16: {"request_id": "decision:16"},
            }
        )
        self.assertTrue(records[15]["accepted"])
        self.assertTrue(records[16]["accepted"])

        self.assertIs(harness.poll().state, FactionBenchmarkHarnessState.ADVANCING)
        self.assertIs(harness.poll().state, FactionBenchmarkHarnessState.ADVANCING)
        self.assertIs(harness.poll().state, FactionBenchmarkHarnessState.METRICS)
        self.assertIs(harness.poll().state, FactionBenchmarkHarnessState.READY)

        report = harness.finalize()
        self.assertEqual(report["epoch_count"], 1)
        self.assertEqual(report["epochs"][0]["metrics"]["game_time"], 91)
        self.assertEqual(report["scorecard"]["ranking"], [15, 16])
        self.assertIs(harness.status().state, FactionBenchmarkHarnessState.COMPLETE)
        self.assertEqual(
            [call for call in self.calls if call[0] == "submit"],
            [("submit", 15, "decision:15"), ("submit", 16, "decision:16")],
        )

    def test_metric_interruption_stops_the_run_without_fabricating_baseline(self):
        harness = self._harness(interrupted_baseline=True)
        harness.begin()

        status = harness.poll()

        self.assertIs(status.state, FactionBenchmarkHarnessState.INTERRUPTED)
        self.assertEqual(status.reason, "Campaign clock drifted")
        with self.assertRaisesRegex(RuntimeError, "ready"):
            harness.start_epoch("epoch:forbidden")
        with self.assertRaisesRegex(RuntimeError, "resolved epoch"):
            harness.finalize()

    def test_state_machine_refuses_overlapping_epochs_and_early_decisions(self):
        harness = self._harness()
        with self.assertRaisesRegex(RuntimeError, "baseline"):
            harness.start_epoch("epoch:early")
        harness.begin()
        harness.poll()
        harness.start_epoch("epoch:1")

        with self.assertRaisesRegex(RuntimeError, "active"):
            harness.start_epoch("epoch:2")
        with self.assertRaisesRegex(RuntimeError, "turns"):
            harness.submit_decisions({})


if __name__ == "__main__":
    unittest.main()
