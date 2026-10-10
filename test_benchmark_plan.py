import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bridge.benchmark_plan import load_faction_benchmark_plan


class FactionBenchmarkPlanTests(unittest.TestCase):
    def _write_fixture(self, root):
        (root / "mcp-catalog.json").write_text(
            json.dumps({"menus": {}, "factions": {}, "parties": {}})
        )
        (root / "mcp-build.json").write_text(
            json.dumps(
                {
                    "protocol": 2,
                    "integration_revision": 16,
                    "extensions": [
                        {"extension_id": "warband.native", "version": "0.2.0"}
                    ],
                    "transport": "engine HTTP opcode 380",
                }
            )
        )
        tokens = []
        for index in range(5):
            path = root / f"private-{index}.token"
            path.write_text(str(index + 1) * 64)
            path.chmod(0o600)
            tokens.append(path)
        host = root / "host.json"
        host.write_text(
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
                    "control": {"token_file": "private-1.token", "port": 8766},
                    "events_database": "events.sqlite3",
                    "sessions": [
                        {
                            "kind": "native-faction",
                            "session_id": "swadia",
                            "token_file": "private-2.token",
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
                            "kind": "native-faction",
                            "session_id": "vaegirs",
                            "token_file": "private-3.token",
                            "port": 8871,
                            "faction_id": 16,
                            "controlled_party_ids": [600],
                            "order_options": [
                                {
                                    "party_id": 600,
                                    "order": "attack",
                                    "target_party_id": 500,
                                    "title": "Attack the Swadian host",
                                }
                            ],
                        },
                    ],
                }
            )
        )
        plan = root / "benchmark.json"
        plan.write_text(
            json.dumps(
                {
                    "schema": "warband.agentic/benchmark-plan/v1",
                    "run_id": "native-border-war-42",
                    "host_config": "host.json",
                    "scenario": {
                        "schema": "warband.agentic/benchmark-scenario/v1",
                        "scenario_id": "native.border-war",
                        "version": "1.0.0",
                        "description": "Two-faction border war",
                        "faction_ids": [15, 16],
                        "metrics": [
                            {
                                "key": "active_world_parties",
                                "description": "Active parties assigned to the faction",
                                "unit": "count",
                                "objective": "maximize",
                                "weight": 10,
                                "scale": 5,
                            },
                            {
                                "key": "military_strength",
                                "description": "Observed active-party members",
                                "unit": "troops",
                                "objective": "maximize",
                                "weight": 40,
                                "scale": 100,
                            },
                            {
                                "key": "settlements",
                                "description": "Owned scenario settlements",
                                "unit": "count",
                                "objective": "maximize",
                                "weight": 20,
                                "scale": 2,
                            },
                            {
                                "key": "surviving",
                                "description": "Faction remains active",
                                "unit": "boolean",
                                "objective": "binary",
                                "weight": 30,
                                "scale": None,
                            },
                        ],
                    },
                    "participants": [
                        {
                            "faction_id": 15,
                            "session_id": "swadia",
                            "provider": "openai",
                            "model": "luna",
                            "settings": {"temperature": 0},
                        },
                        {
                            "faction_id": 16,
                            "session_id": "vaegirs",
                            "provider": "cursor",
                            "model": "grok-4.6",
                            "settings": {"temperature": 0},
                        },
                    ],
                    "settlement_party_ids": [1, 2, 3, 4],
                    "epochs": {"count": 24, "hours": 1, "speed": 2},
                    "budget": {
                        "max_input_tokens": 4096,
                        "max_output_tokens": 300,
                        "timeout_ms": 30000,
                        "max_cost_microusd": 50000,
                    },
                    "run_metadata": {
                        "module_sha256": "a" * 64,
                        "save_sha256": "b" * 64,
                        "scenario_seed": 42,
                        "runner_version": "0.2.0",
                    },
                }
            )
        )
        return plan, tokens

    def test_check_compiles_complete_plan_without_runtime_side_effects(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, tokens = self._write_fixture(root)

            plan = load_faction_benchmark_plan(config)
            diagnostics = plan.diagnostics()

            self.assertEqual(
                diagnostics["schema"], "warband.agentic/benchmark-plan-check/v1"
            )
            self.assertEqual(diagnostics["run_id"], "native-border-war-42")
            self.assertEqual(diagnostics["scenario"]["faction_ids"], [15, 16])
            self.assertEqual(
                diagnostics["epochs"], {"count": 24, "hours": 1, "speed": 2}
            )
            self.assertEqual(diagnostics["participants"][0]["session_id"], "swadia")
            self.assertEqual(diagnostics["participants"][1]["model"], "grok-4.6")
            self.assertEqual(diagnostics["budget"]["max_output_tokens"], 300)
            self.assertEqual(len(diagnostics["run_metadata_sha256"]), 64)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bridge.benchmark_plan",
                    "--config",
                    config,
                    "--check",
                ],
                cwd=Path(__file__).parent,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(result.stdout), diagnostics)
            encoded = json.dumps(diagnostics)
            for token in tokens:
                self.assertNotIn(token.read_text(), encoded)
                self.assertNotIn(token.name, encoded)
            self.assertFalse((root / "bridge.sqlite3").exists())
            self.assertFalse((root / "events.sqlite3").exists())

    def test_plan_refuses_credentials_in_retained_run_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, _tokens = self._write_fixture(root)
            value = json.loads(config.read_text())
            value["run_metadata"]["api_key"] = "must-not-enter-the-report"
            config.write_text(json.dumps(value))

            with self.assertRaisesRegex(ValueError, "credential-like") as raised:
                load_faction_benchmark_plan(config)

            self.assertNotIn("must-not-enter-the-report", str(raised.exception))
            self.assertFalse((root / "bridge.sqlite3").exists())
            self.assertFalse((root / "events.sqlite3").exists())

    def test_plan_rejects_metric_sets_the_native_collector_cannot_produce(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, _tokens = self._write_fixture(root)
            value = json.loads(config.read_text())
            value["scenario"]["metrics"] = value["scenario"]["metrics"][1:]
            config.write_text(json.dumps(value))

            with self.assertRaisesRegex(ValueError, "collector metric set"):
                load_faction_benchmark_plan(config)

    def test_runtime_preflight_is_hashed_and_has_no_host_or_provider_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, tokens = self._write_fixture(root)
            wrapper = root / "provider-wrapper"
            wrapper.write_text("#!/bin/sh\nexit 0\n")
            wrapper.chmod(0o700)
            adapters = root / "adapters.json"
            adapters.write_text(
                json.dumps(
                    {
                        "schema": "warband.agentic/subprocess-adapters/v1",
                        "adapters": [
                            {
                                "provider": provider,
                                "argv": [str(wrapper)],
                                "pass_environment": [],
                            }
                            for provider in ("openai", "cursor")
                        ],
                    }
                )
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bridge.benchmark_runtime_cli",
                    "--config",
                    config,
                    "--adapter-config",
                    adapters,
                    "--preflight",
                ],
                cwd=Path(__file__).parent,
                check=True,
                capture_output=True,
                text=True,
            )

            preflight = json.loads(result.stdout)
            self.assertEqual(
                preflight["schema"],
                "warband.agentic/benchmark-execution-preflight/v1",
            )
            self.assertEqual(preflight["run_id"], "native-border-war-42")
            self.assertEqual(
                [item["model"] for item in preflight["participants"]],
                ["luna", "grok-4.6"],
            )
            self.assertEqual(len(preflight["confirmation_sha256"]), 64)
            self.assertFalse((root / "bridge.sqlite3").exists())
            self.assertFalse((root / "events.sqlite3").exists())
            encoded = json.dumps(preflight)
            for token in tokens:
                self.assertNotIn(token.read_text(), encoded)

            refused = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bridge.benchmark_runtime_cli",
                    "--config",
                    config,
                    "--adapter-config",
                    adapters,
                    "--execute",
                    "--acknowledge-preflight",
                    "0" * 64,
                    "--checkpoint",
                    root / "run.checkpoint.json",
                    "--report",
                    root / "run.report.json",
                ],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
            )
            self.assertEqual(refused.returncode, 2)
            self.assertIn("current --preflight", refused.stderr)
            self.assertFalse((root / "bridge.sqlite3").exists())
            self.assertFalse((root / "events.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
