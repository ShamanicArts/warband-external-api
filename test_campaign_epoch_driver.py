import tempfile
import unittest
from pathlib import Path

from bridge.campaign_epoch_driver import CampaignAdvanceState, CampaignEpochDriver
from bridge.game_bridge import Store


def campaign_telemetry(ack=0, result=0, clock=90, context="campaign"):
    return {
        "v": "2",
        "context": context,
        "ack": str(ack),
        "gold": "355",
        "troop": "0",
        "hp": "0",
        "x": "0",
        "y": "0",
        "z": "0",
        "clock": str(clock),
        "scene": "-1",
        "session": "-1",
        "agent": "-1",
        "result": str(result),
        "build": "16",
        "menu": "23" if context == "menu" else "-1",
        "menu-session": "4" if context == "menu" else "0",
        "dialogue": "0",
        "captive": "0",
    }


class CampaignEpochDriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "bridge.sqlite3")
        self.query = campaign_telemetry()
        self.store.poll(self.query)
        self.driver = CampaignEpochDriver(self.store, "epoch:12")

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_elapsed_engine_time_and_acknowledged_stop_complete_epoch(self):
        started = self.driver.begin(hours=1, speed=2)
        self.assertIs(started.state, CampaignAdvanceState.STARTING)
        self.assertEqual(started.start_clock, 90)
        self.assertEqual(started.target_clock, 91)

        fields = self.store.poll(self.query).split("|")
        start_command_id = int(fields[2])
        self.assertEqual(fields[3:7], ["16", "1", "2", "0"])
        self.store.poll(campaign_telemetry(ack=start_command_id, clock=90))
        advancing = self.driver.status()
        self.assertIs(advancing.state, CampaignAdvanceState.ADVANCING)
        self.assertFalse(advancing.target_reached)

        self.store.poll(campaign_telemetry(clock=91))
        reached = self.driver.status()
        self.assertIs(reached.state, CampaignAdvanceState.TARGET_REACHED)
        self.assertTrue(reached.target_reached)

        stopping = self.driver.request_stop()
        self.assertIs(stopping.state, CampaignAdvanceState.STOPPING)
        fields = self.store.poll(campaign_telemetry(clock=91)).split("|")
        stop_command_id = int(fields[2])
        self.assertEqual(fields[3:7], ["16", "0", "1", "0"])
        self.store.poll(campaign_telemetry(ack=stop_command_id, clock=91))

        completed = self.driver.status()
        self.assertIs(completed.state, CampaignAdvanceState.COMPLETE)
        self.assertEqual(completed.elapsed_hours, 1)
        self.assertTrue(completed.stop_acknowledged)

    def test_checkpoint_restores_existing_wait_without_starting_another(self):
        self.driver.begin(hours=1, speed=2)
        checkpoint = self.driver.checkpoint()
        restored = CampaignEpochDriver.restore(self.store, checkpoint)

        self.assertEqual(restored.checkpoint(), checkpoint)
        command_count = self.store.db.execute(
            "SELECT count(*) FROM commands"
        ).fetchone()[0]
        fields = self.store.poll(self.query).split("|")
        start_command_id = int(fields[2])
        self.assertEqual(start_command_id, checkpoint["start_command_id"])
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM commands").fetchone()[0],
            command_count,
        )

        self.store.poll(campaign_telemetry(ack=start_command_id, clock=91))
        self.assertIs(restored.status().state, CampaignAdvanceState.TARGET_REACHED)
        restored.request_stop()
        stop_checkpoint = restored.checkpoint()
        restored = CampaignEpochDriver.restore(self.store, stop_checkpoint)
        before_repeat_stop = self.store.db.execute(
            "SELECT count(*) FROM commands"
        ).fetchone()[0]
        restored.request_stop()
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM commands").fetchone()[0],
            before_repeat_stop,
        )
        stop_command_id = int(
            self.store.poll(campaign_telemetry(clock=91)).split("|")[2]
        )
        self.store.poll(campaign_telemetry(ack=stop_command_id, clock=91))
        self.assertIs(restored.status().state, CampaignAdvanceState.COMPLETE)


if __name__ == "__main__":
    unittest.main()
