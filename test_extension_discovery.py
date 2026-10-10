import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InstalledExtensionDiscoveryTests(unittest.TestCase):
    def test_host_cli_loads_only_explicitly_named_extension_entry_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = Path(__file__).parent
            (root / "example_plugin.py").write_text(
                """
from warband_agentic import (
    AgenticExtension, ApplicationKind, ExtensionBundle, RoleId
)

def extension_bundle():
    def factory(backend, session_id, *, event_log, agent_id):
        raise AssertionError("check mode must not construct applications")

    application = ApplicationKind(
        "example-observer",
        "Example installed observer",
        {
            "type": "object",
            "properties": {"agent_id": {"type": "integer", "minimum": 0}},
            "required": ("agent_id",),
            "additionalProperties": False,
        },
        (RoleId.OBSERVER_READONLY,),
        (),
        (),
        (),
        False,
    )
    extension = AgenticExtension(
        "example.observer", "1.0.0", "Installed extension fixture",
        2, 16, 16, (application,)
    )
    return ExtensionBundle(extension, {"example-observer": factory})
""".strip()
                + "\n"
            )
            distribution = root / "example_observer-1.0.0.dist-info"
            distribution.mkdir()
            (distribution / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: example-observer\nVersion: 1.0.0\n"
            )
            (distribution / "entry_points.txt").write_text(
                "[warband_agentic.extensions]\n"
                "example.observer = example_plugin:extension_bundle\n"
                "poison.extension = module_that_does_not_exist:bundle\n"
            )
            (root / "mcp-catalog.json").write_text(json.dumps({}))
            (root / "mcp-build.json").write_text(
                json.dumps({"protocol": 2, "integration_revision": 16})
            )
            for name, token in (
                ("bridge", "1" * 64),
                ("control", "2" * 64),
                ("observer", "3" * 64),
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
                            "port": 8765,
                        },
                        "control": {
                            "token_file": "control.token",
                            "port": 8766,
                        },
                        "events_database": "events.sqlite3",
                        "sessions": [
                            {
                                "kind": "example-observer",
                                "session_id": "observer",
                                "token_file": "observer.token",
                                "port": 8869,
                                "agent_id": 7,
                            }
                        ],
                    }
                )
            )
            environment = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join((str(root), str(checkout))),
            }
            command = [
                sys.executable,
                "-m",
                "bridge.agent_host",
                "--config",
                str(config),
                "--extension",
                "example.observer",
                "--check",
            ]
            result = subprocess.run(
                command,
                cwd=checkout,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            diagnostics = json.loads(result.stdout)
            self.assertEqual(
                diagnostics["extensions"],
                [
                    {"extension_id": "example.observer", "version": "1.0.0"},
                    {"extension_id": "warband.native", "version": "0.2.0"},
                ],
            )
            self.assertFalse((root / "bridge.sqlite3").exists())
            self.assertFalse((root / "events.sqlite3").exists())

            missing = subprocess.run(
                [*command[:-3], "--extension", "absent.extension", "--check"],
                cwd=checkout,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(missing.returncode, 2)
            self.assertIn("absent.extension is not installed", missing.stderr)
            self.assertNotIn("1" * 64, missing.stderr)


if __name__ == "__main__":
    unittest.main()
