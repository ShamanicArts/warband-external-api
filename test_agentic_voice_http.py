import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from warband_agentic import (
    AudioArtifact,
    SpeechRequest,
    VoiceDelivery,
    VoiceHttpClient,
    VoiceProfile,
    VoiceService,
    make_voice_server,
)


class Adapter:
    def __init__(self):
        self.calls = 0

    def synthesize(self, request, profile, created_at_ms):
        self.calls += 1
        return AudioArtifact(
            "audio:one",
            request.request_id,
            "audio/wav",
            b"RIFF\x00\x00\x00\x00WAVEdata",
            created_at_ms,
        )


class VoiceHttpTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.service = VoiceService(
            {"local": self.adapter},
            (VoiceProfile("elder.calm", "Village elder", "local", "bm_george"),),
            clock_ms=iter(range(1000, 1100)).__next__,
        )
        self.token = "a" * 64
        self.server = make_voice_server(self.service, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None, token=None):
        request = Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + (token or self.token),
                "Content-Type": "application/json",
            },
        )
        with urlopen(request) as response:
            if response.headers.get_content_type() == "application/json":
                return response.status, json.load(response)
            return response.status, response.read()

    def test_profiles_hide_provider_configuration_and_require_auth(self):
        status, body = self.request("/v1/voice/profiles")
        self.assertEqual(status, 200)
        self.assertEqual(body["profiles"][0]["profile_id"], "elder.calm")
        self.assertNotIn("provider_voice_id", body["profiles"][0])
        with self.assertRaises(HTTPError) as error:
            self.request("/v1/voice/profiles", token="wrong")
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_speech_outcome_events_request_lookup_and_audio_retrieval(self):
        payload = {
            "request_id": "speech:1",
            "text": "Good day, sir.",
            "profile_id": "elder.calm",
            "delivery": "synthesize-only",
            "correlation_id": "dialogue:42",
        }
        status, outcome = self.request("/v1/voice/speech", payload)
        self.assertEqual(status, 200)
        self.assertEqual(outcome["state"], "ready")
        self.assertEqual(outcome["correlation_id"], "dialogue:42")

        _, repeated = self.request("/v1/voice/speech", payload)
        self.assertEqual(repeated, outcome)
        self.assertEqual(self.adapter.calls, 1)
        conflicting = {**payload, "text": "A different line."}
        with self.assertRaises(HTTPError) as error:
            self.request("/v1/voice/speech", conflicting)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        _, events = self.request("/v1/voice/events?after=1")
        self.assertEqual(
            [event["state"] for event in events["events"]],
            ["synthesizing", "ready"],
        )
        _, lookup = self.request("/v1/voice/requests/" + quote("speech:1", safe=""))
        self.assertEqual(lookup, outcome)
        _, audio = self.request("/v1/voice/audio/" + quote("audio:one", safe=""))
        self.assertTrue(audio.startswith(b"RIFF"))

    def test_client_dispatches_a_typed_request_and_validates_the_outcome(self):
        client = VoiceHttpClient(
            self.base + "/v1/voice/speech", self.token, timeout_ms=2_000
        )
        request = SpeechRequest(
            "speech:client:1",
            "The road to Suno is unsafe.",
            "elder.calm",
            VoiceDelivery.SYNTHESIZE_ONLY,
            correlation_id="action:npc-turn:1",
        )

        outcome = client.speak(request)

        self.assertEqual(outcome.request_id, "speech:client:1")
        self.assertEqual(outcome.state.value, "ready")
        self.assertEqual(outcome.correlation_id, "action:npc-turn:1")
        self.assertEqual(outcome.audio_id, "audio:one")
        self.assertEqual(self.adapter.calls, 1)
        self.assertNotIn(self.token, repr(client))

    def test_malformed_or_expansive_requests_are_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request(
                "/v1/voice/speech",
                {
                    "request_id": "bad",
                    "text": "hello",
                    "profile_id": "elder.calm",
                    "delivery": "synthesize-only",
                    "raw_provider_voice": "do-not-allow",
                },
            )
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_server_refuses_nonloopback_bind_and_short_token(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            make_voice_server(self.service, self.token, host="0.0.0.0")
        with self.assertRaisesRegex(ValueError, "loopback"):
            make_voice_server(self.service, self.token, host="::1")
        with self.assertRaisesRegex(ValueError, "32"):
            make_voice_server(self.service, "short", port=0)


if __name__ == "__main__":
    unittest.main()
