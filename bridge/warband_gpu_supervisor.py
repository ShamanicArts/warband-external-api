#!/usr/bin/env python3
"""Own CUA and Proton inside gpu_safe_runner's private gamescope display."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

DEFAULT_CUA = Path("/home/shamanic/.local/bin/cua-driver-main")
DEFAULT_PROTON = Path(
    "/home/shamanic/.local/share/Steam/steamapps/common/Proton 9.0 (Beta)/proton"
)
DEFAULT_GAME = Path(
    "/home/shamanic/.local/share/Steam/steamapps/common/"
    "MountBlade Warband/mb_warband.exe"
)
DEFAULT_PREFIX = Path("/tmp/shuvcode/warband-cua/compatdata")
STEAM_ROOT = Path("/home/shamanic/.local/share/Steam")


class SupervisorFailure(RuntimeError):
    """The private display or one of its owned services is not usable."""


def require_private_gamescope_display(environment: Mapping[str, str]) -> str:
    display = environment.get("DISPLAY", "")
    log_dir = environment.get("WARBAND_GPU_LOG_DIR", "")
    if not display or display == ":0":
        raise SupervisorFailure("refusing the user's desktop X display")
    if environment.get("WARBAND_GPU_PRIVATE_DISPLAY") != "1":
        raise SupervisorFailure("missing gpu_safe_runner private-display marker")
    if not log_dir:
        raise SupervisorFailure(
            "gpu_safe_runner did not provide a private log directory"
        )
    return display


def build_cua_command(cua: Path, socket: Path, pid_file: Path) -> list[str]:
    return [
        str(cua),
        "serve",
        "--socket",
        str(socket),
        "--pid-file",
        str(pid_file),
        "--no-overlay",
    ]


def build_proton_command(
    proton: Path,
    game: Path,
    graphics_backend: str,
    game_arguments: Sequence[str] = (),
) -> list[str]:
    if graphics_backend == "dxvk":
        return [str(proton), "waitforexitandrun", str(game), *game_arguments]
    return [str(proton), "runinprefix", game.name, *game_arguments]


def build_proton_environment(
    base: Mapping[str, str],
    prefix: Path,
    game: Path,
    log_dir: Path,
    graphics_backend: str,
) -> dict[str, str]:
    environment = dict(base)
    environment.pop("WAYLAND_DISPLAY", None)
    environment.pop("PROTON_USE_WINED3D", None)
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
            "WINE_FULLSCREEN_FSR": "0",
        }
    )
    if graphics_backend == "dxvk":
        environment["DXVK_FILTER_DEVICE_NAME"] = "AMD Radeon RX 6600 XT"
    else:
        environment.pop("DXVK_FILTER_DEVICE_NAME", None)
        environment["PROTON_USE_WINED3D"] = "1"
        environment["WINE_DISABLE_FULLSCREEN_HACK"] = "1"
    return environment


def build_cua_environment(base: Mapping[str, str]) -> dict[str, str]:
    environment = dict(base)
    environment.pop("WAYLAND_DISPLAY", None)
    environment.pop("CUA_DRIVER_RS_ENABLE_WAYLAND", None)
    environment["XDG_SESSION_TYPE"] = "x11"
    return environment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prove_dxvk_install(proton: Path, prefix: Path) -> dict[str, object]:
    source = proton.parent / "files/lib/wine/dxvk/d3d9.dll"
    installed = prefix / "pfx/drive_c/windows/syswow64/d3d9.dll"
    for path, label in ((source, "Proton DXVK"), (installed, "prefix DXVK")):
        if not path.is_file():
            raise SupervisorFailure(f"{label} d3d9.dll does not exist: {path}")
    source_digest = _sha256(source)
    installed_digest = _sha256(installed)
    if source_digest != installed_digest:
        raise SupervisorFailure(
            "isolated prefix d3d9.dll does not match Proton's 32-bit DXVK DLL"
        )
    return {
        "d3d9_sha256": source_digest,
        "dxvk_d3d9_match": True,
        "prefix_d3d9": str(installed),
        "proton_d3d9": str(source),
    }


def _write_metadata(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _terminate(process: subprocess.Popen[bytes] | None, timeout: float = 5.0) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def supervise(args: argparse.Namespace) -> int:
    display = require_private_gamescope_display(os.environ)
    for path, label in (
        (args.cua, "CUA executable"),
        (args.proton, "Proton executable"),
        (args.game, "Warband executable"),
        (args.prefix / "pfx", "isolated Proton prefix"),
    ):
        if not path.exists():
            raise SupervisorFailure(f"{label} does not exist: {path}")

    log_dir = Path(os.environ["WARBAND_GPU_LOG_DIR"]).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    socket = log_dir / "cua-driver.sock"
    pid_file = log_dir / "cua-driver.pid"
    metadata_path = log_dir / "session.json"
    graphics_proof: dict[str, object] = {"graphics_backend": args.graphics_backend}
    if args.graphics_backend == "dxvk":
        graphics_proof.update(prove_dxvk_install(args.proton, args.prefix))
        _write_metadata(log_dir / "dxvk-proof.json", graphics_proof)
    else:
        _write_metadata(log_dir / "graphics-proof.json", graphics_proof)
    if socket.exists():
        socket.unlink()

    stopping = False

    def request_stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    cua_process: subprocess.Popen[bytes] | None = None
    game_process: subprocess.Popen[bytes] | None = None
    started = datetime.now(UTC).isoformat()
    cua_log_path = log_dir / "cua-driver.log"
    try:
        with cua_log_path.open("wb") as cua_log:
            cua_process = subprocess.Popen(
                build_cua_command(args.cua, socket, pid_file),
                env=build_cua_environment(os.environ),
                stdout=cua_log,
                stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + 10.0
            while not socket.exists():
                if cua_process.poll() is not None:
                    raise SupervisorFailure(
                        "CUA exited before creating its socket: "
                        f"{cua_process.returncode}"
                    )
                if time.monotonic() >= deadline:
                    raise SupervisorFailure("CUA did not create its socket within 10s")
                time.sleep(0.1)

            game_process = subprocess.Popen(
                build_proton_command(
                    args.proton,
                    args.game,
                    args.graphics_backend,
                    args.game_arguments,
                ),
                cwd=args.game.parent,
                env=build_proton_environment(
                    os.environ,
                    args.prefix,
                    args.game,
                    log_dir,
                    args.graphics_backend,
                ),
            )
            _write_metadata(
                metadata_path,
                {
                    "cua_pid": cua_process.pid,
                    "cua_socket": str(socket),
                    "display": display,
                    "d3d9_sha256": graphics_proof.get("d3d9_sha256"),
                    "game_pid": game_process.pid,
                    "game_arguments": args.game_arguments,
                    "graphics_backend": args.graphics_backend,
                    "renderer_required": "AMD Radeon RX 6600 XT",
                    "started_at": started,
                    "state": "running",
                },
            )
            print(str(metadata_path), flush=True)

            while game_process.poll() is None and not stopping:
                if cua_process.poll() is not None:
                    raise SupervisorFailure(
                        f"CUA exited during the game run: {cua_process.returncode}"
                    )
                time.sleep(0.25)
            return game_process.returncode or 0 if not stopping else 130
    finally:
        _terminate(game_process)
        _terminate(cua_process)
        _write_metadata(
            metadata_path,
            {
                "cua_socket": str(socket),
                "display": display,
                "d3d9_sha256": graphics_proof.get("d3d9_sha256"),
                "ended_at": datetime.now(UTC).isoformat(),
                "graphics_backend": args.graphics_backend,
                "renderer_required": "AMD Radeon RX 6600 XT",
                "started_at": started,
                "state": "stopped",
            },
        )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cua", type=Path, default=DEFAULT_CUA)
    parser.add_argument("--proton", type=Path, default=DEFAULT_PROTON)
    parser.add_argument("--game", type=Path, default=DEFAULT_GAME)
    parser.add_argument("--prefix", type=Path, default=DEFAULT_PREFIX)
    parser.add_argument(
        "--graphics-backend", choices=("dxvk", "wined3d"), default="dxvk"
    )
    parser.add_argument(
        "--game-arg",
        action="append",
        default=[],
        dest="game_arguments",
        help="pass one argument through to mb_warband.exe (repeatable)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        return supervise(args)
    except SupervisorFailure as error:
        print(f"warband-gpu-supervisor: REFUSED: {error}", file=sys.stderr)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
