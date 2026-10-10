"""Provider-neutral host voice service with optional Kokoro and PipeWire adapters."""

import json
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from warband_agentic.contracts import CONTRACT_VERSION, to_wire

MAX_AUDIO_BYTES = 32 * 1024 * 1024


def _nonempty(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _timestamp(name, value):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


class VoiceDelivery(StrEnum):
    SYNTHESIZE_ONLY = "synthesize-only"
    PLAY_HOST = "play-host"


class VoiceState(StrEnum):
    QUEUED = "queued"
    SYNTHESIZING = "synthesizing"
    READY = "ready"
    PLAYING = "playing"
    PLAYED = "played"
    SYNTHESIS_FAILED = "synthesis-failed"
    PLAYBACK_FAILED = "playback-failed"


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    profile_id: str
    display_name: str
    adapter_id: str
    provider_voice_id: str
    locale: str | None = None
    tags: tuple[str, ...] = ()
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        for name in (
            "profile_id",
            "display_name",
            "adapter_id",
            "provider_voice_id",
        ):
            _nonempty(name, getattr(self, name))
        if self.locale is not None:
            _nonempty("locale", self.locale)
        tags = tuple(self.tags)
        if any(not isinstance(tag, str) or not tag for tag in tags):
            raise ValueError("tags must contain non-empty strings")
        object.__setattr__(self, "tags", tags)
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")

    def public_manifest(self):
        return {
            "schema": self.schema,
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "locale": self.locale,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    request_id: str
    text: str
    profile_id: str
    delivery: VoiceDelivery
    speed: float = 1.0
    output_format: str = "wav"
    correlation_id: str | None = None
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        for name in ("request_id", "profile_id", "output_format"):
            _nonempty(name, getattr(self, name))
        if not isinstance(self.text, str) or not 1 <= len(self.text) <= 4000:
            raise ValueError("text must contain 1-4000 characters")
        if any(character in self.text for character in "\x00\r"):
            raise ValueError("text cannot contain NUL or carriage return")
        if not isinstance(self.delivery, VoiceDelivery):
            raise TypeError("delivery must be VoiceDelivery")
        if type(self.speed) not in (int, float) or not 0.25 <= self.speed <= 4.0:
            raise ValueError("speed must be from 0.25 through 4.0")
        if self.correlation_id is not None:
            _nonempty("correlation_id", self.correlation_id)
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


@dataclass(frozen=True, slots=True)
class AudioArtifact:
    audio_id: str
    request_id: str
    mime_type: str
    data: bytes
    created_at_ms: int

    def __post_init__(self):
        for name in ("audio_id", "request_id", "mime_type"):
            _nonempty(name, getattr(self, name))
        if (
            not isinstance(self.data, bytes)
            or not 0 < len(self.data) <= MAX_AUDIO_BYTES
        ):
            raise ValueError("audio data must contain 1-32 MiB")
        _timestamp("created_at_ms", self.created_at_ms)


@dataclass(frozen=True, slots=True)
class VoiceEvent:
    sequence: int
    request_id: str
    state: VoiceState
    occurred_at_ms: int
    detail: str | None = None

    def __post_init__(self):
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("sequence must be a positive integer")
        _nonempty("request_id", self.request_id)
        if not isinstance(self.state, VoiceState):
            raise TypeError("state must be VoiceState")
        _timestamp("occurred_at_ms", self.occurred_at_ms)
        if self.detail is not None:
            _nonempty("detail", self.detail)


@dataclass(frozen=True, slots=True)
class VoiceOutcome:
    request_id: str
    state: VoiceState
    profile_id: str
    delivery: VoiceDelivery
    audio_id: str | None
    mime_type: str | None
    error: str | None
    correlation_id: str | None
    started_at_ms: int
    completed_at_ms: int
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        _nonempty("request_id", self.request_id)
        _nonempty("profile_id", self.profile_id)
        if not isinstance(self.state, VoiceState):
            raise TypeError("state must be VoiceState")
        if not isinstance(self.delivery, VoiceDelivery):
            raise TypeError("delivery must be VoiceDelivery")
        if self.audio_id is not None:
            _nonempty("audio_id", self.audio_id)
        if self.mime_type is not None:
            _nonempty("mime_type", self.mime_type)
        if self.error is not None:
            _nonempty("error", self.error)
        _timestamp("started_at_ms", self.started_at_ms)
        _timestamp("completed_at_ms", self.completed_at_ms)
        if self.completed_at_ms < self.started_at_ms:
            raise ValueError("voice outcome completed before it started")
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")


class VoiceAdapter(Protocol):
    def synthesize(
        self, request: SpeechRequest, profile: VoiceProfile, created_at_ms: int
    ) -> AudioArtifact: ...


class AudioPlayer(Protocol):
    def play(self, artifact: AudioArtifact) -> None: ...


class VoiceService:
    """Coordinate synthesis/playback without making audio part of game truth."""

    def __init__(
        self,
        adapters,
        profiles,
        player=None,
        clock_ms=None,
        artifact_limit=32,
    ):
        if type(artifact_limit) is not int or not 1 <= artifact_limit <= 1024:
            raise ValueError("artifact_limit must be from 1 through 1024")
        self._adapters = dict(adapters)
        self._profiles = {}
        for profile in profiles:
            if not isinstance(profile, VoiceProfile):
                raise TypeError("profiles must contain VoiceProfile values")
            if profile.profile_id in self._profiles:
                raise ValueError(f"Duplicate voice profile: {profile.profile_id}")
            self._profiles[profile.profile_id] = profile
        self._player = player
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._artifact_limit = artifact_limit
        self._artifacts = {}
        self._requests = {}
        self._outcomes = {}
        self._events = []
        self._lock = threading.RLock()

    def profiles(self):
        with self._lock:
            return tuple(
                self._profiles[key].public_manifest()
                for key in sorted(self._profiles)
            )

    def speak(self, request):
        if not isinstance(request, SpeechRequest):
            raise TypeError("request must be a SpeechRequest")
        with self._lock:
            return self._speak_locked(request)

    def _speak_locked(self, request):
        if request.request_id in self._outcomes:
            if request != self._requests[request.request_id]:
                raise ValueError("Voice request ID was reused with different input")
            return self._outcomes[request.request_id]
        self._requests[request.request_id] = request
        started = self._now()
        self._emit(request.request_id, VoiceState.QUEUED, started)
        profile = self._profiles.get(request.profile_id)
        adapter = self._adapters.get(profile.adapter_id) if profile else None
        if profile is None or adapter is None:
            return self._failure(
                request,
                VoiceState.SYNTHESIS_FAILED,
                started,
                "Unknown voice profile or unavailable adapter",
            )
        try:
            self._emit(request.request_id, VoiceState.SYNTHESIZING, self._now())
            artifact = adapter.synthesize(request, profile, self._now())
            if not isinstance(artifact, AudioArtifact):
                raise TypeError("Voice adapter returned no AudioArtifact")
            if artifact.request_id != request.request_id:
                raise ValueError(
                    "Voice adapter returned an artifact for another request"
                )
            self._store_artifact(artifact)
            self._emit(request.request_id, VoiceState.READY, self._now())
        except Exception as exc:
            return self._failure(
                request,
                VoiceState.SYNTHESIS_FAILED,
                started,
                f"{type(exc).__name__}: {exc}",
            )

        if request.delivery is VoiceDelivery.PLAY_HOST:
            try:
                if self._player is None:
                    raise RuntimeError("No host audio player configured")
                self._emit(request.request_id, VoiceState.PLAYING, self._now())
                self._player.play(artifact)
                state, error = VoiceState.PLAYED, None
            except Exception as exc:
                state = VoiceState.PLAYBACK_FAILED
                error = f"{type(exc).__name__}: {exc}"
                self._emit(request.request_id, state, self._now(), error)
        else:
            state, error = VoiceState.READY, None
        completed = self._now()
        if state is VoiceState.PLAYED:
            self._emit(request.request_id, state, completed)
        outcome = VoiceOutcome(
            request.request_id,
            state,
            profile.profile_id,
            request.delivery,
            artifact.audio_id,
            artifact.mime_type,
            error,
            request.correlation_id,
            started,
            completed,
        )
        self._outcomes[request.request_id] = outcome
        return outcome

    def artifact(self, audio_id):
        _nonempty("audio_id", audio_id)
        with self._lock:
            try:
                return self._artifacts[audio_id]
            except KeyError as exc:
                raise ValueError("Unknown or evicted audio artifact") from exc

    def events(self, after_sequence=0):
        if type(after_sequence) is not int or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        with self._lock:
            return tuple(
                event
                for event in self._events
                if event.sequence > after_sequence
            )

    def outcome(self, request_id):
        _nonempty("request_id", request_id)
        with self._lock:
            try:
                return self._outcomes[request_id]
            except KeyError as exc:
                raise ValueError("Unknown voice request") from exc

    def _failure(self, request, state, started, error):
        completed = self._now()
        self._emit(request.request_id, state, completed, error)
        outcome = VoiceOutcome(
            request.request_id,
            state,
            request.profile_id,
            request.delivery,
            None,
            None,
            error,
            request.correlation_id,
            started,
            completed,
        )
        self._outcomes[request.request_id] = outcome
        return outcome

    def _store_artifact(self, artifact):
        if artifact.audio_id in self._artifacts:
            raise ValueError("Duplicate audio artifact ID")
        while len(self._artifacts) >= self._artifact_limit:
            del self._artifacts[next(iter(self._artifacts))]
        self._artifacts[artifact.audio_id] = artifact

    def _emit(self, request_id, state, at_ms, detail=None):
        self._events.append(
            VoiceEvent(len(self._events) + 1, request_id, state, at_ms, detail)
        )

    def _now(self):
        value = self._clock_ms()
        _timestamp("clock result", value)
        return value


class KokoroAdapter:
    """OpenAI-compatible local Kokoro speech adapter; synthesis only."""

    def __init__(
        self,
        endpoint="http://127.0.0.1:8880/v1/audio/speech",
        model="tts-1",
        audio_id_factory=None,
    ):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.path != "/v1/audio/speech"
        ):
            raise ValueError("Kokoro endpoint must be loopback /v1/audio/speech")
        _nonempty("model", model)
        self.endpoint = endpoint
        self.model = model
        self._audio_id_factory = audio_id_factory or (
            lambda: "audio:" + secrets.token_urlsafe(18)
        )

    def synthesize(self, request, profile, created_at_ms):
        if request.output_format != "wav":
            raise ValueError("Initial Kokoro adapter supports WAV output only")
        body = json.dumps(
            {
                "model": self.model,
                "input": request.text,
                "voice": profile.provider_voice_id,
                "response_format": "wav",
                "speed": request.speed,
            }
        ).encode()
        response = urlopen(
            Request(
                self.endpoint,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        )
        try:
            audio = response.read(MAX_AUDIO_BYTES + 1)
        finally:
            response.close()
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("Kokoro audio response exceeds 32 MiB")
        if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
            raise ValueError("Kokoro returned invalid WAV audio")
        return AudioArtifact(
            self._audio_id_factory(),
            request.request_id,
            "audio/wav",
            audio,
            created_at_ms,
        )


class PipeWirePlayer:
    """Play synthesized bytes on the host through ``pw-play``."""

    def __init__(self, executable="pw-play"):
        _nonempty("executable", executable)
        self.executable = executable

    def play(self, artifact):
        if artifact.mime_type != "audio/wav":
            raise ValueError("PipeWire player currently accepts WAV audio only")
        subprocess.run(
            [self.executable, "-"],
            input=artifact.data,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )


def voice_outcome_manifest(outcome):
    """Return an agent-safe outcome without binary audio bytes."""
    return to_wire(outcome)
