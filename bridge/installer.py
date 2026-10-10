"""Plan and apply a private, Native-preserving Warband Agentic Kit install."""

from __future__ import annotations

import argparse
import json
import secrets
import shlex
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from bridge.agent_host import load_agent_host_plan
from bridge.application_extensions import built_in_extension_registry
from module_system.build_mcp_module import build
from warband_agentic.extensions import load_named_extension_entry_points
from warband_agentic.voice import KokoroAdapter
from warband_agentic.voice_server import build_voice_service, load_voice_config

PLAN_SCHEMA = "warband.agentic/install-plan/v1"
RECEIPT_SCHEMA = "warband.agentic/install-receipt/v1"
MANIFEST_SCHEMA = "warband.agentic/install-manifest/v1"


def _port(value: int, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 65_535:
        raise ValueError(f"{label} must be from 1 through 65535")
    return value


def _new_target(path: Path, label: str) -> Path:
    target = path.expanduser().resolve()
    if target.exists():
        raise ValueError(f"{label} must not already exist: {target}")
    if not target.parent.is_dir():
        raise ValueError(f"{label} parent does not exist: {target.parent}")
    return target


def build_install_plan(args: argparse.Namespace) -> dict[str, object]:
    native = args.native.expanduser().resolve()
    if native.name != "Native" or not (native / "module.ini").is_file():
        raise ValueError("--native must be an installed Native module")
    module_output = _new_target(
        args.module_output or native.parent / "WarbandMCP", "module output"
    )
    install_root = _new_target(args.install_root, "install root")
    if native == module_output or native in module_output.parents:
        raise ValueError("module output must be outside Native")
    if native == install_root or native in install_root.parents:
        raise ValueError("install root must be outside Native")
    if (
        install_root == module_output
        or install_root in module_output.parents
        or module_output in install_root.parents
    ):
        raise ValueError("install root and module output must not overlap")

    ports = {
        "bridge": _port(args.bridge_port, "bridge port"),
        "control": _port(args.control_port, "control port"),
        "voice": _port(args.voice_port, "voice port"),
        "starter_session": _port(args.session_port, "starter session port"),
    }
    if len(set(ports.values())) != len(ports):
        raise ValueError("installer service ports must be distinct")
    KokoroAdapter(args.kokoro_endpoint)
    extensions = built_in_extension_registry()
    load_named_extension_entry_points(extensions, args.extension)
    return {
        "schema": PLAN_SCHEMA,
        "native": str(native),
        "module_output": str(module_output),
        "install_root": str(install_root),
        "configuration": {
            "ports": ports,
            "voice_playback": args.voice_playback,
            "kokoro_endpoint": args.kokoro_endpoint,
            "starter_application": "native-menu",
            "extensions": list(args.extension),
            "module_extensions": list(extensions.required_module_extensions()),
        },
        "credentials": {"distinct_private_files": 4, "mode": "0600"},
        "requirements": {
            "loopback_port_80_route": args.bridge_port != 80,
            "hardware_safe_game_acceptance": True,
            "manual_mcp_client_registration": True,
        },
        "validation_scope": (
            "Source identity and target safety are checked during planning; "
            "all Native patch seams are checked during apply before commit."
        ),
        "effects": [],
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply"):
        command = subparsers.add_parser(name)
        command.add_argument("--native", type=Path, required=True)
        command.add_argument("--install-root", type=Path, required=True)
        command.add_argument("--module-output", type=Path)
        command.add_argument("--bridge-port", type=int, default=8765)
        command.add_argument("--control-port", type=int, default=8879)
        command.add_argument("--voice-port", type=int, default=8870)
        command.add_argument("--session-port", type=int, default=8890)
        command.add_argument(
            "--voice-playback", choices=("disabled", "pipewire"), default="disabled"
        )
        command.add_argument(
            "--kokoro-endpoint",
            default="http://127.0.0.1:8880/v1/audio/speech",
        )
        command.add_argument("--extension", action="append", default=[])
    return parser


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_credential(path: Path) -> None:
    path.write_text(secrets.token_hex(32))
    path.chmod(0o600)


def _claim_and_move(staged: Path, destination: Path, mode: int) -> None:
    destination.mkdir(mode=mode)
    try:
        for child in staged.iterdir():
            target = destination / child.name
            if target.exists():
                raise FileExistsError(
                    f"install target appeared during commit: {target}"
                )
            child.rename(target)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _launch_commands(plan: dict[str, object], python: str) -> dict[str, list[str]]:
    install_root = Path(str(plan["install_root"]))
    ports = plan["configuration"]["ports"]
    return {
        "voice": [
            python,
            "-m",
            "warband_agentic.voice_server",
            "--config",
            str(install_root / "config/voice.json"),
            "--token-file",
            str(install_root / "runtime/voice.credential"),
            "--port",
            str(ports["voice"]),
        ],
        "host_check": [
            python,
            "-m",
            "bridge.agent_host",
            "--config",
            str(install_root / "config/agent-host.json"),
            "--check",
        ],
        "host": [
            python,
            "-m",
            "bridge.agent_host",
            "--config",
            str(install_root / "config/agent-host.json"),
        ],
    }


def _install_readme(plan: dict[str, object], python: str) -> str:
    module_output = Path(str(plan["module_output"]))
    ports = plan["configuration"]["ports"]
    route = (
        f"Route 127.0.0.1:80 to 127.0.0.1:{ports['bridge']} before starting "
        "Warband. Vanilla Warband cannot put a custom port in its HTTP URL."
        if plan["requirements"]["loopback_port_80_route"]
        else "The host binds the game bridge directly to loopback port 80."
    )
    commands = _launch_commands(plan, python)
    return f"""# Warband Agentic Kit local install

This directory contains private credentials and runtime state. Keep it private.
The generated game module is `{module_output}` and the original Native module was
not modified.

## Required network route

{route}

## Start voice and host

```bash
{shlex.join(commands["voice"])}
{shlex.join(commands["host_check"])}
{shlex.join(commands["host"])}
```

The starter host exposes one restricted `native-menu` session. Add NPC or faction
sessions only after choosing real live agent/party IDs and reviewed order options.
Copy `config/agent-mcp-server.json` into an agent's MCP client for the restricted
starter session. `config/mcp-server.json` is the separate full operator surface;
do not give its bridge credential to an untrusted agent. Registration remains
manual.
Do not publish this directory or the generated module: the game credential is
embedded in the module's strings file.
"""


def apply_install(
    plan: dict[str, object], args: argparse.Namespace
) -> dict[str, object]:
    native = Path(str(plan["native"]))
    module_output = Path(str(plan["module_output"]))
    install_root = Path(str(plan["install_root"]))
    configuration = plan["configuration"]
    ports = configuration["ports"]
    registry = built_in_extension_registry()
    load_named_extension_entry_points(registry, args.extension)

    install_container = Path(
        tempfile.mkdtemp(prefix=".warband-agentic-install-", dir=install_root.parent)
    )
    module_container = Path(
        tempfile.mkdtemp(prefix=".warband-agentic-module-", dir=module_output.parent)
    )
    staged_install = install_container / "root"
    staged_module = module_container / "module"
    committed_module = False
    committed_install = False
    try:
        config = staged_install / "config"
        runtime = staged_install / "runtime"
        config.mkdir(parents=True, mode=0o700)
        runtime.mkdir(mode=0o700)
        credentials = {
            "bridge": runtime / "bridge.credential",
            "control": runtime / "control.credential",
            "voice": runtime / "voice.credential",
            "player-menu": runtime / "player-menu.credential",
        }
        for path in credentials.values():
            _write_credential(path)
        credential_values = [path.read_text() for path in credentials.values()]
        if len(set(credential_values)) != len(credential_values):
            raise RuntimeError("credential generator returned duplicate values")

        build(
            native,
            staged_module,
            "http://127.0.0.1",
            credential_values[0],
            compiled_operations=registry.compiled_operations(),
            module_extensions=registry.required_module_extensions(),
        )
        host_config = {
            "schema": "warband.agentic/host-config/v2",
            "bridge": {
                "database": "../runtime/bridge.sqlite3",
                "catalog": str(module_output / "mcp-catalog.json"),
                "build_manifest": str(module_output / "mcp-build.json"),
                "token_file": "../runtime/bridge.credential",
                "port": ports["bridge"],
            },
            "control": {
                "token_file": "../runtime/control.credential",
                "port": ports["control"],
            },
            "voice": {
                "endpoint": (f"http://127.0.0.1:{ports['voice']}/v1/voice/speech"),
                "token_file": "../runtime/voice.credential",
                "timeout_ms": 30_000,
            },
            "events_database": "../runtime/agentic-events.sqlite3",
            "sessions": [
                {
                    "kind": "native-menu",
                    "session_id": "player-menu",
                    "token_file": "../runtime/player-menu.credential",
                    "port": ports["starter_session"],
                }
            ],
        }
        voice_config = {
            "kokoro": {
                "endpoint": configuration["kokoro_endpoint"],
                "model": "tts-1",
            },
            "profiles": [
                {
                    "profile_id": "npc.default",
                    "display_name": "Default NPC",
                    "voice_id": "bm_george",
                    "locale": "en-GB",
                    "tags": ["npc", "default"],
                }
            ],
            "playback": configuration["voice_playback"],
            "artifact_limit": 32,
        }
        mcp_server = {
            "command": sys.executable,
            "args": ["-m", "src.warband_mcp"],
            "env": {
                "WARBAND_TOKEN_FILE": str(credentials["bridge"]).replace(
                    str(staged_install), str(install_root), 1
                ),
                "WARBAND_BRIDGE_URL": (f"http://127.0.0.1:{ports['bridge']}"),
            },
        }
        agent_mcp_server = {
            "command": sys.executable,
            "args": ["-m", "src.warband_agent_mcp"],
            "env": {
                "WARBAND_AGENT_TOKEN_FILE": str(credentials["player-menu"]).replace(
                    str(staged_install), str(install_root), 1
                ),
                "WARBAND_AGENT_URL": (f"http://127.0.0.1:{ports['starter_session']}"),
            },
        }
        _write_json(config / "agent-host.json", host_config)
        _write_json(config / "voice.json", voice_config)
        _write_json(config / "mcp-server.json", mcp_server)
        _write_json(config / "agent-mcp-server.json", agent_mcp_server)
        build_voice_service(load_voice_config(config / "voice.json"))
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "state": "installed",
            "native_source": str(native),
            "module_output": str(module_output),
            "install_root": str(install_root),
            "module_protocol": 2,
            "module_integration_revision": 16,
            "extensions": registry.catalog()["extensions"],
            "credential_files": [
                str(install_root / "runtime" / path.name)
                for path in credentials.values()
            ],
            "configuration_files": [
                str(install_root / "config" / name)
                for name in (
                    "agent-host.json",
                    "voice.json",
                    "mcp-server.json",
                    "agent-mcp-server.json",
                )
            ],
            "launch_commands": _launch_commands(plan, sys.executable),
            "requirements": plan["requirements"],
        }
        _write_json(staged_install / "install-manifest.json", manifest)
        (staged_install / "INSTALL.md").write_text(
            _install_readme(plan, sys.executable)
        )
        for path in config.iterdir():
            path.chmod(0o600)
        (staged_install / "install-manifest.json").chmod(0o600)
        (staged_install / "INSTALL.md").chmod(0o600)

        _claim_and_move(staged_module, module_output, 0o700)
        committed_module = True
        _claim_and_move(staged_install, install_root, 0o700)
        committed_install = True
        load_agent_host_plan(install_root / "config" / "agent-host.json", registry)
        return {
            "schema": RECEIPT_SCHEMA,
            "state": "installed",
            "module_output": str(module_output),
            "install_root": str(install_root),
            "manifest": str(install_root / "install-manifest.json"),
            "mcp_server": str(install_root / "config" / "mcp-server.json"),
            "agent_mcp_server": str(install_root / "config" / "agent-mcp-server.json"),
            "requirements": plan["requirements"],
        }
    except BaseException:
        if committed_install:
            shutil.rmtree(install_root, ignore_errors=True)
        if committed_module:
            shutil.rmtree(module_output, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(install_container, ignore_errors=True)
        shutil.rmtree(module_container, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        plan = build_install_plan(args)
        result = plan if args.command == "plan" else apply_install(plan, args)
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except (OSError, ValueError) as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
