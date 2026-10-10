import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from bridge.agent_host import AgentApplicationHost, load_agent_host_plan
from bridge.application_extensions import built_in_extension_registry
from bridge.native_npc_speech_app import NativeNpcSpeechApplication
from test_agentic_extensions import example_extension


def available_port():
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


class AgentApplicationHostCliTests(unittest.TestCase):
    def test_check_validates_three_session_plan_without_side_effects_or_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "mcp-catalog.json"
            catalog.write_text(json.dumps({"menus": {}, "factions": {}, "parties": {}}))
            build = root / "mcp-build.json"
            build.write_text(
                json.dumps(
                    {
                        "protocol": 2,
                        "integration_revision": 16,
                        "transport": "engine HTTP opcode 380",
                    }
                )
            )
            token_paths = []
            for index in range(5):
                path = root / f"private-{index}.token"
                path.write_text(str(index + 1) * 64)
                path.chmod(0o600)
                token_paths.append(path)
            config = root / "host.json"
            config.write_text(
                json.dumps(
                    {
                        "schema": "warband.agentic/host-config/v1",
                        "bridge": {
                            "database": "bridge.sqlite3",
                            "catalog": "mcp-catalog.json",
                            "build_manifest": "mcp-build.json",
                            "token_file": "private-0.token",
                            "port": 8765,
                        },
                        "control": {
                            "token_file": "private-1.token",
                            "port": 8766,
                        },
                        "events_database": "events.sqlite3",
                        "sessions": [
                            {
                                "kind": "native-menu",
                                "session_id": "player-menu",
                                "token_file": "private-2.token",
                                "port": 8869,
                            },
                            {
                                "kind": "native-faction",
                                "session_id": "swadia",
                                "token_file": "private-3.token",
                                "port": 8870,
                                "faction_id": 15,
                                "controlled_party_ids": [500],
                                "order_options": [
                                    {
                                        "party_id": 500,
                                        "order": "travel",
                                        "target_party_id": 26,
                                        "title": "Defend Praven",
                                    }
                                ],
                            },
                            {
                                "kind": "native-npc-speech",
                                "session_id": "trainer",
                                "token_file": "private-4.token",
                                "port": 8871,
                                "agent_id": 7,
                            },
                        ],
                    }
                )
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bridge.agent_host",
                    "--config",
                    config,
                    "--check",
                ],
                cwd=Path(__file__).parent,
                check=True,
                capture_output=True,
                text=True,
            )
            diagnostics = json.loads(result.stdout)
            self.assertEqual(
                diagnostics,
                {
                    "schema": "warband.agentic/host-diagnostics/v1",
                    "status": "ready",
                    "module": {"protocol": 2, "integration_revision": 16},
                    "bridge": {"host": "127.0.0.1", "port": 8765},
                    "control": {"host": "127.0.0.1", "port": 8766},
                    "extensions": [
                        {"extension_id": "warband.native", "version": "0.2.0"}
                    ],
                    "sessions": [
                        {
                            "kind": "native-menu",
                            "session_id": "player-menu",
                            "host": "127.0.0.1",
                            "port": 8869,
                        },
                        {
                            "kind": "native-faction",
                            "session_id": "swadia",
                            "host": "127.0.0.1",
                            "port": 8870,
                        },
                        {
                            "kind": "native-npc-speech",
                            "session_id": "trainer",
                            "host": "127.0.0.1",
                            "port": 8871,
                        },
                    ],
                },
            )
            encoded = json.dumps(diagnostics)
            for token_path in token_paths:
                self.assertNotIn(token_path.read_text(), encoded)
                self.assertNotIn(token_path.name, encoded)
            self.assertFalse((root / "bridge.sqlite3").exists())
            self.assertFalse((root / "events.sqlite3").exists())

            conflicting = json.loads(config.read_text())
            extra_token = root / "private-conflict.token"
            extra_token.write_text("f" * 64)
            extra_token.chmod(0o600)
            conflicting["sessions"].append(
                {
                    "kind": "native-faction",
                    "session_id": "swadia-copy",
                    "token_file": extra_token.name,
                    "port": 8872,
                    "faction_id": 15,
                    "controlled_party_ids": [500],
                    "order_options": [
                        {
                            "party_id": 500,
                            "order": "travel",
                            "target_party_id": 26,
                            "title": "Duplicate control",
                        }
                    ],
                }
            )
            config.write_text(json.dumps(conflicting))
            rejected = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bridge.agent_host",
                    "--config",
                    config,
                    "--check",
                ],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("controlled parties overlap", rejected.stderr)
            self.assertNotIn(extra_token.read_text(), rejected.stderr)

    def test_runtime_hosts_session_refresh_control_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge_port, control_port, session_port = (
                available_port(),
                available_port(),
                available_port(),
            )
            while len({bridge_port, control_port, session_port}) != 3:
                control_port, session_port = available_port(), available_port()
            while session_port == bridge_port:
                session_port = available_port()
            (root / "mcp-catalog.json").write_text(
                json.dumps({"troops": {"7": "Trainer"}})
            )
            (root / "mcp-build.json").write_text(
                json.dumps({"protocol": 2, "integration_revision": 16})
            )
            for name, token in (
                ("bridge", "a" * 64),
                ("control", "c" * 64),
                ("npc", "b" * 64),
            ):
                path = root / f"{name}.token"
                path.write_text(token)
                path.chmod(0o600)
            config = root / "host.json"
            config.write_text(
                json.dumps(
                    {
                        "schema": "warband.agentic/host-config/v1",
                        "bridge": {
                            "database": "bridge.sqlite3",
                            "catalog": "mcp-catalog.json",
                            "build_manifest": "mcp-build.json",
                            "token_file": "bridge.token",
                            "port": bridge_port,
                        },
                        "control": {
                            "token_file": "control.token",
                            "port": control_port,
                        },
                        "events_database": "events.sqlite3",
                        "sessions": [
                            {
                                "kind": "native-npc-speech",
                                "session_id": "trainer",
                                "token_file": "npc.token",
                                "port": session_port,
                                "agent_id": 7,
                            }
                        ],
                    }
                )
            )
            host = AgentApplicationHost(load_agent_host_plan(config))
            try:
                host.start()
                self.assertEqual(
                    host.runtime_diagnostics()["status"], "waiting-for-game"
                )
                query = (
                    "v=2&context=mission&ack=0&gold=355&troop=0&hp=50&x=0&y=0&z=0"
                    "&clock=90&scene=42&session=1&agent=0&result=0&build=16"
                    "&menu=-1&menu-session=0&dialogue=0&captive=0&flags=0&token="
                    + "a" * 64
                )
                with urlopen(
                    f"http://127.0.0.1:{bridge_port}/poll?{query}", timeout=2
                ) as response:
                    self.assertEqual(response.status, 200)
                self.assertTrue(host.wait_until_ready(timeout=2))
                request = Request(
                    f"http://127.0.0.1:{session_port}/v1/agent/manifest",
                    headers={"Authorization": "Bearer " + "b" * 64},
                )
                with urlopen(request, timeout=2) as response:
                    manifest = json.load(response)
                self.assertEqual(manifest["session_id"], "trainer")
                self.assertEqual(manifest["role"], "npc.self")
                refresh = Request(
                    (
                        f"http://127.0.0.1:{control_port}"
                        "/v1/host/sessions/trainer/refresh"
                    ),
                    data=b"",
                    method="POST",
                    headers={"Authorization": "Bearer " + "c" * 64},
                )
                with urlopen(refresh, timeout=2) as response:
                    refresh_result = json.load(response)
                    self.assertEqual(response.status, 202)
                self.assertEqual(
                    refresh_result,
                    {
                        "schema": "warband.agentic/host-refresh/v1",
                        "session_id": "trainer",
                        "status": "queued",
                        "job_count": 1,
                    },
                )
                self.assertEqual(host.runtime_diagnostics()["status"], "ready")
            finally:
                host.stop()

            self.assertEqual(host.runtime_diagnostics()["status"], "stopped")
            for port in (bridge_port, control_port, session_port):
                with self.subTest(port=port):
                    with socket.socket() as probe:
                        probe.settimeout(0.1)
                        self.assertNotEqual(
                            probe.connect_ex(("127.0.0.1", port)), 0
                        )

    def test_explicit_extension_registry_hosts_custom_kind_without_import_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge_port, control_port, session_port = (
                available_port(),
                available_port(),
                available_port(),
            )
            while len({bridge_port, control_port, session_port}) != 3:
                bridge_port, control_port, session_port = (
                    available_port(),
                    available_port(),
                    available_port(),
                )
            (root / "mcp-catalog.json").write_text(
                json.dumps({"troops": {"7": "Trainer"}})
            )
            (root / "mcp-build.json").write_text(
                json.dumps({"protocol": 2, "integration_revision": 16})
            )
            for name, token in (
                ("bridge", "1" * 64),
                ("control", "2" * 64),
                ("agent", "3" * 64),
            ):
                path = root / f"{name}.token"
                path.write_text(token)
                path.chmod(0o600)
            config = root / "host.json"
            config.write_text(
                json.dumps(
                    {
                        "schema": "warband.agentic/host-config/v1",
                        "bridge": {
                            "database": "bridge.sqlite3",
                            "catalog": "mcp-catalog.json",
                            "build_manifest": "mcp-build.json",
                            "token_file": "bridge.token",
                            "port": bridge_port,
                        },
                        "control": {
                            "token_file": "control.token",
                            "port": control_port,
                        },
                        "events_database": "events.sqlite3",
                        "sessions": [
                            {
                                "kind": "example-npc",
                                "session_id": "custom-trainer",
                                "token_file": "agent.token",
                                "port": session_port,
                                "agent_id": 7,
                            }
                        ],
                    }
                )
            )
            registry = built_in_extension_registry()
            registry.register(
                example_extension(),
                {"example-npc": NativeNpcSpeechApplication},
            )
            plan = load_agent_host_plan(config, registry)
            self.assertEqual(
                plan.diagnostics()["extensions"],
                [
                    {"extension_id": "example.dialogue", "version": "1.2.3"},
                    {"extension_id": "warband.native", "version": "0.2.0"},
                ],
            )
            host = AgentApplicationHost(plan)
            try:
                host.start()
                query = (
                    "v=2&context=mission&ack=0&gold=355&troop=0&hp=50&x=0&y=0&z=0"
                    "&clock=90&scene=42&session=1&agent=0&result=0&build=16"
                    "&menu=-1&menu-session=0&dialogue=0&captive=0&flags=0&token="
                    + "1" * 64
                )
                with urlopen(
                    f"http://127.0.0.1:{bridge_port}/poll?{query}", timeout=2
                ) as response:
                    self.assertEqual(response.status, 200)
                self.assertTrue(host.wait_until_ready(timeout=2))
                request = Request(
                    f"http://127.0.0.1:{session_port}/v1/agent/manifest",
                    headers={"Authorization": "Bearer " + "3" * 64},
                )
                with urlopen(request, timeout=2) as response:
                    manifest = json.load(response)
                self.assertEqual(manifest["session_id"], "custom-trainer")
                self.assertEqual(manifest["role"], "npc.self")
                catalog_request = Request(
                    f"http://127.0.0.1:{control_port}/v1/host/extensions",
                    headers={"Authorization": "Bearer " + "2" * 64},
                )
                with urlopen(catalog_request, timeout=2) as response:
                    extension_catalog = json.load(response)
                self.assertEqual(
                    [
                        item["extension_id"]
                        for item in extension_catalog["extensions"]
                    ],
                    ["example.dialogue", "warband.native"],
                )
                self.assertNotIn("factory", json.dumps(extension_catalog).lower())
            finally:
                host.stop()


if __name__ == "__main__":
    unittest.main()
