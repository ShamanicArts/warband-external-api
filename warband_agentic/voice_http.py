"""Authenticated loopback HTTP façade for :mod:`warband_agentic.voice`."""

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from warband_agentic.contracts import to_wire
from warband_agentic.voice import (
    SpeechRequest,
    VoiceDelivery,
    VoiceService,
    voice_outcome_manifest,
)


def make_voice_server(service, token, host="127.0.0.1", port=8870):
    if not isinstance(service, VoiceService):
        raise TypeError("service must be a VoiceService")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("voice API token must contain at least 32 characters")
    if host != "127.0.0.1":
        raise ValueError("voice API must bind to IPv4 loopback")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args):
            pass

        def _authorized(self):
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            return hmac.compare_digest(supplied.encode(), token.encode())

        def _reply_json(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _reply_audio(self, artifact):
            self.send_response(200)
            self.send_header("Content-Type", artifact.mime_type)
            self.send_header("Content-Length", str(len(artifact.data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(artifact.data)

        def _authenticate(self):
            if self._authorized():
                return True
            self._reply_json(403, {"error": "Forbidden"})
            return False

        def do_GET(self):
            if not self._authenticate():
                return
            url = urlparse(self.path)
            try:
                if url.path == "/v1/voice/profiles":
                    self._reply_json(200, {"profiles": service.profiles()})
                elif url.path == "/v1/voice/events":
                    query = parse_qs(url.query)
                    if any(len(value) != 1 for value in query.values()):
                        raise ValueError("Duplicate event cursor field")
                    after = int(query.get("after", ["0"])[0])
                    self._reply_json(
                        200,
                        {
                            "events": [
                                to_wire(event) for event in service.events(after)
                            ]
                        },
                    )
                elif url.path.startswith("/v1/voice/requests/"):
                    request_id = unquote(url.path.removeprefix("/v1/voice/requests/"))
                    self._reply_json(
                        200, voice_outcome_manifest(service.outcome(request_id))
                    )
                elif url.path.startswith("/v1/voice/audio/"):
                    audio_id = unquote(url.path.removeprefix("/v1/voice/audio/"))
                    self._reply_audio(service.artifact(audio_id))
                else:
                    self._reply_json(404, {"error": "Unknown endpoint"})
            except (ValueError, TypeError) as exc:
                self._reply_json(400, {"error": str(exc)})

        def do_POST(self):
            if not self._authenticate():
                return
            if urlparse(self.path).path != "/v1/voice/speech":
                self._reply_json(404, {"error": "Unknown endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("Invalid body length")
                body = json.loads(self.rfile.read(length))
                allowed = {
                    "request_id",
                    "text",
                    "profile_id",
                    "delivery",
                    "speed",
                    "output_format",
                    "correlation_id",
                }
                if not isinstance(body, dict) or set(body) - allowed:
                    raise ValueError("Unexpected voice request fields")
                required = {"request_id", "text", "profile_id", "delivery"}
                if not required <= set(body):
                    raise ValueError("Missing voice request fields")
                request = SpeechRequest(
                    body["request_id"],
                    body["text"],
                    body["profile_id"],
                    VoiceDelivery(body["delivery"]),
                    body.get("speed", 1.0),
                    body.get("output_format", "wav"),
                    body.get("correlation_id"),
                )
                self._reply_json(200, voice_outcome_manifest(service.speak(request)))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._reply_json(400, {"error": str(exc)})

    return ThreadingHTTPServer((host, port), Handler)
