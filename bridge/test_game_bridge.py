import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bridge.game_bridge import Store, make_server
from module_system.build_mcp_module import OPS, callback, compile_ops


def telemetry(ack=0):
    return dict(
        v="1",
        context="mission",
        ack=str(ack),
        gold="42",
        troop="0",
        hp="75",
        x="1234",
        y="-500",
        z="100",
        clock="10",
    )


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "bridge.db")

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_disconnected_until_engine_poll(self):
        self.assertFalse(self.store.snapshot()["connected"])
        self.assertEqual(self.store.poll(telemetry()), "741731|1|0|0|0|idle")
        state = self.store.snapshot()
        self.assertTrue(state["connected"])
        self.assertEqual(state["player_gold"], 42)
        self.assertEqual(state["position"]["x"], 12.34)

    def test_dispatch_retry_and_game_ack(self):
        command = self.store.enqueue("MCP proof")
        response = self.store.poll(telemetry())
        self.assertIn(f"|{command['id']}|1|0|MCP proof", response)
        self.assertEqual(self.store.command(command["id"])["status"], "dispatched")
        self.assertEqual(self.store.poll(telemetry()), response)
        self.assertEqual(
            self.store.poll(telemetry(command["id"])), "741731|1|0|0|0|idle"
        )
        self.assertEqual(self.store.command(command["id"])["status"], "acknowledged")

    def test_expired_commands_not_sent(self):
        command = self.store.enqueue("expires")
        with patch(
            "bridge.game_bridge.time.time", return_value=command["created"] + 31
        ):
            self.assertEqual(self.store.poll(telemetry()), "741731|1|0|0|0|idle")
        self.assertEqual(self.store.command(command["id"])["status"], "expired")

    def test_expiration_visible_even_if_game_stops_polling(self):
        command = self.store.enqueue("expires while paused")
        with patch(
            "bridge.game_bridge.time.time", return_value=command["created"] + 31
        ):
            self.assertEqual(self.store.command(command["id"])["status"], "expired")

    def test_late_game_ack_overrides_timeout(self):
        command = self.store.enqueue("late acknowledgement")
        self.store.poll(telemetry())
        with patch(
            "bridge.game_bridge.time.time", return_value=command["created"] + 31
        ):
            self.assertEqual(self.store.command(command["id"])["status"], "expired")
            self.store.poll(telemetry(command["id"]))
            self.assertEqual(
                self.store.command(command["id"])["status"], "acknowledged"
            )

    def test_protocol_injection_rejected(self):
        for text in ("", "bad|command", "bad\ncommand", "x" * 201):
            with self.assertRaises(ValueError):
                self.store.enqueue(text)

    def test_unsupported_protocol_rejected(self):
        query = telemetry()
        query["v"] = "3"
        with self.assertRaisesRegex(ValueError, "Unsupported game protocol"):
            self.store.poll(query)

    def test_command_ids_survive_restart(self):
        first = self.store.enqueue("first")
        other = Store(Path(self.temp.name) / "bridge.db")
        try:
            self.assertGreater(other.enqueue("second")["id"], first["id"])
        finally:
            other.db.close()

    def test_compiled_operation_count_and_dedup_guard(self):
        tokens = list(map(int, callback().split()))
        count, cursor, found = tokens[0], 1, []
        while cursor < len(tokens):
            opcode, arity = tokens[cursor : cursor + 2]
            found.append(opcode)
            cursor += 2 + arity
        self.assertEqual(cursor, len(tokens))
        self.assertEqual(count, len(found))
        self.assertIn(OPS["gt"], found)
        self.assertEqual(compile_ops([("assign", 1, 2)]), "1 2133 2 1 2")


def mission_telemetry():
    return {
        **telemetry(),
        "v": "2",
        "scene": "42",
        "session": "1",
        "agent": "0",
        "result": "0",
    }


