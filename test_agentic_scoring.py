import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from warband_agentic import (
    BenchmarkScenario,
    Evidence,
    EvidenceLevel,
    FactionBenchmarkRun,
    FactionMetricSnapshot,
    MetricObjective,
    MetricObservation,
    MetricRule,
    score_scenario,
)


def observed(key, value):
    return MetricObservation(
        key,
        value,
        Evidence(
            EvidenceLevel.ENGINE_OBSERVED,
            "Warband benchmark fixture",
            f"engine getter for {key}",
        ),
    )


def snapshot(snapshot_id, game_time, faction_15, faction_16):
    return FactionMetricSnapshot(
        snapshot_id,
        game_time,
        {
            15: tuple(observed(key, value) for key, value in faction_15.items()),
            16: tuple(observed(key, value) for key, value in faction_16.items()),
        },
    )


class BenchmarkScoringTests(unittest.TestCase):
    def setUp(self):
        self.scenario = BenchmarkScenario(
            "native.border-war",
            "1.0.0",
            "Two-faction territorial survival fixture",
            (15, 16),
            (
                MetricRule(
                    "settlements",
                    "Owned scenario settlements",
                    "count",
                    MetricObjective.MAXIMIZE,
                    40,
                    2,
                ),
                MetricRule(
                    "military_strength",
                    "Observed faction party members",
                    "troops",
                    MetricObjective.MAXIMIZE,
                    30,
                    100,
                ),
                MetricRule(
                    "surviving",
                    "Faction remains active",
                    "boolean",
                    MetricObjective.BINARY,
                    30,
                    None,
                ),
            ),
        )
        self.baseline = snapshot(
            "metrics:start",
            90,
            {"settlements": 4, "military_strength": 500, "surviving": True},
            {"settlements": 4, "military_strength": 500, "surviving": True},
        )
        self.final = snapshot(
            "metrics:end",
            114,
            {"settlements": 6, "military_strength": 650, "surviving": True},
            {"settlements": 2, "military_strength": 300, "surviving": False},
        )
        self.run_metadata = {
            "module_hash": "a" * 64,
            "save_hash": "b" * 64,
            "seed": 42,
            "runner_version": "0.2.0",
        }

    def test_weighted_scorecard_is_bounded_ranked_and_evidence_linked(self):
        scorecard = score_scenario(self.scenario, self.baseline, self.final)

        self.assertEqual(scorecard["schema"], "warband.agentic/scorecard/v1")
        self.assertEqual(scorecard["ranking"], [15, 16])
        self.assertEqual(scorecard["factions"]["15"]["rank"], 1)
        self.assertEqual(scorecard["factions"]["15"]["total_points"], 100.0)
        self.assertEqual(scorecard["factions"]["16"]["rank"], 2)
        self.assertEqual(scorecard["factions"]["16"]["total_points"], -70.0)
        settlement = scorecard["factions"]["15"]["metrics"]["settlements"]
        self.assertEqual(settlement["delta"], 2)
        self.assertEqual(settlement["normalized"], 1.0)
        self.assertEqual(settlement["points"], 40.0)
        self.assertEqual(
            settlement["final_evidence"]["level"], "engine-observed"
        )
        self.assertEqual(len(scorecard["input_sha256"]), 64)

    def test_snapshot_rejects_weak_evidence_and_missing_metric(self):
        with self.assertRaisesRegex(ValueError, "engine-observed"):
            FactionMetricSnapshot(
                "metrics:weak",
                90,
                {
                    15: (
                        MetricObservation(
                            "settlements",
                            4,
                            Evidence(
                                EvidenceLevel.DECLARED,
                                "model claim",
                                "not game evidence",
                            ),
                        ),
                    )
                },
            )

        incomplete = snapshot(
            "metrics:incomplete",
            114,
            {"settlements": 6, "military_strength": 650, "surviving": True},
            {"settlements": 2, "surviving": False},
        )
        with self.assertRaisesRegex(ValueError, "metric set"):
            score_scenario(self.scenario, self.baseline, incomplete)

    def test_run_report_binds_resolved_epochs_metrics_and_canonical_hash(self):
        run = FactionBenchmarkRun(
            "run:border-war:42",
            self.scenario,
            run_metadata=self.run_metadata,
        )
        run.set_baseline(self.baseline)
        turns = {15: {}, 16: {}}
        turn_hash = hashlib.sha256(
            json.dumps(turns, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        epoch = {
            "schema": "warband.agentic/benchmark-epoch/v1",
            "epoch_id": "epoch:1",
            "state": "resolved",
            "run_metadata": self.run_metadata,
            "campaign_game_time": 90,
            "turn_set_sha256": turn_hash,
            "refresh_jobs": {15: {}, 16: {}},
            "turns": turns,
            "decisions": {15: {}, 16: {}},
            "decision_records": {15: {}, 16: {}},
            "campaign_advance": {
                "epoch_id": "epoch:1",
                "state": "complete",
                "start_clock": 90,
                "target_clock": 114,
                "current_clock": 114,
                "elapsed_hours": 24,
                "target_reached": True,
                "stop_command_status": "acknowledged",
                "stop_acknowledged": True,
            },
        }
        malformed = deepcopy(epoch)
        malformed["campaign_advance"]["elapsed_hours"] = 23
        rejected_run = FactionBenchmarkRun(
            "run:border-war:bad",
            self.scenario,
            run_metadata=self.run_metadata,
        )
        rejected_run.set_baseline(self.baseline)
        with self.assertRaisesRegex(ValueError, "clock evidence"):
            rejected_run.append_epoch(malformed, self.final)

        wrong_hash = deepcopy(epoch)
        wrong_hash["turn_set_sha256"] = "d" * 64
        rejected_hash_run = FactionBenchmarkRun(
            "run:border-war:bad-hash",
            self.scenario,
            run_metadata=self.run_metadata,
        )
        rejected_hash_run.set_baseline(self.baseline)
        with self.assertRaisesRegex(ValueError, "turn-set hash"):
            rejected_hash_run.append_epoch(wrong_hash, self.final)

        run.append_epoch(epoch, self.final)

        report = run.report()
        self.assertEqual(report["schema"], "warband.agentic/benchmark-run/v1")
        self.assertEqual(report["run_id"], "run:border-war:42")
        self.assertEqual(report["epoch_count"], 1)
        self.assertEqual(report["scorecard"]["ranking"], [15, 16])
        self.assertEqual(len(report["report_sha256"]), 64)
        encoded = json.dumps(report)
        self.assertNotIn("application", encoded)
        self.assertNotIn("command_id", encoded)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            self.assertEqual(run.write_report(path), path)
            loaded = json.loads(path.read_text())
            self.assertEqual(loaded["report_sha256"], report["report_sha256"])

        with self.assertRaisesRegex(RuntimeError, "finalized"):
            run.append_epoch(epoch, self.final)


if __name__ == "__main__":
    unittest.main()
