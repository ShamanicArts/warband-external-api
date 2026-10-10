"""Runnable configured host voice service."""

import argparse
import json
from pathlib import Path

from warband_agentic.voice import (
    KokoroAdapter,
    PipeWirePlayer,
    VoiceProfile,
    VoiceService,
)
from warband_agentic.voice_http import make_voice_server


def load_voice_config(path):
    try:
        config = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read voice configuration") from exc
    allowed = {"kokoro", "profiles", "playback", "artifact_limit"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("Unexpected voice configuration fields")
    if not isinstance(config.get("kokoro"), dict):
        raise ValueError("Voice configuration requires kokoro settings")
    if not isinstance(config.get("profiles"), list) or not config["profiles"]:
        raise ValueError("Voice configuration requires at least one profile")
    if config.get("playback", "disabled") not in ("disabled", "pipewire"):
        raise ValueError("playback must be disabled or pipewire")
    return config


def build_voice_service(config):
    kokoro = config["kokoro"]
    if set(kokoro) - {"endpoint", "model"}:
        raise ValueError("Unexpected Kokoro configuration fields")
    adapter = KokoroAdapter(
        kokoro.get("endpoint", "http://127.0.0.1:8880/v1/audio/speech"),
        kokoro.get("model", "tts-1"),
    )
    profiles = []
    allowed_profile = {
        "profile_id",
        "display_name",
        "voice_id",
        "locale",
        "tags",
    }
    for data in config["profiles"]:
        if not isinstance(data, dict) or set(data) - allowed_profile:
            raise ValueError("Unexpected voice profile fields")
        try:
            profiles.append(
                VoiceProfile(
                    data["profile_id"],
                    data["display_name"],
                    "kokoro",
                    data["voice_id"],
                    data.get("locale"),
                    tuple(data.get("tags", ())),
                )
            )
        except KeyError as exc:
            raise ValueError("Voice profile is missing a required field") from exc
    player = PipeWirePlayer() if config.get("playback") == "pipewire" else None
    return VoiceService(
        {"kokoro": adapter},
        profiles,
        player,
        artifact_limit=config.get("artifact_limit", 32),
    )


def load_voice_token(path):
    try:
        token = Path(path).read_text().strip()
    except OSError as exc:
        raise ValueError("Cannot read voice API token file") from exc
    if len(token) < 32 or not token.isprintable():
        raise ValueError(
            "Voice API token must contain at least 32 printable characters"
        )
    return token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8870)
    args = parser.parse_args()
    service = build_voice_service(load_voice_config(args.config))
    server = make_voice_server(
        service, load_voice_token(args.token_file), port=args.port
    )
    print(f"Warband voice service listening on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
