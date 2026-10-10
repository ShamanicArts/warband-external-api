import json
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from warband_agentic import (
    ActorKind,
    ActorRef,
    ContextKind,
    ContextRef,
    Evidence,
    EvidenceLevel,
    GameEvent,
)
from warband_agentic.events import SemanticEventLog, game_event_from_wire


class SemanticEventLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "runtime.sqlite3"
        self.context = ContextRef(ContextKind.DIALOGUE, "scene:376", 12, 3)
        self.actor = ActorRef("troop:691", ActorKind.TROOP, 691)

    def tearDown(self):
        self.temp.cleanup()

    def event(self, event_type="dialogue.npc-line", occurred=1200):
        return GameEvent(
            0,
            event_type,
            self.context,
            (self.actor,),
            {"entry_id": 2469},
            Evidence(
                EvidenceLevel.ENGINE_OBSERVED,
                "Warband consequence",
                "Catalog-validated committed entry",
            ),
            occurred,
        )

    def test_assigns_order_and_evidence_sequence_then_round_trips(self):
        with SemanticEventLog(self.database) as log:
            result = log.append(self.event(), "dialogue:source:1")
            self.assertTrue(result.inserted)
            self.assertEqual(result.event.sequence, 1)
            self.assertEqual(result.event.evidence.event_sequence, 1)
            page = log.read()
        self.assertEqual(page.events, (result.event,))
        self.assertEqual(page.next_sequence, 1)
        self.assertEqual(page.high_watermark, 1)

    def test_restart_preserves_order_and_cursor_pages(self):
        with SemanticEventLog(self.database) as log:
            for index in range(3):
                log.append(
                    self.event(f"test.event-{index}", 1200 + index),
                    f"source:{index}",
                )
        with SemanticEventLog(self.database) as reopened:
            first = reopened.read(limit=2)
            second = reopened.read(first.next_sequence)
        self.assertEqual([event.sequence for event in first.events], [1, 2])
        self.assertEqual(first.high_watermark, 3)
        self.assertEqual([event.sequence for event in second.events], [3])

    def test_source_idempotency_rejects_conflicting_reuse(self):
        with SemanticEventLog(self.database) as log:
            first = log.append(self.event(), "source:one")
            equivalent = replace(
                self.event(),
                evidence=replace(self.event().evidence, event_sequence=0),
            )
            repeated = log.append(equivalent, "source:one")
            self.assertFalse(repeated.inserted)
            self.assertEqual(repeated.event, first.event)
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                log.append(self.event("different.event"), "source:one")
            with self.assertRaisesRegex(ValueError, "sequence zero"):
                log.append(first.event, "source:committed")

    def test_concurrent_appends_have_unique_monotonic_sequences(self):
        with SemanticEventLog(self.database) as log:
            results = []

            def append(index):
                results.append(
                    log.append(self.event(f"test.concurrent-{index}"), f"c:{index}")
                )

            threads = [
                threading.Thread(target=append, args=(index,))
                for index in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            page = log.read()
        self.assertEqual(len(results), 8)
        self.assertEqual([event.sequence for event in page.events], list(range(1, 9)))

    def test_decoder_rejects_unknown_persisted_fields(self):
        with SemanticEventLog(self.database) as log:
            committed = log.append(self.event(), "source:one").event
        from warband_agentic import to_wire

        wire = to_wire(committed)
        wire["provider_private"] = True
        with self.assertRaisesRegex(ValueError, "event fields"):
            game_event_from_wire(wire)

    def test_schema_migration_rejects_future_database(self):
        connection = sqlite3.connect(self.database)
        connection.execute(
            "CREATE TABLE agentic_store_meta "
            "(name TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute("INSERT INTO agentic_store_meta VALUES ('events', 99)")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(ValueError, "newer"):
            SemanticEventLog(self.database)

    def test_legacy_bridge_records_migrate_once_with_honest_evidence(self):
        connection = sqlite3.connect(self.database)
        connection.execute(
            "CREATE TABLE native_dialogue_events "
            "(sequence INTEGER PRIMARY KEY, received REAL NOT NULL, "
            "event TEXT NOT NULL, entry_id INTEGER NOT NULL, data TEXT NOT NULL)"
        )
        dialogue = {
            "source": "Warband conversation consequence",
            "symbol": "dlga_village_elder_talk:close_window.1",
            "text_template": "[Leave]",
            "input_state_id": 33,
            "output_state_id": 12,
            "conversation_troop_id": 691,
            "conversation_agent_id": 13,
            "context": 1,
            "mission_session": 3,
        }
        connection.execute(
            "INSERT INTO native_dialogue_events VALUES (1,1.5,'player_choice',2515,?)",
            (json.dumps(dialogue),),
        )
        connection.execute(
            "CREATE TABLE commands "
            "(id INTEGER PRIMARY KEY,text TEXT,created REAL,status TEXT,kind TEXT,"
            "arguments TEXT,scene INTEGER,session INTEGER,result INTEGER)"
        )
        connection.execute(
            "INSERT INTO commands VALUES "
            "(42,'Leave',2.0,'acknowledged','select_menu','{\"action_id\":1}',NULL,NULL,0)"
        )
        connection.execute(
            "INSERT INTO commands VALUES "
            "(43,'Pending',3.0,'queued','message','{}',NULL,NULL,NULL)"
        )
        connection.commit()
        connection.close()

        with SemanticEventLog(self.database) as log:
            self.assertEqual(log.migrate_legacy_bridge(), 2)
            self.assertEqual(log.migrate_legacy_bridge(), 0)
            events = log.read().events
        self.assertEqual(
            [event.event_type for event in events],
            ["legacy.dialogue.player-choice", "legacy.command.acknowledged"],
        )
        self.assertEqual(events[0].context.scope_id, "legacy:mission-session:3")
        self.assertIn("unavailable", events[0].evidence.detail)
        self.assertIs(events[1].evidence.level, EvidenceLevel.ENGINE_ACKNOWLEDGED)
        self.assertIn("not independent", events[1].evidence.detail)

    def test_bounds_and_different_draft_evidence_sequence_are_rejected(self):
        with SemanticEventLog(self.database) as log:
            with self.assertRaisesRegex(ValueError, "limit"):
                log.read(limit=0)
            invalid = replace(
                self.event(),
                evidence=replace(self.event().evidence, event_sequence=9),
            )
            with self.assertRaisesRegex(ValueError, "sequence zero"):
                log.append(invalid, "invalid")


if __name__ == "__main__":
    unittest.main()
