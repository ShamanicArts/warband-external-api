import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from bridge.agent_host import load_agent_host_plan
from bridge.installer import main


def make_native(root: Path) -> Path:
    native = root / "Modules" / "Native"
    native.mkdir(parents=True)
    files = {
        "module.ini": "module_name = Native\nload_resource = test\n",
        "scripts.txt": (
            "scriptsfile version 1\n2\ngame_receive_url_response -1\n"
            " 0 \nother -1\n 0 \n"
        ),
        "strings.txt": "stringsfile version 1\n2\nstr_zero zero\nstr_one one\n",
        "mission_templates.txt": (
            "missionsfile version 1\n1\n"
            "mst_tutorial_training_ground tutorial_training_ground 1 -1\n"
            "Description.\n\n1 0 0 0\n1\n"
            "0.000000 0.000000 0.000000 0 0\n"
        ),
        "simple_triggers.txt": "simple_triggers_file version 1\n1\n1.000000 0\n",
        "menus.txt": (
            "menusfile version 1\n1\nmenu_test 0 Test. none 0 1\n"
            " mno_leave 0 Leave. 1 2040 0 .\n"
        ),
        "dialog_states.txt": (
            "start\nparty_encounter\nprisoner_liberated\nenemy_defeated\n"
            "party_relieved\nevent_triggered\nclose_window\n"
        ),
        "conversation.txt": (
            "dialogsfile version 2\n1\n"
            "dlga_start:close_window 4095 0 0 test 6 0 NO_VOICEOVER\n"
        ),
        "untouched.bin": "user-owned-native-asset",
    }
    for name, content in files.items():
        (native / name).write_text(content, encoding="latin-1")
    return native


class InstallerCliTests(unittest.TestCase):
    def test_plan_is_secret_free_and_does_not_create_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "Modules" / "Native"
            native.mkdir(parents=True)
            (native / "module.ini").write_text("module_name = Native\n")
            install_root = root / "private" / "warband-agentic"
            install_root.parent.mkdir()
            module_output = native.parent / "WarbandMCP"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = main(
                    [
                        "plan",
                        "--native",
                        str(native),
                        "--install-root",
                        str(install_root),
                    ]
                )

            plan = json.loads(stdout.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(plan["schema"], "warband.agentic/install-plan/v1")
            self.assertEqual(plan["native"], str(native))
            self.assertEqual(plan["module_output"], str(module_output))
            self.assertEqual(plan["install_root"], str(install_root))
            self.assertEqual(plan["effects"], [])
            self.assertEqual(
                plan["configuration"]["module_extensions"],
                [{"extension_id": "warband.native", "version": "0.2.0"}],
            )
            self.assertTrue(plan["requirements"]["loopback_port_80_route"])
            self.assertNotIn("token", json.dumps(plan).casefold())
            self.assertFalse(install_root.exists())
            self.assertFalse(module_output.exists())

    def test_apply_builds_private_validated_install_without_mutating_native(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = make_native(root)
            before = {path.name: path.read_bytes() for path in native.iterdir()}
            install_root = root / "private" / "warband-agentic"
            install_root.parent.mkdir()
            module_output = native.parent / "WarbandMCP"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = main(
                    [
                        "apply",
                        "--native",
                        str(native),
                        "--install-root",
                        str(install_root),
                    ]
                )

            receipt = json.loads(stdout.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(receipt["schema"], "warband.agentic/install-receipt/v1")
            self.assertEqual(receipt["state"], "installed")
            self.assertEqual(
                before, {path.name: path.read_bytes() for path in native.iterdir()}
            )
            self.assertTrue((module_output / "mcp-build.json").is_file())
            self.assertTrue((module_output / "mcp-catalog.json").is_file())
            self.assertEqual(module_output.stat().st_mode & 0o777, 0o700)
            config = install_root / "config" / "agent-host.json"
            host_plan = load_agent_host_plan(config)
            self.assertEqual(host_plan.module_protocol, 2)
            self.assertEqual(host_plan.integration_revision, 16)
            self.assertEqual(host_plan.sessions[0].kind, "native-menu")
            credential_paths = sorted((install_root / "runtime").glob("*.credential"))
            self.assertEqual(len(credential_paths), 4)
            values = {path.read_text() for path in credential_paths}
            self.assertEqual(len(values), 4)
            self.assertTrue(all(len(value) == 64 for value in values))
            self.assertTrue(
                all(path.stat().st_mode & 0o777 == 0o600 for path in credential_paths)
            )
            retained = "\n".join(
                path.read_text()
                for path in (
                    install_root / "install-manifest.json",
                    install_root / "config" / "mcp-server.json",
                    install_root / "INSTALL.md",
                )
            )
            self.assertTrue(all(value not in retained for value in values))
            mcp = json.loads((install_root / "config" / "mcp-server.json").read_text())
            self.assertEqual(mcp["env"]["WARBAND_BRIDGE_URL"], "http://127.0.0.1:8765")
            self.assertEqual(
                mcp["env"]["WARBAND_TOKEN_FILE"],
                str(install_root / "runtime" / "bridge.credential"),
            )

    def test_apply_failure_rolls_back_only_new_staging_and_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "Modules" / "Native"
            native.mkdir(parents=True)
            (native / "module.ini").write_text("module_name = Native\n")
            sentinel = native / "keep.txt"
            sentinel.write_text("untouched")
            install_root = root / "private" / "warband-agentic"
            install_root.parent.mkdir()
            module_output = native.parent / "WarbandMCP"

            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(
                        [
                            "apply",
                            "--native",
                            str(native),
                            "--install-root",
                            str(install_root),
                        ]
                    )

            self.assertEqual(sentinel.read_text(), "untouched")
            self.assertFalse(install_root.exists())
            self.assertFalse(module_output.exists())
            self.assertEqual([path.name for path in install_root.parent.iterdir()], [])
            self.assertEqual(
                sorted(path.name for path in native.parent.iterdir()), ["Native"]
            )

    def test_plan_rejects_remote_voice_and_port_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "Modules" / "Native"
            native.mkdir(parents=True)
            (native / "module.ini").write_text("module_name = Native\n")
            install_parent = root / "private"
            install_parent.mkdir()
            base = [
                "plan",
                "--native",
                str(native),
                "--install-root",
                str(install_parent / "kit"),
            ]

            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(
                        [
                            *base,
                            "--kokoro-endpoint",
                            "https://voice.example/v1/audio/speech",
                        ]
                    )
                with self.assertRaises(SystemExit):
                    main([*base, "--voice-port", "8765"])

            self.assertFalse((install_parent / "kit").exists())

    def test_plan_refuses_existing_destinations_without_touching_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "Modules" / "Native"
            native.mkdir(parents=True)
            (native / "module.ini").write_text("module_name = Native\n")
            module_output = native.parent / "WarbandMCP"
            module_output.mkdir()
            sentinel = module_output / "user-file"
            sentinel.write_text("keep")
            install_root = root / "private" / "warband-agentic"
            install_root.parent.mkdir()

            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(
                        [
                            "plan",
                            "--native",
                            str(native),
                            "--install-root",
                            str(install_root),
                        ]
                    )

            self.assertEqual(sentinel.read_text(), "keep")
            self.assertFalse(install_root.exists())


if __name__ == "__main__":
    unittest.main()
