import tempfile
import unittest
from pathlib import Path

from bridge.campaign_metric_collector import (
    CampaignMetricCollectionState,
    CampaignMetricCollector,
)
from bridge.game_bridge import Store
from bridge.test_game_bridge import mission_telemetry


def campaign_telemetry(*, ack=0, clock=90):
    return {
        **mission_telemetry(),
        "context": "campaign",
        "scene": "-1",
        "session": "-1",
        "agent": "-1",
        "ack": str(ack),
        "clock": str(clock),
        "build": "16",
    }


class CampaignMetricCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "bridge.sqlite3")
        self.query = campaign_telemetry()
        self.store.poll(self.query)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_collects_paged_world_parties_and_faction_state_at_fixed_clock(self):
        collector = CampaignMetricCollector(
            self.store,
            "metrics:epoch-12",
            faction_ids=(15, 16),
            settlement_party_ids=(1, 2, 3, 4),
        )
        status = collector.begin()
        self.assertIs(status.state, CampaignMetricCollectionState.COLLECTING)
        self.assertEqual(status.game_time, 90)

        rows = [
            {
                "id": party_id,
                "faction": 15 if party_id % 2 else 16,
                "members": party_id * 10,
            }
            for party_id in range(1, 19)
        ]
        faction_states = {15: 0, 16: 1}
        acknowledged = 0
        for _ in range(10):
            response = self.store.poll(
                campaign_telemetry(ack=acknowledged)
            ).split("|")
            command_id = int(response[2])
            if command_id:
                command = self.store.command(command_id)
                if command["kind"] == "scan_campaign":
                    offset = command["arguments"]["offset"]
                    limit = command["arguments"]["limit"]
                    page = rows[offset : offset + limit]
                    for row in page:
                        self.store.event(
                            "/campaign-row",
                            {
                                "v": "2",
                                "job": str(command_id),
                                "dataset": "5",
                                "id": str(row["id"]),
                                "a": str(row["faction"]),
                                "b": "0",
                                "c": "1",
                                "d": str(row["members"]),
                                "e": "0",
                                "f": "0",
                            },
                        )
                    self.store.event(
                        "/campaign-end",
                        {
                            "v": "2",
                            "job": str(command_id),
                            "dataset": "5",
                            "count": str(len(page)),
                            "total": str(len(rows)),
                        },
                    )
                else:
                    faction_id = command["arguments"]["entity_id"]
                    other_id = command["arguments"]["other_id"]
                    self.store.event(
                        "/world-result",
                        {
                            "v": "2",
                            "job": str(command_id),
                            "kind": "1",
                            "id": str(faction_id),
                            "other": str(other_id),
                            "a": "0",
                            "b": str(100 + faction_id),
                            "c": str(faction_states[faction_id]),
                            "d": "0",
                            "e": str(100 + other_id),
                            "f": str(faction_states[other_id]),
                        },
                    )
                acknowledged = command_id
            status = collector.status()
            if status.state is CampaignMetricCollectionState.COMPLETE:
                break

        self.assertIs(status.state, CampaignMetricCollectionState.COMPLETE)
        self.assertEqual(status.pages_complete, 2)
        self.assertEqual(status.faction_queries_complete, 2)
        metrics = collector.snapshot()
        faction_15 = metrics.metric_map(15)
        faction_16 = metrics.metric_map(16)
        self.assertEqual(faction_15["active_world_parties"].value, 9)
        self.assertEqual(faction_16["active_world_parties"].value, 9)
        self.assertEqual(faction_15["military_strength"].value, 810)
        self.assertEqual(faction_16["military_strength"].value, 900)
        self.assertEqual(faction_15["settlements"].value, 2)
        self.assertEqual(faction_16["settlements"].value, 2)
        self.assertTrue(faction_15["surviving"].value)
        self.assertFalse(faction_16["surviving"].value)
        self.assertEqual(
            faction_15["military_strength"].evidence.level.value,
            "engine-observed",
        )

    def test_clock_drift_interrupts_collection_without_a_snapshot(self):
        collector = CampaignMetricCollector(
            self.store,
            "metrics:drift",
            faction_ids=(15, 16),
            settlement_party_ids=(1, 2),
        )
        collector.begin()
        self.store.poll(campaign_telemetry(clock=91))

        status = collector.status()
        self.assertIs(status.state, CampaignMetricCollectionState.INTERRUPTED)
        self.assertIn("clock changed", status.reason)
        with self.assertRaisesRegex(RuntimeError, "not complete"):
            collector.snapshot()


if __name__ == "__main__":
    unittest.main()
