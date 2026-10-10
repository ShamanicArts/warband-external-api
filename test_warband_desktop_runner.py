import argparse
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.warband_desktop_runner import (
    DesktopSafetyFailure,
    advancing_amdgpu_evidence,
    amdgpu_engine_samples,
    build_proton_command,
    build_proton_environment,
    build_rule_lua,
    build_systemd_command,
    call_cua,
    cua_window_target,
    current_control_group_pids,
    desktop_violations,
    image_mean_luminance,
    make_parser,
    process_driver_evidence,
    run_bounded,
    select_owned_cua_window,
    terminate_control_group_descendants,
    workspace_is_inactive,
)


class WarbandDesktopRunnerTests(unittest.TestCase):
    def test_default_cua_session_is_unique_to_the_outer_runner_process(self):
        args = make_parser().parse_args(["run", "--log-dir", "/tmp/proof"])
        self.assertEqual(args.cua_session, f"warband-hidden-{os.getpid()}")

    def test_negative_post_acceptance_hold_is_refused_before_launch(self):
        with self.assertRaisesRegex(DesktopSafetyFailure, "must not be negative"):
            run_bounded(argparse.Namespace(post_acceptance_seconds=-1))

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
            cua=Path("/cua"),
            cua_socket=Path("/cua.sock"),
            auto_play=True,
            launcher_timeout=40,
            play_x=150,
            play_y=212,
            cua_session="test-session",
            post_acceptance_seconds=15,
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
        self.assertIn("--auto-play", command)
        self.assertIn("/cua", command)
        self.assertIn("test-session", command)
        self.assertIn("--post-acceptance-seconds", command)
        self.assertIn("15", command)
        self.assertIn("--game-arg=-m", command)
        self.assertIn("--game-arg=WarbandMCP", command)

    @patch("bridge.warband_desktop_runner.subprocess.run")
    def test_cua_call_uses_exact_socket_and_requires_object_json(self, run):
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout='{"windows":[]}', stderr=""
        )
        response = call_cua(
            Path("/cua"),
            Path("/driver.sock"),
            "list_windows",
            {"session": "test"},
        )
        self.assertEqual(response, {"windows": []})
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ("/cua", "call", "list_windows"))
        self.assertEqual(command[-2:], ("--socket", "/driver.sock"))

        run.return_value = subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
        with self.assertRaisesRegex(DesktopSafetyFailure, "non-object"):
            call_cua(Path("/cua"), Path("/driver.sock"), "list_windows", {})

        run.side_effect = subprocess.TimeoutExpired("cua", 20)
        with self.assertRaisesRegex(DesktopSafetyFailure, "CUA list_windows timed out"):
            call_cua(Path("/cua"), Path("/driver.sock"), "list_windows", {})

    def test_cua_window_selection_is_owned_exact_and_unambiguous(self):
        response = {
            "windows": [
                {
                    "app_name": "steam_app_48700",
                    "pid": 41,
                    "window_id": 3,
                    "width": 640,
                    "height": 480,
                    "title": "Mount&Blade Warband",
                },
                {
                    "app_name": "steam_app_48700",
                    "pid": 99,
                    "window_id": 4,
                    "width": 640,
                    "height": 480,
                    "title": "Mount&Blade Warband",
                },
                {
                    "app_name": "other",
                    "pid": 41,
                    "window_id": 5,
                    "width": 640,
                    "height": 480,
                    "title": "Mount&Blade Warband",
                },
            ]
        }
        selected = select_owned_cua_window(
            response,
            (41,),
            exact_size=(640, 480),
            title="Mount&Blade Warband",
        )
        self.assertEqual(cua_window_target(selected or {}), {"pid": 41, "window_id": 3})

        response["windows"].append(dict(response["windows"][0], window_id=6))
        with self.assertRaisesRegex(DesktopSafetyFailure, "multiple"):
            select_owned_cua_window(response, (41,), exact_size=(640, 480))

    def test_cua_game_window_filter_ignores_bink_and_small_windows(self):
        response = {
            "windows": [
                {
                    "app_name": "steam_app_48700",
                    "pid": 41,
                    "window_id": 7,
                    "width": 1600,
                    "height": 919,
                    "title": "Bink Video",
                },
                {
                    "app_name": "steam_app_48700",
                    "pid": 41,
                    "window_id": 8,
                    "width": 1600,
                    "height": 919,
                    "title": "Mount&Blade Warband",
                },
            ]
        }
        selected = select_owned_cua_window(
            response,
            (41,),
            minimum_size=(1000, 700),
            title="Mount&Blade Warband",
        )
        self.assertEqual(cua_window_target(selected or {})["window_id"], 8)
        with self.assertRaisesRegex(DesktopSafetyFailure, "integer PID"):
            cua_window_target({"pid": 41})

    @patch("bridge.warband_desktop_runner.os.kill")
    @patch("bridge.warband_desktop_runner.current_control_group_pids")
    def test_cleanup_signals_only_exact_cgroup_descendants(self, pids, kill):
        pids.side_effect = [(10, 11, 12), (10,)]
        result = terminate_control_group_descendants(self_pid=10)
        self.assertEqual(result, {"sigterm": [11, 12], "sigkill": []})
        self.assertEqual(
            kill.call_args_list,
            [
                unittest.mock.call(11, 15),
                unittest.mock.call(12, 15),
            ],
        )

    @patch("bridge.warband_desktop_runner.os.kill")
    @patch("bridge.warband_desktop_runner.current_control_group_pids")
    def test_cleanup_kills_only_stubborn_exact_cgroup_descendants(self, pids, kill):
        pids.side_effect = [(10, 11), (10, 11)]
        result = terminate_control_group_descendants(timeout=0, self_pid=10)
        self.assertEqual(result, {"sigterm": [11], "sigkill": [11]})
        self.assertEqual(kill.call_args_list[-1], unittest.mock.call(11, 9))

    @patch("bridge.warband_desktop_runner.shutil.which", return_value="/magick")
    @patch("bridge.warband_desktop_runner.subprocess.run")
    def test_game_capture_luminance_is_bounded(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout="0.386697", stderr=""
        )
        self.assertAlmostEqual(image_mean_luminance(Path("/game.png")), 0.386697)
        self.assertIn("-alpha", run.call_args.args[0])

        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout="not-a-number", stderr=""
        )
        with self.assertRaisesRegex(DesktopSafetyFailure, "invalid luminance"):
            image_mean_luminance(Path("/game.png"))

        run.side_effect = subprocess.TimeoutExpired("magick", 10)
        with self.assertRaisesRegex(DesktopSafetyFailure, "validation timed out"):
            image_mean_luminance(Path("/game.png"))

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
