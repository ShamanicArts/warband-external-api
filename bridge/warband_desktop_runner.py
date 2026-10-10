#!/usr/bin/env python3
"""Run Warband on desktop XWayland without focus theft or software rendering."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

if __package__:
    from bridge.gpu_safe_runner import (
        DEFAULT_GPU,
        DEFAULT_RENDERER,
        SafetyFailure,
        contains_software_renderer,
        probe_hardware,
        sample_processes,
        software_renderer_evidence,
    )
    from bridge.warband_gpu_supervisor import (
        DEFAULT_GAME,
        DEFAULT_PROTON,
        STEAM_ROOT,
        prove_dxvk_install,
    )
else:
    from gpu_safe_runner import (
        DEFAULT_GPU,
        DEFAULT_RENDERER,
        SafetyFailure,
        contains_software_renderer,
        probe_hardware,
        sample_processes,
        software_renderer_evidence,
    )
    from warband_gpu_supervisor import (
        DEFAULT_GAME,
        DEFAULT_PROTON,
        STEAM_ROOT,
        prove_dxvk_install,
    )

DEFAULT_PREFIX = STEAM_ROOT / "steamapps/compatdata/48700"
DEFAULT_CUA_SOCKET = Path.home() / ".cache/cua-driver/cua-driver-x11.sock"
DEFAULT_WORKSPACE = "name:warband-agent"
RULE_GLOBAL = "warband_agent_background_rule"
RULE_NAME = "warband-agent-background"
SOFTWARE_ENVIRONMENT = (
    "LIBGL_ALWAYS_SOFTWARE",
    "GALLIUM_DRIVER",
    "MESA_LOADER_DRIVER_OVERRIDE",
    "PROTON_USE_WINED3D",
)


class DesktopSafetyFailure(SafetyFailure):
    """The desktop launch could not preserve its declared safety boundary."""


def _run_json(command: Sequence[str]) -> object:
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DesktopSafetyFailure(f"{' '.join(command)} failed: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DesktopSafetyFailure(
            f"{' '.join(command)} returned malformed JSON"
        ) from error


def hypr_json(command: str) -> object:
    return _run_json(("hyprctl", "-j", command))


def workspace_is_inactive(
    workspace: str,
    monitors: Iterable[Mapping[str, object]],
    workspaces: Iterable[Mapping[str, object]],
) -> bool:
    name = workspace.removeprefix("name:")
    for monitor in monitors:
        active = monitor.get("activeWorkspace")
        if isinstance(active, Mapping) and active.get("name") == name:
            return False
    return all(item.get("name") != name for item in workspaces)


def focus_identity(active: Mapping[str, object]) -> dict[str, object]:
    workspace = active.get("workspace")
    return {
        "address": active.get("address", ""),
        "class": active.get("class", ""),
        "monitor": active.get("monitor"),
        "workspace": workspace.get("name") if isinstance(workspace, Mapping) else "",
    }


def build_rule_lua(workspace: str) -> str:
    if not re.fullmatch(r"(?:name:)?[A-Za-z0-9_.-]+", workspace):
        raise DesktopSafetyFailure(f"unsafe workspace selector: {workspace!r}")
    return " ".join(
        (
            f'if type({RULE_GLOBAL}) == "userdata" then',
            f"{RULE_GLOBAL}:set_enabled(false); end;",
            f"{RULE_GLOBAL} = hl.window_rule({{",
            f'name = "{RULE_NAME}",',
            'match = { initial_class = "^steam_app_48700$" },',
            f'workspace = "{workspace} silent",',
            "no_initial_focus = true,",
            "focus_on_activate = false,",
            'content = "game",',
            "});",
        )
    )


def install_rule(workspace: str) -> None:
    completed = subprocess.run(
        ("hyprctl", "eval", build_rule_lua(workspace)),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0 or completed.stdout.strip() != "ok":
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise DesktopSafetyFailure(f"Hyprland refused the launch rule: {detail}")
    enabled = subprocess.run(
        ("hyprctl", "repl", f"{RULE_GLOBAL}:is_enabled()"),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    if enabled.returncode != 0 or enabled.stdout.strip() != "true":
        raise DesktopSafetyFailure("Hyprland did not enable the launch rule")


def disable_rule() -> None:
    lua = (
        f'if type({RULE_GLOBAL}) == "userdata" then '
        f"{RULE_GLOBAL}:set_enabled(false); {RULE_GLOBAL} = nil; end"
    )
    subprocess.run(
        ("hyprctl", "eval", lua),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )


def build_proton_environment(
    base: Mapping[str, str],
    prefix: Path,
    game: Path,
    log_dir: Path,
    graphics_backend: str = "dxvk",
) -> dict[str, str]:
    environment = dict(base)
    for variable in SOFTWARE_ENVIRONMENT:
        environment.pop(variable, None)
    environment.pop("WAYLAND_DISPLAY", None)
    environment.update(
        {
            "XDG_SESSION_TYPE": "x11",
            "SteamAppId": "48700",
            "SteamGameId": "48700",
            "STEAM_COMPAT_APP_ID": "48700",
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(STEAM_ROOT),
            "STEAM_COMPAT_DATA_PATH": str(prefix),
            "STEAM_COMPAT_INSTALL_PATH": str(game.parent),
            "PROTON_DISABLE_NVAPI": "1",
            "PROTON_LOG": "1",
            "PROTON_LOG_DIR": str(log_dir),
            "MESA_VK_DEVICE_SELECT": f"{DEFAULT_GPU}!",
            "DRI_PRIME": "pci-0000_08_00_0",
            "__GLX_VENDOR_LIBRARY_NAME": "mesa",
            "WINE_FULLSCREEN_FSR": "0",
        }
    )
    if graphics_backend == "dxvk":
        environment.update(
            {
                "DXVK_FILTER_DEVICE_NAME": DEFAULT_RENDERER,
                "DXVK_LOG_LEVEL": "info",
                "DXVK_LOG_PATH": str(log_dir),
                # runinprefix does not install Proton's usual DXVK overrides.
                # Force Warband's 32-bit D3D9 import to the verified native DLL.
                "WINEDLLOVERRIDES": "d3d9=n",
            }
        )
    else:
        environment.update(
            {
                "PROTON_USE_WINED3D": "1",
                "WINE_DISABLE_FULLSCREEN_HACK": "1",
                "WINEDLLOVERRIDES": "d3d9=b",
            }
        )
    return environment


def build_proton_command(
    proton: Path, game: Path, game_arguments: Sequence[str] = ()
) -> list[str]:
    # runinprefix is intentional: Warband's launcher maps on desktop XWayland
    # through this Proton verb, while waitforexitandrun stalls before a window.
    return [str(proton), "runinprefix", game.name, *game_arguments]


def build_systemd_command(
    args: argparse.Namespace, script: Path, unit_name: str
) -> list[str]:
    inner = [
        sys.executable,
        str(script),
        "run",
        "--bounded",
        "--workspace",
        args.workspace,
        "--max-runtime",
        str(args.max_runtime),
        "--hardware-deadline",
        str(args.hardware_deadline),
        "--graphics-backend",
        args.graphics_backend,
        "--log-dir",
        str(args.log_dir),
        "--prefix",
        str(args.prefix),
        "--proton",
        str(args.proton),
        "--game",
        str(args.game),
        "--cua-socket",
        str(args.cua_socket),
    ]
    for argument in args.game_arguments:
        inner.append(f"--game-arg={argument}")
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
        f"WorkingDirectory={Path.cwd()}",
        "--",
        *inner,
    ]


def current_control_group_pids(
    proc_root: Path = Path("/proc"), cgroup_root: Path = Path("/sys/fs/cgroup")
) -> tuple[int, ...]:
    try:
        line = next(
            item
            for item in (proc_root / "self/cgroup").read_text().splitlines()
            if item.startswith("0::")
        )
        path = line.removeprefix("0::").lstrip("/")
        values = (cgroup_root / path / "cgroup.procs").read_text().splitlines()
        return tuple(sorted(int(value) for value in values if value.isdigit()))
    except (FileNotFoundError, OSError, StopIteration, ValueError):
        return (os.getpid(),)


def process_driver_evidence(
    pids: Iterable[int],
    process_name: str = "mb_warband.exe",
    driver_name: str = "libvulkan_radeon.so",
    proc_root: Path = Path("/proc"),
) -> tuple[dict[str, object], ...]:
    evidence: list[dict[str, object]] = []
    for pid in pids:
        process = proc_root / str(pid)
        try:
            comm = (process / "comm").read_text().strip()
            maps = (process / "maps").read_text(errors="replace")
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        if comm.casefold() != process_name.casefold():
            continue
        matches = sorted(
            {
                line.rsplit(" ", 1)[-1]
                for line in maps.splitlines()
                if driver_name.casefold() in line.casefold()
            }
        )
        if matches:
            evidence.append({"pid": pid, "process": comm, "driver_mappings": matches})
    return tuple(evidence)


def _fdinfo_value(text: str, name: str) -> str | None:
    prefix = f"{name}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip().split()[0]
    return None


def amdgpu_engine_samples(
    pids: Iterable[int], proc_root: Path = Path("/proc")
) -> dict[tuple[int, str], dict[str, object]]:
    """Read kernel DRM accounting for AMD clients owned by candidate PIDs."""
    samples: dict[tuple[int, str], dict[str, object]] = {}
    for pid in pids:
        fdinfo_root = proc_root / str(pid) / "fdinfo"
        try:
            entries = tuple(fdinfo_root.iterdir())
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        for entry in entries:
            try:
                info = entry.read_text(errors="replace")
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                continue
            if _fdinfo_value(info, "drm-driver") != "amdgpu":
                continue
            client_id = _fdinfo_value(info, "drm-client-id")
            gfx = _fdinfo_value(info, "drm-engine-gfx")
            if client_id is None or gfx is None:
                continue
            try:
                gfx_ns = int(gfx)
            except ValueError:
                continue
            try:
                render_node = (proc_root / str(pid) / "fd" / entry.name).resolve()
            except (FileNotFoundError, OSError):
                render_node = Path("unknown")
            key = (pid, client_id)
            previous = samples.get(key)
            if previous is None or gfx_ns > int(previous["gfx_ns"]):
                samples[key] = {
                    "client_id": client_id,
                    "gfx_ns": gfx_ns,
                    "pid": pid,
                    "render_node": str(render_node),
                }
    return samples


def advancing_amdgpu_evidence(
    before: Mapping[tuple[int, str], Mapping[str, object]],
    after: Mapping[tuple[int, str], Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    evidence: list[dict[str, object]] = []
    for key, current in after.items():
        prior = before.get(key)
        if prior is None:
            continue
        before_ns = int(prior["gfx_ns"])
        after_ns = int(current["gfx_ns"])
        if after_ns <= before_ns:
            continue
        evidence.append(
            {
                **current,
                "driver": "amdgpu",
                "gfx_after_ns": after_ns,
                "gfx_before_ns": before_ns,
                "gfx_delta_ns": after_ns - before_ns,
            }
        )
    return tuple(evidence)


def desktop_violations(
    clients: Iterable[Mapping[str, object]],
    active: Mapping[str, object],
    monitors: Iterable[Mapping[str, object]],
    workspace: str,
) -> tuple[str, ...]:
    target = workspace.removeprefix("name:")
    violations: list[str] = []
    warband = [
        client
        for client in clients
        if str(client.get("class", "")).casefold() == "steam_app_48700"
    ]
    active_address = active.get("address")
    for client in warband:
        location = client.get("workspace")
        name = location.get("name") if isinstance(location, Mapping) else None
        if name != target:
            violations.append(f"Warband window mapped on workspace {name!r}")
        if client.get("address") == active_address:
            violations.append("Warband became the active window")
    for monitor in monitors:
        location = monitor.get("activeWorkspace")
        name = location.get("name") if isinstance(location, Mapping) else None
        if name == target:
            violations.append("agent workspace became visible")
    return tuple(dict.fromkeys(violations))


def event_socket_path(environment: Mapping[str, str]) -> Path:
    runtime = environment.get("XDG_RUNTIME_DIR")
    signature = environment.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not runtime or not signature:
        raise DesktopSafetyFailure("Hyprland runtime environment is incomplete")
    path = Path(runtime) / "hypr" / signature / ".socket2.sock"
    if not path.exists():
        raise DesktopSafetyFailure(f"Hyprland event socket does not exist: {path}")
    return path


def _metadata(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _assert_no_existing_warband() -> None:
    clients = hypr_json("clients")
    assert isinstance(clients, list)
    if any(
        str(client.get("class", "")).casefold() == "steam_app_48700"
        for client in clients
    ):
        raise DesktopSafetyFailure("a Warband desktop window already exists")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip().casefold() == "mb_warband.exe":
                raise DesktopSafetyFailure("a Warband process already exists")
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue


def run_bounded(args: argparse.Namespace) -> int:
    for path, label in (
        (args.proton, "Proton executable"),
        (args.game, "Warband executable"),
        (args.prefix / "pfx", "Proton prefix"),
        (args.cua_socket, "CUA X11 socket"),
    ):
        if not path.exists():
            raise DesktopSafetyFailure(f"{label} does not exist: {path}")
    _assert_no_existing_warband()
    probe = probe_hardware(DEFAULT_GPU)
    if DEFAULT_RENDERER.casefold() not in probe.renderer.casefold():
        raise DesktopSafetyFailure(f"hardware probe selected {probe.renderer!r}")
    dxvk = (
        prove_dxvk_install(args.proton, args.prefix)
        if args.graphics_backend == "dxvk"
        else {}
    )
    monitors = hypr_json("monitors")
    workspaces = hypr_json("workspaces")
    active = hypr_json("activewindow")
    assert isinstance(monitors, list) and isinstance(workspaces, list)
    assert isinstance(active, Mapping)
    if not workspace_is_inactive(args.workspace, monitors, workspaces):
        raise DesktopSafetyFailure(
            f"workspace {args.workspace!r} is visible or already occupied"
        )

    args.log_dir.mkdir(parents=True, exist_ok=False)
    session_path = args.log_dir / "session.json"
    event_path = args.log_dir / "hyprland-events.log"
    focus_before = focus_identity(active)
    started_at = datetime.now(UTC).isoformat()
    stopping = False

    def request_stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    events = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    events.connect(str(event_socket_path(os.environ)))
    events.setblocking(False)
    install_rule(args.workspace)
    process: subprocess.Popen[bytes] | None = None
    event_buffer = b""
    event_lines: list[str] = []
    hardware: tuple[dict[str, object], ...] = ()
    gpu_baselines: dict[tuple[int, str], dict[str, object]] = {}
    started = time.monotonic()
    last_report = started
    last_sample_time = started
    last_ticks = 0
    try:
        environment = build_proton_environment(
            os.environ,
            args.prefix,
            args.game,
            args.log_dir,
            args.graphics_backend,
        )
        process = subprocess.Popen(
            build_proton_command(args.proton, args.game, args.game_arguments),
            cwd=args.game.parent,
            env=environment,
        )
        _metadata(
            session_path,
            {
                "cua_socket": str(args.cua_socket),
                "dxvk_d3d9_sha256": dxvk.get("d3d9_sha256"),
                "focus_before": focus_before,
                "game_pid": process.pid,
                "graphics_backend": args.graphics_backend,
                "renderer_required": DEFAULT_RENDERER,
                "started_at": started_at,
                "state": "running",
                "workspace": args.workspace,
            },
        )
        print(str(session_path), flush=True)

        while process.poll() is None and not stopping:
            now = time.monotonic()
            try:
                chunk = events.recv(65536)
                if chunk:
                    event_buffer += chunk
                    pieces = event_buffer.split(b"\n")
                    event_buffer = pieces.pop()
                    event_lines.extend(
                        piece.decode(errors="replace") for piece in pieces if piece
                    )
            except BlockingIOError:
                pass

            pids = current_control_group_pids()
            software = software_renderer_evidence(pids)
            logs = "\n".join(
                path.read_text(errors="replace")
                for path in args.log_dir.glob("*.log")
                if path != event_path
            )
            if contains_software_renderer(logs):
                software = (*software, "runtime log contains software renderer")
            if software:
                raise DesktopSafetyFailure("; ".join(dict.fromkeys(software)))

            clients = hypr_json("clients")
            current_active = hypr_json("activewindow")
            current_monitors = hypr_json("monitors")
            assert isinstance(clients, list) and isinstance(current_active, Mapping)
            assert isinstance(current_monitors, list)
            violations = desktop_violations(
                clients, current_active, current_monitors, args.workspace
            )
            if violations:
                raise DesktopSafetyFailure("; ".join(violations))
            if any(
                "steam_app_48700" in line.casefold()
                and line.startswith(("activewindow>>", "activewindowv2>>"))
                for line in event_lines
            ):
                raise DesktopSafetyFailure("Hyprland recorded Warband focus activation")

            if not hardware:
                owned_pids = set(pids)
                warband_pids = {
                    int(client["pid"])
                    for client in clients
                    if str(client.get("class", "")).casefold() == "steam_app_48700"
                    and isinstance(client.get("pid"), int)
                    and int(client["pid"]) in owned_pids
                }
                gpu_samples = amdgpu_engine_samples(warband_pids)
                hardware = advancing_amdgpu_evidence(gpu_baselines, gpu_samples)
                if hardware:
                    _metadata(
                        args.log_dir / "hardware-renderer-proof.json",
                        {
                            "driver": "amdgpu",
                            "evidence_kind": "kernel-drm-engine-advance",
                            "graphics_backend": args.graphics_backend,
                            "processes": hardware,
                            "renderer": probe.renderer,
                        },
                    )
                elif now - started >= args.hardware_deadline:
                    raise DesktopSafetyFailure(
                        "Warband did not submit work to the AMD DRM gfx engine within "
                        f"{args.hardware_deadline:.0f}s"
                    )
                for key, sample in gpu_samples.items():
                    gpu_baselines.setdefault(key, sample)

            if now - started >= args.max_runtime:
                return 124
            if now - last_report >= 5:
                sample = sample_processes(pids)
                elapsed = max(now - last_sample_time, 0.001)
                cpu = (
                    max(sample.cpu_ticks - last_ticks, 0)
                    / os.sysconf("SC_CLK_TCK")
                    / elapsed
                    * 100
                )
                print(
                    f"desktop-guard: pids={len(sample.pids)} "
                    f"rss={sample.rss_kib / 1024:.1f}MiB cpu={cpu:.1f}% "
                    f"gpu_proven={bool(hardware)}",
                    file=sys.stderr,
                    flush=True,
                )
                last_report = now
                last_sample_time = now
                last_ticks = sample.cpu_ticks
            time.sleep(0.25)
        if not hardware and not stopping:
            raise DesktopSafetyFailure(
                "Warband exited before proving AMD hardware rendering"
            )
        return (process.returncode or 0) if not stopping else 130
    finally:
        _terminate(process)
        disable_rule()
        if event_buffer:
            event_lines.append(event_buffer.decode(errors="replace"))
        event_path.write_text("\n".join(event_lines) + ("\n" if event_lines else ""))
        focus_after_raw = hypr_json("activewindow")
        assert isinstance(focus_after_raw, Mapping)
        _metadata(
            session_path,
            {
                "cua_socket": str(args.cua_socket),
                "ended_at": datetime.now(UTC).isoformat(),
                "focus_after": focus_identity(focus_after_raw),
                "focus_before": focus_before,
                "hardware_renderer_proven": bool(hardware),
                "graphics_backend": args.graphics_backend,
                "renderer": probe.renderer,
                "started_at": started_at,
                "state": "stopped",
                "workspace": args.workspace,
            },
        )
        events.close()


def run_systemd(args: argparse.Namespace, script: Path) -> int:
    unit = f"warband-desktop-{os.getpid()}.service"
    command = build_systemd_command(args, script, unit)
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        subprocess.run(
            ("systemctl", "--user", "stop", unit),
            check=False,
            timeout=10,
        )
        return 130
    finally:
        # A second teardown path clears a runtime rule even if the bounded
        # service is killed before its Python finally block can run.
        disable_rule()


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    run.add_argument("--max-runtime", type=float, default=300)
    run.add_argument("--hardware-deadline", type=float, default=120)
    run.add_argument("--graphics-backend", choices=("dxvk", "wined3d"), default="dxvk")
    run.add_argument("--cpu-quota", type=int, default=200)
    run.add_argument("--memory-high", default="1500M")
    run.add_argument("--memory-max", default="2G")
    run.add_argument("--tasks-max", type=int, default=192)
    run.add_argument("--log-dir", type=Path, required=True)
    run.add_argument("--prefix", type=Path, default=DEFAULT_PREFIX)
    run.add_argument("--proton", type=Path, default=DEFAULT_PROTON)
    run.add_argument("--game", type=Path, default=DEFAULT_GAME)
    run.add_argument("--cua-socket", type=Path, default=DEFAULT_CUA_SOCKET)
    run.add_argument("--game-arg", action="append", default=[], dest="game_arguments")
    run.add_argument("--bounded", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if not args.bounded:
            if shutil.which("systemd-run") is None:
                raise DesktopSafetyFailure("systemd-run is required")
            return run_systemd(args, Path(__file__).resolve())
        return run_bounded(args)
    except (DesktopSafetyFailure, SafetyFailure) as error:
        print(f"warband-desktop-runner: REFUSED: {error}", file=sys.stderr)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
