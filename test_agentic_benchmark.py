import json
import tempfile
import unittest
from pathlib import Path

from warband_agentic import (
    ActionOutcome,
    ActionState,
    ActorKind,
    ActorRef,
    AgentConflict,
    AgentTurn,
    ContextKind,
    ContextRef,
    Evidence,
    EvidenceLevel,
    ObservationEnvelope,
    RoleId,
    SynchronizedFactionEpoch,
)


class FakeSession:
    def __init__(self, faction_id, game_time, calls, reject=False):
        self.faction_id = faction_id
        self.calls = calls
        self.reject = reject
        context = ContextRef(
            ContextKind.CAMPAIGN,
            "campaign:world",
            faction_id,
            None,
            game_time,
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
        if self.reject:
            raise AgentConflict("deliberate invalid decision")
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
                    "test boundary",
                    "queued for deterministic commit",
                ),
            ),
            None,
            1100,
        )
        return self._outcome

    def outcome(self, request_id):
        self.calls.append(("outcome", self.faction_id, request_id))
        if self._outcome is None:
            return None
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
                    "test boundary",
                    "party order read back",
                ),
            ),
            None,
            1200,
        )


class FakeFactionApplication:
    def __init__(self, faction_id, party_ids, game_time, calls, reject=False):
        self.faction_id = faction_id
        self.controlled_party_ids = tuple(party_ids)
        self.session = FakeSession(faction_id, game_time, calls, reject)
        self.calls = calls

    def queue_observation_refresh(self):
        self.calls.append(("refresh", self.faction_id))
        return {
            party_id: self.faction_id * 1000 + party_id
            for party_id in self.controlled_party_ids
        }


class SynchronizedFactionEpochTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.apps = {
            16: FakeFactionApplication(16, (600,), 90, self.calls, reject=True),
            15: FakeFactionApplication(15, (500,), 90, self.calls),
        }
        self.epoch = SynchronizedFactionEpoch(
            "epoch:12",
            self.apps,
            run_metadata={
                "module_hash": "a" * 64,
                "save_hash": "b" * 64,
                "seed": 42,
            },
        )

    def test_refresh_turn_collection_and_commit_are_sorted_and_synchronized(self):
        jobs = self.epoch.queue_observation_refreshes()
        self.assertEqual(list(jobs), [15, 16])
        turns = self.epoch.collect_turns()
        self.assertEqual(list(turns), [15, 16])

        decisions = {
            16: {"request_id": "decision:16"},
            15: {"request_id": "decision:15"},
        }
        records = self.epoch.commit_decisions(decisions)

        submits = [item for item in self.calls if item[0] == "submit"]
        self.assertEqual(
            submits,
            [("submit", 15, "decision:15"), ("submit", 16, "decision:16")],
        )
        self.assertTrue(records[15]["accepted"])
        self.assertFalse(records[16]["accepted"])
        self.assertEqual(records[16]["error_type"], "AgentConflict")

        refreshed = self.epoch.refresh_outcomes()
        self.assertEqual(refreshed[15]["outcome"]["state"], "observed")
        self.epoch.record_campaign_advance(
            {
                "epoch_id": "epoch:12",
                "state": "complete",
                "start_clock": 90,
                "target_clock": 91,
                "current_clock": 91,
                "elapsed_hours": 1,
                "target_reached": True,
                "start_command_status": "acknowledged",
                "stop_command_status": "acknowledged",
                "stop_acknowledged": True,
                "reason": None,
            }
        )

        transcript = self.epoch.transcript()
        self.assertEqual(transcript["epoch_id"], "epoch:12")
        self.assertEqual(transcript["campaign_game_time"], 90)
        self.assertEqual(len(transcript["turn_set_sha256"]), 64)
        self.assertEqual(transcript["campaign_advance"]["state"], "complete")
        self.assertNotIn("application", str(transcript))

        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "epoch-12.json"
            written = self.epoch.write_transcript(artifact)
            self.assertEqual(written, artifact)
            loaded = json.loads(artifact.read_text())
            self.assertEqual(loaded["epoch_id"], "epoch:12")
            self.assertEqual(loaded["turn_set_sha256"], transcript["turn_set_sha256"])
            self.assertEqual(list(loaded["turns"]), ["15", "16"])

    def test_overlapping_party_control_is_rejected(self):
        apps = {
            15: FakeFactionApplication(15, (500,), 90, self.calls),
            16: FakeFactionApplication(16, (500,), 90, self.calls),
        }
        with self.assertRaisesRegex(ValueError, "party 500"):
            SynchronizedFactionEpoch("epoch:bad", apps, run_metadata={})

    def test_different_campaign_times_are_rejected_before_decisions(self):
        apps = {
            15: FakeFactionApplication(15, (500,), 90, self.calls),
            16: FakeFactionApplication(16, (600,), 91, self.calls),
        }
        epoch = SynchronizedFactionEpoch("epoch:bad-time", apps, run_metadata={})
        epoch.queue_observation_refreshes()
        with self.assertRaisesRegex(ValueError, "game time"):
            epoch.collect_turns()

    def test_committed_checkpoint_resumes_without_resubmitting_decisions(self):
        self.epoch.queue_observation_refreshes()
        self.epoch.collect_turns()
        self.epoch.commit_decisions(
            {
                15: {"request_id": "decision:15"},
                16: {"request_id": "decision:16"},
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "epoch-12.checkpoint.json"
            self.epoch.write_checkpoint(checkpoint)
            self.calls.clear()
            resumed = SynchronizedFactionEpoch.load_checkpoint(
                checkpoint, self.apps
            )
            records = resumed.refresh_outcomes()
            self.assertEqual(records[15]["outcome"]["state"], "observed")
            self.assertEqual(
                [call for call in self.calls if call[0] == "submit"], []
            )
            self.assertEqual(
                [call for call in self.calls if call[0] == "outcome"],
                [("outcome", 15, "decision:15")],
            )

            damaged = json.loads(checkpoint.read_text())
            damaged["payload"]["campaign_game_time"] = 91
            checkpoint.write_text(json.dumps(damaged))
            with self.assertRaisesRegex(ValueError, "checksum"):
                SynchronizedFactionEpoch.load_checkpoint(checkpoint, self.apps)


if __name__ == "__main__":
    unittest.main()