class GameOperationTests(unittest.TestCase):
    setUp = BridgeTests.setUp
    tearDown = BridgeTests.tearDown

    def test_relocation_is_scoped_and_fixed_point_encoded(self):
        self.store.poll(mission_telemetry())
        cmd = self.store.enqueue_operation("relocate_player", {"x": 14, "y": -5})
        self.assertEqual(cmd["scene"], 42)
        self.assertEqual(cmd["session"], 1)
        parts = self.store.poll(mission_telemetry()).split("|")
        self.assertEqual(parts[3:9], ["3", "1400", "-500", "0", "1", "42"])

    def test_bridge_restart_does_not_replay_mission_actions(self):
        self.store.poll(mission_telemetry())
        dispatched = self.store.enqueue_operation("relocate_player", {"x": 14, "y": -5})
        self.store.poll(mission_telemetry())
        queued = self.store.enqueue_operation("scan_agents", {})
        other = Store(Path(self.temp.name) / "bridge.db")
        try:
            self.assertEqual(other.command(dispatched["id"])["status"], "interrupted")
            self.assertEqual(other.command(queued["id"])["status"], "rejected")
            self.assertEqual(
                other.poll(mission_telemetry()), "741731|2|0|0|0|0|0|0|0|idle"
            )
        finally:
            other.db.close()

    def test_mission_clock_reset_interrupts_dispatched_action(self):
        query = mission_telemetry()
        self.store.poll(query)
        command = self.store.enqueue_operation("scan_agents", {})
        self.store.poll(query)
        query["clock"] = "0"
        self.store.poll(query)
        self.assertEqual(self.store.command(command["id"])["status"], "interrupted")

    def test_late_ack_can_resolve_interrupted_operation(self):
        query = mission_telemetry()
        self.store.poll(query)
        command = self.store.enqueue_operation("scan_agents", {})
        self.store.poll(query)
        other = Store(Path(self.temp.name) / "bridge.db")
        try:
            query["ack"] = str(command["id"])
            other.poll(query)
            self.assertEqual(other.command(command["id"])["status"], "acknowledged")
        finally:
            other.db.close()

    def test_relocation_rejects_large_or_nonfinite_moves(self):
        self.store.poll(mission_telemetry())
        for x in (100, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                self.store.enqueue_operation("relocate_player", {"x": x, "y": -5})

    def test_mission_commands_refuse_legacy_and_campaign_contexts(self):
        self.store.poll(telemetry())
        with self.assertRaisesRegex(ValueError, "protocol-2 mission"):
            self.store.enqueue_operation("scan_agents", {})
        query = mission_telemetry()
        query["context"] = "campaign"
        self.store.poll(query)
        with self.assertRaisesRegex(ValueError, "protocol-2 mission"):
            self.store.enqueue_operation("scan_agents", {})

    def test_scene_reload_rejects_queued_commands(self):
        query = mission_telemetry()
        self.store.poll(query)
        command = self.store.enqueue_operation("scan_agents", {})
        query["session"] = "2"
        self.assertEqual(self.store.poll(query), "741731|2|0|0|0|0|0|0|0|idle")
        self.assertEqual(self.store.command(command["id"])["status"], "rejected")

    def test_engine_rejection_is_not_acknowledged_success(self):
        query = mission_telemetry()
        self.store.poll(query)
        command = self.store.enqueue_operation("scan_agents", {})
        self.store.poll(query)
        query.update(ack=str(command["id"]), result="-1")
        self.store.poll(query)
        self.assertEqual(self.store.command(command["id"])["status"], "rejected")

    def census(self):
        self.store.poll(mission_telemetry())
        command = self.store.enqueue_operation("scan_agents", {})
        self.store.poll(mission_telemetry())
        event = dict(v="2", job=str(command["id"]), scene="42", session="1")
        self.store.event("/agents_end", {**event, "count": "2"})
        self.assertFalse(self.store.scan_result(command["id"])["complete"])
        for agent_id in (0, 1):
            self.store.event(
                "/agent",
                {
                    **event,
                    "id": str(agent_id),
                    "troop": str(agent_id),
                    "team": "0",
                    "hp": "50",
                    "x": "1234",
                    "y": "-500",
                    "z": "0",
                    "player": str(int(agent_id == 0)),
                },
            )
        return command

    def test_census_waits_for_all_out_of_order_events(self):
        command = self.census()
        result = self.store.scan_result(command["id"])
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["agents"]), 2)
        self.assertEqual(result["agents"][1]["position"]["x"], 12.34)

    def test_npc_requires_current_census_and_nonplayer_target(self):
        self.store.poll(mission_telemetry())
        with self.assertRaisesRegex(ValueError, "Refresh scene agents"):
            self.store.enqueue_operation("npc_say", {"agent_id": 1, "text": "Hello"})
        self.census()
        with self.assertRaisesRegex(ValueError, "player"):
            self.store.enqueue_operation("npc_say", {"agent_id": 0, "text": "Hello"})
        command = self.store.enqueue_operation(
            "npc_say", {"agent_id": 1, "text": "Hello"}
        )
        self.assertEqual(command["kind"], "npc_say")

    def test_dialogue_close_cannot_be_overwritten_by_late_open(self):
        scan = self.census()
        query = mission_telemetry()
        query["ack"] = str(scan["id"])
        self.store.poll(query)
        command = self.store.enqueue_operation(
            "npc_say", {"agent_id": 1, "text": "Hello"}
        )
        self.store.poll(query)
        event = {"v": "2", "job": str(command["id"])}
        self.store.event("/dialogue", {**event, "event": "2"})
        self.store.event("/dialogue", {**event, "event": "1"})
        self.assertEqual(self.store.dialogue_result(command["id"])["event"], "closed")

    def test_rejects_arbitrary_ops_and_text_template_injection(self):
        self.store.poll(mission_telemetry())
        for kind, args in (("execute_bytecode", {}), ("message", {"text": "{s0}"})):
            with self.assertRaises(ValueError):
                self.store.enqueue_operation(kind, args)


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "bridge.db")
        self.token = "a" * 64
        self.server = make_server(self.store, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.db.close()
        self.temp.cleanup()

    def api(self, path, data=None):
        request = Request(
            self.url + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": "Bearer " + self.token},
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_both_routes_require_authentication(self):
        for path in ("/api/state", "/poll?token=wrong"):
            with self.assertRaises(HTTPError) as result:
                urlopen(self.url + path, timeout=2)
            self.assertEqual(result.exception.code, 403)
        self.assertFalse(self.store.snapshot()["connected"])

    def test_post_refuses_disconnected_game(self):
        with self.assertRaises(HTTPError) as result:
            self.api("/api/commands", {"text": "must not queue"})
        self.assertEqual(result.exception.code, 409)

    def test_full_http_protocol_boundary(self):
        query = telemetry()
        query["token"] = self.token
        with urlopen(self.url + "/poll?" + urlencode(query), timeout=2) as response:
            self.assertEqual(response.read(), b"741731|1|0|0|0|idle")
        command = self.api("/api/commands", {"text": "boundary proof"})
        with urlopen(self.url + "/poll?" + urlencode(query), timeout=2) as response:
            self.assertIn(b"boundary proof", response.read())
        query["ack"] = str(command["id"])
        with urlopen(self.url + "/poll?" + urlencode(query), timeout=2) as response:
            response.read()
        self.assertEqual(
            self.api(f"/api/commands/{command['id']}")["status"], "acknowledged"
        )


if __name__ == "__main__":
    unittest.main()
