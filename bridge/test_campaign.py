import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.test_game_bridge import mission_telemetry


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bridge.sqlite"
        self.store = Store(self.path, {"troops": {"0": "Player"}})
        self.query = {
            **mission_telemetry(),
            "context": "campaign",
            "scene": "-1",
            "session": "-1",
            "agent": "-1",
        }
        self.store.poll(self.query)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def command(self, dataset="party", offset=0, limit=16):
        cmd = self.store.enqueue_operation(
            "scan_campaign", {"dataset": dataset, "offset": offset, "limit": limit}
        )
        response = self.store.poll(self.query).split("|")
        self.assertEqual(response[3], "5")
        self.assertEqual(response[7:9], ["-1", "-1"])
        return cmd

    def event(self, cmd, **kwargs):
        return {"v": "2", "job": str(cmd["id"]), "dataset": "1", **kwargs}

    def test_campaign_page_waits_for_all_rows_even_if_end_arrives_first(self):
        cmd = self.command(limit=2)
        self.store.event("/campaign-end", self.event(cmd, count="2", total="3"))
        self.assertFalse(self.store.campaign.result(cmd["id"])["complete"])
        for index in (1, 0):
            self.store.event(
                "/campaign-row",
                self.event(
                    cmd, id=str(index), a="0", b="5", c="1", d="0", e="0", f="0"
                ),
            )
        page = self.store.campaign.result(cmd["id"])
        self.assertTrue(page["complete"])
        self.assertEqual(page["next_offset"], 2)
        self.assertEqual(page["rows"][0]["name"], "Player")
        self.assertEqual(page["rows"][0]["wounded"], 1)

    def test_empty_page_is_complete_and_has_no_next_offset(self):
        cmd = self.command(offset=20)
        self.store.event("/campaign-end", self.event(cmd, count="0", total="3"))
        page = self.store.campaign.result(cmd["id"])
        self.assertTrue(page["complete"])
        self.assertIsNone(page["next_offset"])

    def test_rejects_bad_pagination_and_unknown_dataset(self):
        for args in (
            {"dataset": "party", "offset": -1, "limit": 16},
            {"dataset": "party", "offset": 0, "limit": 17},
            {"dataset": "party", "offset": True, "limit": 1},
            {"dataset": "cheats", "offset": 0, "limit": 1},
        ):
            with self.assertRaises(ValueError):
                self.store.enqueue_operation("scan_campaign", args)

    def test_campaign_export_rejected_in_mission_context(self):
        self.store.poll(mission_telemetry())
        with self.assertRaisesRegex(ValueError, "campaign telemetry"):
            self.command()

    def test_transition_to_mission_rejects_queued_campaign_request(self):
        cmd = self.command()
        self.store.poll(mission_telemetry())
        self.assertEqual(self.store.command(cmd["id"])["status"], "rejected")

    def test_legacy_reconnect_cannot_dispatch_campaign_as_a_message(self):
        cmd = self.command()
        self.store.poll({**self.query, "v": "1"})
        self.assertEqual(self.store.command(cmd["id"])["status"], "rejected")

    def test_exports_survive_restart(self):
        cmd = self.command()
        self.store.event("/campaign-end", self.event(cmd, count="0", total="0"))
        other = Store(self.path)
        try:
            self.assertTrue(other.campaign.result(cmd["id"])["complete"])
        finally:
            other.db.close()

    def test_world_coordinates_and_hidden_party_provenance(self):
        v = dict(id=32, a=4, b=8, c=3, d=100, e=1234, f=-500)
        row = self.store.campaign.decode("world_parties", v)
        self.assertEqual(row["position"], {"x": 12.34, "y": -5})
        self.assertEqual(row["members"], 100)
        self.assertIsNone(row["name"])

    def test_character_attribute_and_skill_indices(self):
        v = dict(id=0, a=12, b=0, c=0, d=0, e=0, f=0)
        self.assertEqual(self.store.campaign.decode("character", v)["stat"], "level")
        v["id"] = 4
        self.assertEqual(self.store.campaign.decode("character", v)["stat"], "charisma")
        v["id"] = 5
        self.assertEqual(self.store.campaign.decode("character", v)["skill_id"], 0)

    def test_quest_context_remains_raw_not_fabricated_journal(self):
        row = self.store.campaign.decode(
            "quests", dict(id=2, a=55, b=56, c=30, d=1, e=10, f=0)
        )
        self.assertEqual(row["giver_troop_id"], 55)
        self.assertEqual(row["target_center_id"], 30)
        self.assertIsNone(row["definition"])

    def test_stale_pages_are_explicitly_marked(self):
        cmd = self.command()
        self.store.event("/campaign-end", self.event(cmd, count="0", total="0"))
        self.store.db.execute("UPDATE campaign_exports SET created=0")
        self.store.db.commit()
        self.assertTrue(self.store.campaign.result(cmd["id"])["stale"])

    def test_rejects_mismatched_and_excess_events(self):
        cmd = self.command(limit=1)
        with self.assertRaises(ValueError):
            self.store.event("/campaign-end", self.event(cmd, count="2", total="3"))
        with self.assertRaises(ValueError):
            self.store.event(
                "/campaign-end", self.event(cmd, dataset="2", count="0", total="0")
            )
        row = dict(a="0", b="1", c="0", d="0", e="0", f="0")
        self.store.event("/campaign-row", self.event(cmd, id="0", **row))
        self.store.event("/campaign-row", self.event(cmd, id="0", **row))
        with self.assertRaises(ValueError):
            self.store.event("/campaign-row", self.event(cmd, id="1", **row))


if __name__ == "__main__":
    unittest.main()
