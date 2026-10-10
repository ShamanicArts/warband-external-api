import tempfile
import unittest
from pathlib import Path

from bridge.warband_gpu_supervisor import (
    SupervisorFailure,
    build_cua_command,
    build_cua_environment,
    build_proton_command,
    build_proton_environment,
    prove_dxvk_install,
    require_private_gamescope_display,
)


class WarbandGpuSupervisorTests(unittest.TestCase):
    def test_requires_private_gamescope_display(self):
        environment = {
            "DISPLAY": ":2",
            "WARBAND_GPU_LOG_DIR": "/tmp/private-run",
            "WARBAND_GPU_PRIVATE_DISPLAY": "1",
        }
        self.assertEqual(require_private_gamescope_display(environment), ":2")
        with self.assertRaisesRegex(SupervisorFailure, "desktop X display"):
            require_private_gamescope_display({**environment, "DISPLAY": ":0"})
        with self.assertRaisesRegex(SupervisorFailure, "private-display marker"):
            require_private_gamescope_display(
                {
                    key: value
                    for key, value in environment.items()
                    if key != "WARBAND_GPU_PRIVATE_DISPLAY"
                }
            )

    def test_cua_is_bound_to_private_socket_without_overlay(self):
        command = build_cua_command(
            Path("/bin/cua"), Path("/run/private.sock"), Path("/run/private.pid")
        )
        self.assertEqual(command[1], "serve")
        self.assertIn("/run/private.sock", command)
        self.assertIn("--no-overlay", command)

    def test_cua_isolated_from_host_wayland(self):
        base = {
            "DISPLAY": ":2",
            "WAYLAND_DISPLAY": "wayland-1",
            "CUA_DRIVER_RS_ENABLE_WAYLAND": "stale",
        }
        x11 = build_cua_environment(base)
        self.assertNotIn("WAYLAND_DISPLAY", x11)
        self.assertNotIn("CUA_DRIVER_RS_ENABLE_WAYLAND", x11)
        self.assertEqual(x11["XDG_SESSION_TYPE"], "x11")

    def test_proton_uses_initialized_dxvk_path(self):
        proton = Path("/opt/proton/proton")
        game = Path("/games/warband/mb_warband.exe")
        self.assertEqual(
            build_proton_command(proton, game, "dxvk", ("-m", "WarbandMCP")),
            [
                str(proton),
                "waitforexitandrun",
                str(game),
                "-m",
                "WarbandMCP",
            ],
        )
        self.assertEqual(
            build_proton_command(proton, game, "dxvk"),
            [str(proton), "waitforexitandrun", str(game)],
        )
        self.assertEqual(
            build_proton_command(proton, game, "wined3d", ("-m", "WarbandMCP")),
            [
                str(proton),
                "runinprefix",
                "mb_warband.exe",
                "-m",
                "WarbandMCP",
            ],
        )
        environment = build_proton_environment(
            {
                "DISPLAY": ":2",
                "WAYLAND_DISPLAY": "gamescope-0",
                "PROTON_USE_WINED3D": "1",
            },
            Path("/tmp/prefix"),
            game,
            Path("/tmp/logs"),
            "dxvk",
        )
        self.assertNotIn("WAYLAND_DISPLAY", environment)
        self.assertNotIn("PROTON_USE_WINED3D", environment)
        self.assertEqual(
            environment["DXVK_FILTER_DEVICE_NAME"], "AMD Radeon RX 6600 XT"
        )
        self.assertEqual(environment["PROTON_LOG"], "1")
        self.assertEqual(environment["STEAM_COMPAT_DATA_PATH"], "/tmp/prefix")

        wined3d = build_proton_environment(
            {"DISPLAY": ":2"},
            Path("/tmp/prefix"),
            game,
            Path("/tmp/logs"),
            "wined3d",
        )
        self.assertEqual(wined3d["PROTON_USE_WINED3D"], "1")
        self.assertEqual(wined3d["WINE_DISABLE_FULLSCREEN_HACK"], "1")
        self.assertNotIn("DXVK_FILTER_DEVICE_NAME", wined3d)

    def test_dxvk_preflight_hashes_proton_and_prefix_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proton = root / "proton"
            proton.touch()
            source = root / "files/lib/wine/dxvk/d3d9.dll"
            installed = root / "prefix/pfx/drive_c/windows/syswow64/d3d9.dll"
            source.parent.mkdir(parents=True)
            installed.parent.mkdir(parents=True)
            source.write_bytes(b"dxvk-binary")
            installed.write_bytes(b"dxvk-binary")
            proof = prove_dxvk_install(proton, root / "prefix")
            self.assertTrue(proof["dxvk_d3d9_match"])
            self.assertEqual(len(proof["d3d9_sha256"]), 64)
            installed.write_bytes(b"wined3d-binary")
            with self.assertRaisesRegex(SupervisorFailure, "does not match"):
                prove_dxvk_install(proton, root / "prefix")


if __name__ == "__main__":
    unittest.main()
