import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from test_installer import make_native


class PackagingTests(unittest.TestCase):
    def test_lock_file_matches_project_metadata(self):
        subprocess.run(
            ["uv", "lock", "--check"],
            cwd=Path(__file__).parent,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_wheel_contains_agentic_kit_and_console_entrypoints(self):
        root = Path(__file__).parent
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["uv", "build", "--sdist", "--out-dir", directory],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            source_distribution = next(Path(directory).glob("*.tar.gz"))
            subprocess.run(
                [
                    "uv",
                    "build",
                    "--wheel",
                    "--out-dir",
                    directory,
                    source_distribution,
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            wheel = next(Path(directory).glob("*.whl"))
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
                self.assertIn("warband_agentic/contracts.py", names)
                self.assertIn("warband_agentic/agent_client.py", names)
                self.assertIn("warband_agentic/extensions.py", names)
                self.assertIn("warband_agentic/benchmark.py", names)
                self.assertIn("warband_agentic/provider_decisions.py", names)
                self.assertIn("warband_agentic/scoring.py", names)
                self.assertIn("warband_agentic/subprocess_provider.py", names)
                self.assertIn("bridge/game_bridge.py", names)
                self.assertIn("bridge/application_extensions.py", names)
                self.assertIn("bridge/benchmark_runner.py", names)
                self.assertIn("bridge/benchmark_runtime_cli.py", names)
                self.assertIn("bridge/provider_adapter_config.py", names)
                self.assertIn("bridge/opencode_provider_adapter.py", names)
                self.assertIn("bridge/campaign_metric_collector.py", names)
                self.assertIn("bridge/benchmark_plan.py", names)
                self.assertIn("bridge/native_faction_agent_app.py", names)
                self.assertIn("bridge/native_npc_speech_app.py", names)
                self.assertIn("bridge/installer.py", names)
                self.assertIn("module_system/build_mcp_module.py", names)
                self.assertIn("src/warband_mcp.py", names)
                self.assertIn("src/warband_agent_mcp.py", names)
                for example in (
                    "agent-mcp.example.json",
                    "agent-host.example.json",
                    "benchmark.example.json",
                    "provider-adapters.example.json",
                    "voice.example.json",
                ):
                    self.assertTrue(
                        any(
                            name.endswith(
                                "share/warband-agentic-kit/examples/" + example
                            )
                            for name in names
                        ),
                        f"wheel does not contain {example}",
                    )
                entry_points = next(
                    name for name in names if name.endswith("/entry_points.txt")
                )
                scripts = archive.read(entry_points).decode()
                metadata_file = next(
                    name for name in names if name.endswith(".dist-info/METADATA")
                )
                metadata = archive.read(metadata_file).decode()
                self.assertIn("License-Expression: MIT", metadata)
                self.assertTrue(
                    any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
                )
                self.assertTrue(
                    any(
                        name.endswith(".dist-info/licenses/THIRD_PARTY_NOTICES.md")
                        for name in names
                    )
                )
                for command in (
                    "warband-mcp",
                    "warband-agent-mcp",
                    "warband-game-bridge",
                    "warband-agent-host",
                    "warband-build-module",
                    "warband-voice",
                    "warband-agent-usability",
                    "warband-benchmark",
                    "warband-benchmark-run",
                    "warband-provider-opencode",
                    "warband-kit-install",
                ):
                    self.assertIn(command, scripts)
                self.assertFalse(
                    any(
                        name.startswith("evidence/")
                        or name.endswith((".sqlite", ".token"))
                        for name in names
                    )
                )

            installed = Path(directory, "installed")
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--target",
                    installed,
                    "--no-deps",
                    wheel,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            environment = {**os.environ, "PYTHONPATH": str(installed)}
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import bridge.native_faction_agent_app; "
                        "import bridge.application_extensions; "
                        "import bridge.benchmark_runner; "
                        "import bridge.benchmark_runtime_cli; "
                        "import bridge.provider_adapter_config; "
                        "import bridge.opencode_provider_adapter; "
                        "import bridge.installer; "
                        "import bridge.campaign_metric_collector; "
                        "import bridge.benchmark_plan; "
                        "import module_system.build_mcp_module; "
                        "import warband_agentic.benchmark; "
                        "import warband_agentic.agent_client; "
                        "import warband_agentic.extensions; "
                        "import warband_agentic.provider_decisions; "
                        "import warband_agentic.scoring; "
                        "import warband_agentic.subprocess_provider"
                    ),
                ],
                cwd=directory,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            for command in (
                "warband-game-bridge",
                "warband-agent-host",
                "warband-build-module",
                "warband-voice",
                "warband-agent-usability",
                "warband-benchmark",
                "warband-benchmark-run",
                "warband-provider-opencode",
                "warband-kit-install",
            ):
                subprocess.run(
                    [installed / "bin" / command, "--help"],
                    cwd=directory,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            fresh = Path(directory, "fresh")
            native = make_native(fresh)
            private_parent = fresh / "private"
            private_parent.mkdir()
            applied = subprocess.run(
                [
                    installed / "bin" / "warband-kit-install",
                    "apply",
                    "--native",
                    native,
                    "--install-root",
                    private_parent / "warband-agentic",
                ],
                cwd=directory,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            receipt = json.loads(applied.stdout)
            self.assertEqual(receipt["state"], "installed")
            checked = subprocess.run(
                [
                    installed / "bin" / "warband-agent-host",
                    "--config",
                    private_parent / "warband-agentic/config/agent-host.json",
                    "--check",
                ],
                cwd=directory,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(checked.stdout)["status"], "ready")


if __name__ == "__main__":
    unittest.main()
