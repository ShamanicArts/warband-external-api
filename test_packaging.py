import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


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
                self.assertIn("warband_agentic/extensions.py", names)
                self.assertIn("warband_agentic/benchmark.py", names)
                self.assertIn("bridge/game_bridge.py", names)
                self.assertIn("bridge/application_extensions.py", names)
                self.assertIn("bridge/native_faction_agent_app.py", names)
                self.assertIn("bridge/native_npc_speech_app.py", names)
                self.assertIn("module_system/build_mcp_module.py", names)
                self.assertIn("src/warband_mcp.py", names)
                for example in (
                    "agent-host.example.json",
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
                for command in (
                    "warband-mcp",
                    "warband-game-bridge",
                    "warband-agent-host",
                    "warband-build-module",
                    "warband-voice",
                    "warband-agent-usability",
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
                        "import module_system.build_mcp_module; "
                        "import warband_agentic.benchmark; "
                        "import warband_agentic.extensions"
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
            ):
                subprocess.run(
                    [installed / "bin" / command, "--help"],
                    cwd=directory,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )


if __name__ == "__main__":
    unittest.main()
