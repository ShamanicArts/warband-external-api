import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bridge.gpu_safe_runner import (
    SafetyFailure,
    build_gamescope_command,
    build_systemd_command,
    dxvk_proof_error,
    hardware_gl_evidence,
    parse_probe_output,
    process_tree,
    require_hardware_gl_proof,
    run_systemd_bounded,
    software_renderer_evidence,
)


class GpuSafeRunnerTests(unittest.TestCase):
    def test_probe_requires_hardware_headless_xwayland(self):
        output = "\n".join(
            (
                "selecting physical device 'AMD Radeon RX 6600 XT (RADV NAVI23)'",
                "Creating headless backend",
                "Starting Xwayland on :2",
            )
        )
        result = parse_probe_output(output, "1002:73ff")
        self.assertEqual(result.renderer, "AMD Radeon RX 6600 XT (RADV NAVI23)")

    def test_probe_refuses_software_renderer(self):
        output = "\n".join(
            (
                "selecting physical device 'llvmpipe (LLVM 22.1.8)'",
                "Creating headless backend",
                "Starting Xwayland on :2",
            )
        )
        with self.assertRaisesRegex(SafetyFailure, "software renderer"):
            parse_probe_output(output, "1002:73ff")

    def test_process_tree_and_thread_scan_find_llvmpipe(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._process(proc, 10, 1, "gamescope")
            self._process(proc, 11, 10, "Xwayland")
            self._process(proc, 12, 11, "llvmpipe-0")
            self._process(proc, 99, 1, "unrelated")
            pids = process_tree(10, proc)
            self.assertEqual(pids, (10, 11, 12))
            evidence = software_renderer_evidence(pids, proc)
            self.assertEqual(evidence, ("pid 12 thread llvmpipe-0",))

    def test_maps_scan_finds_swrast_but_not_generic_llvm(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._process(proc, 20, 1, "game")
            (proc / "20" / "maps").write_text(
                "7f00 /usr/lib/libLLVM.so\n7f01 /usr/lib/dri/swrast_dri.so\n"
            )
            evidence = software_renderer_evidence((20,), proc)
            self.assertEqual(evidence, ("pid 20 maps /usr/lib/dri/swrast_dri.so",))

    def test_commands_pin_gpu_and_enforce_scope_limits(self):
        game = build_gamescope_command(
            ("game", "--flag"), "1002:73ff", 800, 600, 30
        )
        self.assertIn("headless", game)
        self.assertIn("1002:73ff", game)
        self.assertNotIn("--steam", game)
        self.assertEqual(game[-2:], ["game", "--flag"])
        steam_game = build_gamescope_command(
            ("game",), "1002:73ff", 800, 600, 30, steam_integration=True
        )
        self.assertIn("--steam", steam_game)
        args = argparse.Namespace(
            gpu="1002:73ff",
            renderer="AMD Radeon RX 6600 XT",
            width=800,
            height=600,
            fps=30,
            max_runtime=60,
            log_dir=Path("/tmp/warband-test"),
            require_dxvk=True,
            require_hardware_gl=True,
            hardware_process="mb_warband.exe",
            hardware_driver="radeonsi_dri.so",
            hardware_deadline=45,
            steam_integration=False,
            cpu_quota=250,
            memory_high="2G",
            memory_max="3G",
            tasks_max=256,
            command=["game"],
        )
        with patch("bridge.gpu_safe_runner.sys.executable", "/usr/bin/python"):
            unit = build_systemd_command(
                args,
                Path("/repo/runner.py"),
                Path("/repo"),
                "warband-gpu-test.service",
            )
        self.assertIn("CPUQuota=250%", unit)
        self.assertIn("MemoryMax=3G", unit)
        self.assertIn("TasksMax=256", unit)
        self.assertIn("Nice=10", unit)
        self.assertIn("KillMode=control-group", unit)
        self.assertIn("TimeoutStopSec=5s", unit)
        self.assertIn("RuntimeMaxSec=90s", unit)
        self.assertIn("WorkingDirectory=/repo", unit)
        self.assertIn("--unit=warband-gpu-test.service", unit)
        self.assertIn("--require-dxvk", unit)
        self.assertIn("--require-hardware-gl", unit)
        self.assertIn("radeonsi_dri.so", unit)
        self.assertIn("45", unit)

    def test_interrupt_stops_only_the_exact_transient_unit(self):
        args = Mock()
        with (
            patch(
                "bridge.gpu_safe_runner.build_systemd_command",
                return_value=["systemd-run"],
            ) as build,
            patch(
                "bridge.gpu_safe_runner.subprocess.call",
                side_effect=KeyboardInterrupt,
            ),
            patch("bridge.gpu_safe_runner.subprocess.run") as stop,
            patch("bridge.gpu_safe_runner.os.getpid", return_value=321),
        ):
            status = run_systemd_bounded(args, Path("/repo/runner.py"))
        self.assertEqual(status, 130)
        build.assert_called_once_with(
            args,
            Path("/repo/runner.py"),
            unit_name="warband-gpu-321.service",
        )
        stop.assert_called_once_with(
            [
                "systemctl",
                "--user",
                "stop",
                "warband-gpu-321.service",
            ],
            check=False,
            timeout=10,
        )

    def test_required_hardware_proof_refuses_an_early_child_exit(self):
        with self.assertRaisesRegex(SafetyFailure, "exited before"):
            require_hardware_gl_proof(required=True, proven=False)
        require_hardware_gl_proof(required=True, proven=True)
        require_hardware_gl_proof(required=False, proven=False)

    def test_hardware_gl_proof_is_bound_to_game_process(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            self._process(proc, 30, 1, "gamescope")
            self._process(proc, 31, 30, "mb_warband.exe")
            (proc / "30" / "maps").write_text(
                "7f00 /usr/lib/dri/radeonsi_dri.so\n"
            )
            self.assertEqual(
                hardware_gl_evidence(
                    (30, 31), "mb_warband.exe", "radeonsi_dri.so", proc
                ),
                (),
            )
            (proc / "31" / "maps").write_text(
                "7f01 /usr/lib32/dri/radeonsi_dri.so\n"
            )
            proof = hardware_gl_evidence(
                (30, 31), "mb_warband.exe", "radeonsi_dri.so", proc
            )
            self.assertEqual(proof[0]["pid"], 31)
            self.assertEqual(proof[0]["process"], "mb_warband.exe")

    def test_dxvk_proof_requires_matching_dll_native_load_and_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            (logs / "dxvk-proof.json").write_text(
                '{"dxvk_d3d9_match": true, "d3d9_sha256": "'
                + "a" * 64
                + '"}\n'
            )
            (logs / "steam-48700.log").write_text(
                'Loaded L"C:\\\\windows\\\\system32\\\\d3d9.dll" '
                "at 7A810000: native\n"
            )
            (logs / "gamescope.log").write_text(
                "selecting physical device 'AMD Radeon RX 6600 XT (RADV)'\n"
            )
            self.assertIsNone(dxvk_proof_error(logs, "AMD Radeon RX 6600 XT"))
            (logs / "steam-48700.log").write_text(
                'Loaded L"C:\\\\windows\\\\system32\\\\d3d9.dll" '
                "at 7A810000: builtin\n"
            )
            self.assertIn(
                "native DXVK", dxvk_proof_error(logs, "AMD Radeon RX 6600 XT")
            )

    @staticmethod
    def _process(root: Path, pid: int, parent: int, thread_name: str) -> None:
        process = root / str(pid)
        task = process / "task" / str(pid)
        task.mkdir(parents=True)
        (process / "stat").write_text(
            f"{pid} ({thread_name}) S {parent} 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"
        )
        (process / "maps").write_text("")
        (process / "comm").write_text(f"{thread_name}\n")
        (task / "comm").write_text(f"{thread_name}\n")


if __name__ == "__main__":
    unittest.main()
