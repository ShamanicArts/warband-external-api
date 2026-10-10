#!/usr/bin/env python3
"""Run graphical game tests in an isolated, GPU-backed, resource-bounded scope."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_GPU = "1002:73ff"
DEFAULT_RENDERER = "AMD Radeon RX 6600 XT"
SOFTWARE_MARKERS = ("llvmpipe", "softpipe", "lavapipe", "swrast")
GPU_PATTERN = re.compile(r"selecting physical device '([^']+)'")


class SafetyFailure(RuntimeError):
    """The launch could not prove or preserve the required safety boundary."""


@dataclass(frozen=True)
class ProbeResult:
    gpu_selector: str
    renderer: str
    backend: str = "gamescope-headless"


@dataclass(frozen=True)
class ProcessSample:
    pids: tuple[int, ...]
    rss_kib: int
    cpu_ticks: int


def contains_software_renderer(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in SOFTWARE_MARKERS)


def parse_probe_output(output: str, gpu_selector: str) -> ProbeResult:
    if contains_software_renderer(output):
        raise SafetyFailure("gamescope probe reported a software renderer")
    match = GPU_PATTERN.search(output)
    if match is None:
        raise SafetyFailure("gamescope probe did not identify its physical GPU")
    renderer = match.group(1)
    if contains_software_renderer(renderer):
        raise SafetyFailure(f"gamescope selected forbidden renderer: {renderer}")
    if "Creating headless backend" not in output:
        raise SafetyFailure("gamescope did not establish the headless backend")
    if "Starting Xwayland on" not in output:
        raise SafetyFailure("gamescope did not establish an isolated Xwayland display")
    return ProbeResult(gpu_selector, renderer)


def build_probe_command(gpu_selector: str) -> list[str]:
    return [
        "gamescope",
        "--backend",
        "headless",
        "--prefer-vk-device",
        gpu_selector,
        "-W",
        "640",
        "-H",
        "480",
        "-w",
        "640",
        "-h",
        "480",
        "-r",
        "30",
        "--xwayland-count",
        "1",
        "--",
        "/usr/bin/true",
    ]


def probe_hardware(gpu_selector: str, timeout: float = 15.0) -> ProbeResult:
    if shutil.which("gamescope") is None:
        raise SafetyFailure("gamescope is not installed")
    try:
        completed = subprocess.run(
            build_probe_command(gpu_selector),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SafetyFailure("gamescope hardware probe timed out") from error
    if completed.returncode != 0:
        raise SafetyFailure(
            f"gamescope hardware probe failed with status {completed.returncode}"
        )
    return parse_probe_output(completed.stdout, gpu_selector)


def _read_ppid(stat_path: Path) -> int | None:
    try:
        text = stat_path.read_text()
        fields = text[text.rfind(")") + 1 :].split()
        return int(fields[1])
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return None


def process_tree(root_pid: int, proc_root: Path = Path("/proc")) -> tuple[int, ...]:
    parents: dict[int, int] = {}
    try:
        entries = tuple(proc_root.iterdir())
    except OSError:
        return (root_pid,)
    for entry in entries:
        if not entry.name.isdigit():
            continue
        parent = _read_ppid(entry / "stat")
        if parent is not None:
            parents[int(entry.name)] = parent

    found = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in found and pid not in found:
                found.add(pid)
                changed = True
    return tuple(sorted(found))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return ""


def software_renderer_evidence(
    pids: Iterable[int], proc_root: Path = Path("/proc")
) -> tuple[str, ...]:
    evidence: set[str] = set()
    for pid in pids:
        process = proc_root / str(pid)
        maps = _read_text(process / "maps")
        for line in maps.splitlines():
            if contains_software_renderer(line):
                evidence.add(f"pid {pid} maps {line.rsplit(' ', 1)[-1]}")
        task_root = process / "task"
        try:
            tasks = tuple(task_root.iterdir())
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            tasks = ()
        for task in tasks:
            name = _read_text(task / "comm").strip()
            if contains_software_renderer(name):
                evidence.add(f"pid {pid} thread {name}")
    return tuple(sorted(evidence))


def hardware_gl_evidence(
    pids: Iterable[int],
    process_name: str,
    driver_name: str,
    proc_root: Path = Path("/proc"),
) -> tuple[dict[str, object], ...]:
    evidence: list[dict[str, object]] = []
    for pid in pids:
        process = proc_root / str(pid)
        comm = _read_text(process / "comm").strip()
        if comm.casefold() != process_name.casefold():
            continue
        matches = sorted(
            {
                line.rsplit(" ", 1)[-1]
                for line in _read_text(process / "maps").splitlines()
                if driver_name.casefold() in line.casefold()
            }
        )
        if matches:
            evidence.append(
                {"driver_mappings": matches, "pid": pid, "process": comm}
            )
    return tuple(evidence)


def sample_processes(
    pids: Iterable[int], proc_root: Path = Path("/proc")
) -> ProcessSample:
    live: list[int] = []
    rss_kib = 0
    cpu_ticks = 0
    for pid in pids:
        process = proc_root / str(pid)
        stat = _read_text(process / "stat")
        if not stat:
            continue
        fields = stat[stat.rfind(")") + 1 :].split()
        try:
            cpu_ticks += int(fields[11]) + int(fields[12])
        except (IndexError, ValueError):
            pass
        status = _read_text(process / "status")
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                try:
                    rss_kib += int(line.split()[1])
                except (IndexError, ValueError):
                    pass
                break
        live.append(pid)
    return ProcessSample(tuple(live), rss_kib, cpu_ticks)


def build_gamescope_command(
    command: Sequence[str],
    gpu_selector: str,
    width: int,
    height: int,
    fps: int,
    steam_integration: bool = False,
) -> list[str]:
    gamescope = [
        "gamescope",
        "--backend",
        "headless",
        "--prefer-vk-device",
        gpu_selector,
        "-W",
        str(width),
        "-H",
        str(height),
        "-w",
        str(width),
        "-h",
        str(height),
        "-r",
        str(fps),
        "--framerate-limit",
        str(fps),
        "--xwayland-count",
        "1",
    ]
    if steam_integration:
        gamescope.append("--steam")
    return [*gamescope, "--", *command]


def build_systemd_command(
    args: argparse.Namespace,
    script: Path,
    working_directory: Path | None = None,
    unit_name: str | None = None,
) -> list[str]:
    working_directory = working_directory or Path.cwd()
    unit_name = unit_name or f"warband-gpu-{os.getpid()}.service"
    inner = [
        sys.executable,
        str(script),
        "run",
        "--bounded",
        "--gpu",
        args.gpu,
        "--renderer",
        args.renderer,
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--fps",
        str(args.fps),
        "--max-runtime",
        str(args.max_runtime),
        "--log-dir",
        str(args.log_dir),
    ]
    if args.require_dxvk:
        inner.append("--require-dxvk")
    if args.require_hardware_gl:
        inner.extend(
            (
                "--require-hardware-gl",
                "--hardware-process",
                args.hardware_process,
                "--hardware-driver",
                args.hardware_driver,
                "--hardware-deadline",
                str(args.hardware_deadline),
            )
        )
    if args.steam_integration:
        inner.append("--steam-integration")
    inner.extend(("--", *args.command))
    return [
        "systemd-run",
        "--user",
        f"--unit={unit_name}",
        "--wait",
        "--pipe",
        "--quiet",
        "--collect",
        "-p",
        "Type=exec",
        "-p",
        "KillMode=control-group",
        "-p",
        "TimeoutStopSec=5s",
        "-p",
        f"RuntimeMaxSec={int(args.max_runtime) + 30}s",
        "-p",
        f"CPUQuota={args.cpu_quota}%",
        "-p",
        f"MemoryHigh={args.memory_high}",
        "-p",
        f"MemoryMax={args.memory_max}",
        "-p",
        f"TasksMax={args.tasks_max}",
        "-p",
        "Nice=10",
        "-p",
        f"WorkingDirectory={working_directory}",
        "--",
        *inner,
    ]


def run_systemd_bounded(args: argparse.Namespace, script: Path) -> int:
    unit_name = f"warband-gpu-{os.getpid()}.service"
    command = build_systemd_command(args, script, unit_name=unit_name)
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        subprocess.run(
            ["systemctl", "--user", "stop", unit_name],
            check=False,
            timeout=10,
        )
        return 130


def _scan_logs(log_dir: Path) -> str:
    chunks: list[str] = []
    for pattern in ("*.log", "*.json"):
        for path in sorted(log_dir.glob(pattern)):
            chunks.append(_read_text(path))
    return "\n".join(chunks)


def dxvk_proof_error(log_dir: Path, renderer: str) -> str | None:
    proof_path = log_dir / "dxvk-proof.json"
    try:
        proof = json.loads(proof_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "DXVK preflight proof is missing or malformed"
    if proof.get("dxvk_d3d9_match") is not True:
        return "isolated-prefix d3d9.dll does not match Proton DXVK"
    digest = proof.get("d3d9_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return "DXVK preflight proof has no valid d3d9.dll digest"

    proton_logs = "\n".join(
        _read_text(path) for path in sorted(log_dir.glob("steam-*.log"))
    )
    loaded_native = re.search(
        r'Loaded L"[^"\n]*\\\\d3d9\.dll"[^\n]*: native',
        proton_logs,
        re.IGNORECASE,
    )
    if loaded_native is None:
        return "Proton has not logged the native DXVK d3d9.dll load"
    if renderer.lower() not in _read_text(log_dir / "gamescope.log").lower():
        return "gamescope log does not identify the required hardware renderer"
    return None


def _stop_process_group(
    process: subprocess.Popen[bytes], grace_seconds: float = 5.0
) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace_seconds)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=grace_seconds)


def require_hardware_gl_proof(required: bool, proven: bool) -> None:
    if required and not proven:
        raise SafetyFailure(
            "guarded command exited before the game process proved hardware GL"
        )


def run_guarded(args: argparse.Namespace) -> int:
    probe = probe_hardware(args.gpu)
    if args.renderer.lower() not in probe.renderer.lower():
        raise SafetyFailure(
            f"selected GPU {probe.renderer!r} does not match {args.renderer!r}"
        )

    log_dir = args.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    gamescope_log = log_dir / "gamescope.log"
    environment = os.environ.copy()
    environment.pop("PROTON_USE_WINED3D", None)
    environment.update(
        {
            "DRI_PRIME": "pci-0000_08_00_0",
            "MESA_VK_DEVICE_SELECT": f"{args.gpu}!",
            "__GLX_VENDOR_LIBRARY_NAME": "mesa",
            "DXVK_LOG_LEVEL": "info",
            "DXVK_LOG_PATH": str(log_dir),
            "WARBAND_GPU_LOG_DIR": str(log_dir),
            "WARBAND_GPU_PRIVATE_DISPLAY": "1",
        }
    )
    command = build_gamescope_command(
        args.command,
        args.gpu,
        args.width,
        args.height,
        args.fps,
        args.steam_integration,
    )
    started = time.monotonic()
    last_report = started
    last_sample_time = started
    last_ticks = 0
    dxvk_deadline = started + 30.0
    hardware_deadline = started + args.hardware_deadline
    hardware_proven = not args.require_hardware_gl

    with gamescope_log.open("wb") as output:
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            while process.poll() is None:
                now = time.monotonic()
                pids = process_tree(process.pid)
                evidence = software_renderer_evidence(pids)
                logs = _scan_logs(log_dir)
                if contains_software_renderer(logs):
                    evidence = (*evidence, "runtime log contains software renderer")
                if evidence:
                    raise SafetyFailure("; ".join(dict.fromkeys(evidence)))
                if not hardware_proven:
                    hardware = hardware_gl_evidence(
                        pids, args.hardware_process, args.hardware_driver
                    )
                    if hardware:
                        hardware_proven = True
                        proof = {
                            "driver": args.hardware_driver,
                            "processes": hardware,
                            "renderer": probe.renderer,
                        }
                        (log_dir / "hardware-gl-proof.json").write_text(
                            json.dumps(proof, indent=2, sort_keys=True) + "\n"
                        )
                    elif now >= hardware_deadline:
                        raise SafetyFailure(
                            f"{args.hardware_process} did not map "
                            f"{args.hardware_driver} within "
                            f"{args.hardware_deadline:.0f}s"
                        )
                if args.require_dxvk and now >= dxvk_deadline:
                    proof_error = dxvk_proof_error(log_dir, args.renderer)
                    if proof_error is not None:
                        raise SafetyFailure(f"{proof_error} within 30s")
                if now - started >= args.max_runtime:
                    raise TimeoutError(
                        f"bounded game run reached {args.max_runtime:.0f}s"
                    )
                if now - last_report >= 5.0:
                    sample = sample_processes(pids)
                    elapsed = max(now - last_sample_time, 0.001)
                    tick_delta = max(sample.cpu_ticks - last_ticks, 0)
                    cpu_percent = tick_delta / os.sysconf("SC_CLK_TCK") / elapsed * 100
                    print(
                        f"guard: pids={len(sample.pids)} "
                        f"rss={sample.rss_kib / 1024:.1f}MiB cpu={cpu_percent:.1f}%",
                        file=sys.stderr,
                        flush=True,
                    )
                    last_report = now
                    last_sample_time = now
                    last_ticks = sample.cpu_ticks
                time.sleep(0.5)
            require_hardware_gl_proof(args.require_hardware_gl, hardware_proven)
            return process.returncode or 0
        except TimeoutError as error:
            print(f"gpu-safe-runner: {error}", file=sys.stderr)
            return 124
        finally:
            _stop_process_group(process)


def _write_probe(path: Path | None, probe: ProbeResult) -> None:
    payload = json.dumps(asdict(probe), indent=2, sort_keys=True) + "\n"
    if path is None:
        print(payload, end="")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    probe = subparsers.add_parser("probe", help="prove the headless hardware path")
    probe.add_argument("--gpu", default=DEFAULT_GPU)
    probe.add_argument("--json-out", type=Path)

    run = subparsers.add_parser("run", help="run a command behind the safety guard")
    run.add_argument("--gpu", default=DEFAULT_GPU)
    run.add_argument("--renderer", default=DEFAULT_RENDERER)
    run.add_argument("--width", type=int, default=1600)
    run.add_argument("--height", type=int, default=900)
    run.add_argument("--fps", type=int, default=60)
    run.add_argument("--max-runtime", type=float, default=900.0)
    run.add_argument("--cpu-quota", type=int, default=250)
    run.add_argument("--memory-high", default="2G")
    run.add_argument("--memory-max", default="3G")
    run.add_argument("--tasks-max", type=int, default=256)
    run.add_argument("--require-dxvk", action="store_true")
    run.add_argument("--steam-integration", action="store_true")
    run.add_argument("--require-hardware-gl", action="store_true")
    run.add_argument("--hardware-process", default="mb_warband.exe")
    run.add_argument("--hardware-driver", default="radeonsi_dri.so")
    run.add_argument("--hardware-deadline", type=float, default=20.0)
    run.add_argument("--bounded", action="store_true", help=argparse.SUPPRESS)
    run.add_argument(
        "--log-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "warband-gpu-safe",
    )
    run.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "probe":
            result = probe_hardware(args.gpu)
            _write_probe(args.json_out, result)
            return 0
        if args.command[:1] == ["--"]:
            args.command = args.command[1:]
        if not args.command:
            parser.error("run requires a command after --")
        if not args.bounded:
            if shutil.which("systemd-run") is None:
                raise SafetyFailure("systemd-run is required for resource limits")
            return run_systemd_bounded(args, Path(__file__).resolve())
        return run_guarded(args)
    except SafetyFailure as error:
        print(f"gpu-safe-runner: REFUSED: {error}", file=sys.stderr)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
