import json
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from warband_agentic import (
    AudioArtifact,
    KokoroAdapter,
    PipeWirePlayer,
    SpeechRequest,
    VoiceDelivery,
    VoiceProfile,
    VoiceService,
    VoiceState,
    voice_outcome_manifest,
)


class FakeAdapter:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def synthesize(self, request, profile, created_at_ms):
        self.calls.append((request, profile, created_at_ms))
        if self.fail:
            raise RuntimeError("synth unavailable")
        return AudioArtifact(
            f"audio:{request.request_id}",
            request.request_id,
            "audio/wav",
            b"RIFF\x00\x00\x00\x00WAVEdata",
            created_at_ms,
        )


class FakePlayer:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def play(self, artifact):
        self.calls.append(artifact)
        if self.fail:
            raise RuntimeError("speaker unavailable")


class VoiceServiceTests(unittest.TestCase):
    def setUp(self):
        self.times = iter(range(1000, 1100))
        self.adapter = FakeAdapter()
        self.player = FakePlayer()
        self.profile = VoiceProfile(
            "elder.calm",
            "Village elder - calm",
            "local",
            "bm_george",
            "en-GB",
            ("male", "elder", "calm"),
        )
        self.service = VoiceService(
            {"local": self.adapter},
            (self.profile,),
            self.player,
            clock_ms=lambda: next(self.times),
            artifact_limit=2,
        )

    def request(self, delivery=VoiceDelivery.SYNTHESIZE_ONLY, request_id="speech:1"):
        return SpeechRequest(
            request_id,
            "Good day, sir.",
            self.profile.profile_id,
            delivery,
            1.0,
            "wav",
            "dialogue-event:42",
        )

    def test_synthesis_only_retains_audio_and_emits_lifecycle(self):
        outcome = self.service.speak(self.request())
        self.assertIs(outcome.state, VoiceState.READY)
        self.assertEqual(outcome.correlation_id, "dialogue-event:42")
        self.assertEqual(self.service.artifact(outcome.audio_id).data[:4], b"RIFF")
        self.assertEqual(
            [event.state for event in self.service.events()],
            [VoiceState.QUEUED, VoiceState.SYNTHESIZING, VoiceState.READY],
        )
        self.assertNotIn("data", voice_outcome_manifest(outcome))
        json.dumps(voice_outcome_manifest(outcome))

    def test_host_playback_is_optional_and_separate_from_synthesis(self):
        outcome = self.service.speak(self.request(VoiceDelivery.PLAY_HOST))
        self.assertIs(outcome.state, VoiceState.PLAYED)
        self.assertEqual(len(self.player.calls), 1)
        self.assertEqual(
            [event.state for event in self.service.events()][-2:],
            [VoiceState.PLAYING, VoiceState.PLAYED],
        )

    def test_synthesis_and_playback_failures_are_outcomes_not_exceptions(self):
        synthesis = VoiceService(
            {"local": FakeAdapter(fail=True)},
            (self.profile,),
            self.player,
            clock_ms=lambda: next(self.times),
        ).speak(self.request())
        self.assertIs(synthesis.state, VoiceState.SYNTHESIS_FAILED)
        self.assertIsNone(synthesis.audio_id)

        playback = VoiceService(
            {"local": self.adapter},
            (self.profile,),
            FakePlayer(fail=True),
            clock_ms=lambda: next(self.times),
        )
        failed = playback.speak(self.request(VoiceDelivery.PLAY_HOST, "speech:2"))
        self.assertIs(failed.state, VoiceState.PLAYBACK_FAILED)
        self.assertIsNotNone(failed.audio_id)
        self.assertTrue(playback.artifact(failed.audio_id).data)

    def test_request_ids_are_idempotent_and_artifacts_are_bounded(self):
        request = self.request()
        first = self.service.speak(request)
        second = self.service.speak(request)
        self.assertIs(first, second)
        self.assertEqual(len(self.adapter.calls), 1)
        conflicting = SpeechRequest(
            request.request_id,
            "A different line.",
            request.profile_id,
            request.delivery,
        )
        with self.assertRaisesRegex(ValueError, "different input"):
            self.service.speak(conflicting)
        for index in (2, 3):
            self.service.speak(self.request(request_id=f"speech:{index}"))
        with self.assertRaisesRegex(ValueError, "evicted"):
            self.service.artifact(first.audio_id)

    def test_concurrent_duplicate_request_synthesizes_exactly_once(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingAdapter(FakeAdapter):
            def synthesize(adapter_self, request, profile, created_at_ms):
                entered.set()
                release.wait()
                return super().synthesize(request, profile, created_at_ms)

        adapter = BlockingAdapter()
        service = VoiceService(
            {"local": adapter},
            (self.profile,),
            clock_ms=lambda: next(self.times),
        )
        request = self.request()
        outcomes = []
        errors = []

        def speak():
            try:
                outcomes.append(service.speak(request))
            except Exception as exc:
                errors.append(exc)

        first = threading.Thread(target=speak)
        second = threading.Thread(target=speak)
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()
        release.set()
        first.join(1)
        second.join(1)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(len(outcomes), 2)
        self.assertIs(outcomes[0], outcomes[1])

    def test_public_profiles_hide_adapter_and_provider_voice_ids(self):
        profiles = self.service.profiles()
        self.assertEqual(profiles[0]["profile_id"], "elder.calm")
        self.assertNotIn("adapter_id", profiles[0])
        self.assertNotIn("provider_voice_id", profiles[0])
        self.assertNotIn("bm_george", json.dumps(profiles))


class KokoroAdapterTests(unittest.TestCase):
    def setUp(self):
        self.profile = VoiceProfile(
            "elder.calm", "Village elder", "kokoro", "bm_george"
        )
        self.request = SpeechRequest(
            "speech:1",
            "Good day.",
            self.profile.profile_id,
            VoiceDelivery.SYNTHESIZE_ONLY,
            0.9,
        )

    def test_kokoro_posts_openai_compatible_payload_and_validates_wav(self):
        response = Mock()
        response.read.return_value = b"RIFF\x00\x00\x00\x00WAVEdata"
        adapter = KokoroAdapter(audio_id_factory=lambda: "audio:1")
        with patch("warband_agentic.voice.urlopen", return_value=response) as open_:
            artifact = adapter.synthesize(self.request, self.profile, 1000)
        request = open_.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(
            body,
            {
                "model": "tts-1",
                "input": "Good day.",
                "voice": "bm_george",
                "response_format": "wav",
                "speed": 0.9,
            },
        )
        self.assertEqual(artifact.audio_id, "audio:1")
        self.assertEqual(artifact.mime_type, "audio/wav")
        response.close.assert_called_once()

    def test_kokoro_rejects_remote_endpoint_and_invalid_audio(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            KokoroAdapter("https://example.com/v1/audio/speech")
        response = Mock()
        response.read.return_value = b"not audio"
        with patch("warband_agentic.voice.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "invalid WAV"):
                KokoroAdapter().synthesize(self.request, self.profile, 1000)

    def test_pipewire_player_uses_stdin_without_shell_or_timeout(self):
        artifact = AudioArtifact(
            "audio:1", "speech:1", "audio/wav", b"RIFF....WAVE", 1000
        )
        with patch("warband_agentic.voice.subprocess.run") as run:
            PipeWirePlayer().play(artifact)
        self.assertEqual(run.call_args.args[0], ["pw-play", "-"])
        self.assertEqual(run.call_args.kwargs["input"], artifact.data)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertNotIn("timeout", run.call_args.kwargs)
        self.assertIs(run.call_args.kwargs["stdout"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
