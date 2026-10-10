import argparse
import tempfile
import unittest
from pathlib import Path

from bridge.warband_desktop_runner import (
    DesktopSafetyFailure,
    advancing_amdgpu_evidence,
    amdgpu_engine_samples,
    build_proton_command,
    build_proton_environment,
    build_rule_lua,
    build_systemd_command,
    current_control_group_pids,
    desktop_violations,
    process_driver_evidence,
    workspace_is_inactive,
)


class WarbandDesktopRunnerTests(unittest.TestCase):
    def test_proton_command_uses_the_launcher_mapping_verb(self):
        self.assertEqual(
            build_proton_command(
                Path("/proton"), Path("/game/mb_warband.exe"), ("-m", "WarbandMCP")
            ),
            ["/proton", "runinprefix", "mb_warband.exe", "-m", "WarbandMCP"],
        )

    def test_rule_is_silent_and_denies_focus_before_launch(self):
        rule = build_rule_lua("name:warband-agent")
        self.assertIn('workspace = "name:warband-agent silent"', rule)
        self.assertIn("no_initial_focus = true", rule)
        self.assertIn("focus_on_activate = false", rule)
        self.assertNotIn("suppress_event", rule)
        self.assertIn('initial_class = "^steam_app_48700$"', rule)
        with self.assertRaisesRegex(DesktopSafetyFailure, "unsafe workspace"):
            build_rule_lua('name:bad"; os.execute("nope")')

    def test_workspace_must_be_absent_and_not_visible(self):
        monitors = [{"activeWorkspace": {"name": "11"}}]
        self.assertTrue(workspace_is_inactive("name:agent", monitors, []))
        self.assertFalse(
            workspace_is_inactive(
                "name:agent", monitors, [{"name": "agent", "windows": 1}]
            )
        )
        self.assertFalse(
            workspace_is_inactive(
                "name:agent", [{"activeWorkspace": {"name": "agent"}}], []
            )
        )

    def test_desktop_guard_rejects_wrong_workspace_focus_or_visibility(self):
        client = {
            "address": "0x1",
            "class": "steam_app_48700",
            "workspace": {"name": "wrong"},
        }
        violations = desktop_violations(
            [client],
            {"address": "0x1"},
            [{"activeWorkspace": {"name": "warband-agent"}}],
            "name:warband-agent",
        )
        self.assertIn("Warband window mapped on workspace 'wrong'", violations)
        self.assertIn("Warband became the active window", violations)
        self.assertIn("agent workspace became visible", violations)

    def test_environment_forces_dxvk_amd_and_removes_software_overrides(self):
        environment = build_proton_environment(
            {
                "DISPLAY": ":0",
                "WAYLAND_DISPLAY": "wayland-1",
                "PROTON_USE_WINED3D": "1",
                "LIBGL_ALWAYS_SOFTWARE": "1",
                "GALLIUM_DRIVER": "llvmpipe",
            },
            Path("/prefix"),
            Path("/game/mb_warband.exe"),
            Path("/logs"),
            "dxvk",
        )
        self.assertNotIn("PROTON_USE_WINED3D", environment)
        self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", environment)
        self.assertNotIn("GALLIUM_DRIVER", environment)
        self.assertNotIn("WAYLAND_DISPLAY", environment)
        self.assertEqual(environment["DISPLAY"], ":0")
        self.assertEqual(environment["MESA_VK_DEVICE_SELECT"], "1002:73ff!")
        self.assertEqual(
            environment["DXVK_FILTER_DEVICE_NAME"], "AMD Radeon RX 6600 XT"
        )
        self.assertEqual(environment["WINEDLLOVERRIDES"], "d3d9=n")

        hardware_gl = build_proton_environment(
            {"DISPLAY": ":0", "LIBGL_ALWAYS_SOFTWARE": "1"},
            Path("/prefix"),
            Path("/game/mb_warband.exe"),
            Path("/logs"),
            "wined3d",
        )
        self.assertEqual(hardware_gl["PROTON_USE_WINED3D"], "1")
        self.assertEqual(hardware_gl["WINE_DISABLE_FULLSCREEN_HACK"], "1")
        self.assertEqual(hardware_gl["WINEDLLOVERRIDES"], "d3d9=b")
        self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", hardware_gl)
        self.assertNotIn("DXVK_FILTER_DEVICE_NAME", hardware_gl)

    def test_systemd_scope_caps_resources_and_preserves_arguments(self):
        args = argparse.Namespace(
            workspace="name:warband-agent",
            max_runtime=120,
            hardware_deadline=90,
            graphics_backend="dxvk",
            log_dir=Path("/tmp/run"),
            prefix=Path("/prefix"),
            proton=Path("/proton"),
            game=Path("/game"),
            cua_socket=Path("/cua.sock"),
            game_arguments=["-m", "WarbandMCP"],
            cpu_quota=200,
            memory_high="1500M",
            memory_max="2G",
            tasks_max=192,
        )
        command = build_systemd_command(args, Path("/runner.py"), "unit.service")
        self.assertIn("CPUQuota=200%", command)
        self.assertIn("MemoryHigh=1500M", command)
        self.assertIn("MemoryMax=2G", command)
        self.assertIn("TasksMax=192", command)
        self.assertIn("KillMode=control-group", command)
        self.assertIn("--game-arg=-m", command)
        self.assertIn("--game-arg=WarbandMCP", command)

    def test_cgroup_and_game_driver_proof_are_bound_to_owned_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "proc"
            cgroup = root / "cgroup"
            (proc / "self").mkdir(parents=True)
            (proc / "self/cgroup").write_text("0::/user.slice/warband.service\n")
            group = cgroup / "user.slice/warband.service"
            group.mkdir(parents=True)
            (group / "cgroup.procs").write_text("30\n31\n")
            self.assertEqual(current_control_group_pids(proc, cgroup), (30, 31))
            for pid, name, maps in (
                (30, "python", "/usr/lib32/libvulkan_radeon.so"),
                (31, "mb_warband.exe", "/usr/lib32/libvulkan_radeon.so"),
            ):
                process = proc / str(pid)
                process.mkdir()
                (process / "comm").write_text(name + "\n")
                (process / "maps").write_text("7f00 " + maps + "\n")
            proof = process_driver_evidence((30, 31), proc_root=proc)
            self.assertEqual(len(proof), 1)
            self.assertEqual(proof[0]["pid"], 31)

    def test_drm_proof_requires_owned_amd_gfx_engine_to_advance(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "41"
            (process / "fdinfo").mkdir(parents=True)
            (process / "fd").mkdir()
            (process / "fd/9").symlink_to("/dev/dri/renderD129")
            info = process / "fdinfo/9"
            info.write_text(
                "drm-driver:\tamdgpu\ndrm-client-id:\t77\ndrm-engine-gfx:\t100 ns\n"
            )
            before = amdgpu_engine_samples((41,), proc)
            self.assertEqual(before[(41, "77")]["gfx_ns"], 100)
            self.assertEqual(advancing_amdgpu_evidence(before, before), ())
            info.write_text(
                "drm-driver:\tamdgpu\ndrm-client-id:\t77\ndrm-engine-gfx:\t175 ns\n"
            )
            after = amdgpu_engine_samples((41,), proc)
            proof = advancing_amdgpu_evidence(before, after)
            self.assertEqual(proof[0]["gfx_delta_ns"], 75)
            self.assertEqual(proof[0]["driver"], "amdgpu")


if __name__ == "__main__":
    unittest.main()
