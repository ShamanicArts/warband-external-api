import json
import tempfile
import unittest
from pathlib import Path

from warband_agentic import PipeWirePlayer
from warband_agentic.voice_server import (
    build_voice_service,
    load_voice_config,
    load_voice_token,
)


class VoiceServerConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = {
            "kokoro": {
                "endpoint": "http://127.0.0.1:8880/v1/audio/speech",
                "model": "tts-1",
            },
            "profiles": [
                {
                    "profile_id": "elder.calm",
                    "display_name": "Village elder - calm",
                    "voice_id": "bm_george",
                    "locale": "en-GB",
                    "tags": ["elder", "calm"],
                }
            ],
            "playback": "pipewire",
            "artifact_limit": 8,
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self, value):
        path = self.root / "voice.json"
        path.write_text(json.dumps(value))
        return path

    def test_config_builds_private_kokoro_mapping_and_optional_player(self):
        service = build_voice_service(load_voice_config(self.write(self.config)))
        profile = service.profiles()[0]
        self.assertEqual(profile["profile_id"], "elder.calm")
        self.assertNotIn("voice_id", profile)
        self.assertIsInstance(service._player, PipeWirePlayer)

    def test_config_rejects_unknown_fields_remote_endpoint_and_bad_playback(self):
        cases = (
            ({**self.config, "secret_provider_option": True}, "Unexpected"),
            ({**self.config, "playback": "game"}, "playback"),
            (
                {
                    **self.config,
                    "kokoro": {"endpoint": "https://example.com/v1/audio/speech"},
                },
                "loopback",
            ),
            ({**self.config, "profiles": []}, "at least one"),
        )
        for config, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValueError, message),
            ):
                build_voice_service(load_voice_config(self.write(config)))

    def test_token_file_is_trimmed_and_validated_without_logging(self):
        token = self.root / "voice.token"
        token.write_text("a" * 64 + "\n")
        self.assertEqual(load_voice_token(token), "a" * 64)
        token.write_text("short")
        with self.assertRaisesRegex(ValueError, "32"):
            load_voice_token(token)


if __name__ == "__main__":
    unittest.main()
