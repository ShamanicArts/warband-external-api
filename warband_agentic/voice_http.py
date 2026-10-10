"""Authenticated loopback HTTP façade for :mod:`warband_agentic.voice`."""

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from warband_agentic.contracts import CONTRACT_VERSION, to_wire
from warband_agentic.voice import (
    SpeechRequest,
    VoiceDelivery,
    VoiceOutcome,
    VoiceService,
    VoiceState,
    voice_outcome_manifest,
)

_MAX_VOICE_RESPONSE_BYTES = 64 * 1024


class VoiceHttpError(RuntimeError):
    """Sanitized failure while dispatching to the local voice service."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def voice_outcome_from_manifest(value):
    expected = {
        "request_id",
        "state",
        "profile_id",
        "delivery",
        "audio_id",
        "mime_type",
        "error",
        "correlation_id",
        "started_at_ms",
        "completed_at_ms",
        "schema",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise VoiceHttpError("voice service returned an invalid outcome")
    try:
        return VoiceOutcome(
            value["request_id"],
            VoiceState(value["state"]),
            value["profile_id"],
            VoiceDelivery(value["delivery"]),
            value["audio_id"],
            value["mime_type"],
            value["error"],
            value["correlation_id"],
            value["started_at_ms"],
            value["completed_at_ms"],
            value["schema"],
        )
    except (TypeError, ValueError) as exc:
        raise VoiceHttpError("voice service returned an invalid outcome") from exc


class VoiceHttpClient:
    """Bounded authenticated client for one loopback voice service."""

    __slots__ = ("endpoint", "timeout_ms", "_token", "_opener")

    def __init__(self, endpoint, token, *, timeout_ms=30_000):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.path != "/v1/voice/speech"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("voice endpoint must be loopback /v1/voice/speech")
        if not 1024 <= parsed.port <= 65535:
            raise ValueError("voice endpoint must use an unprivileged TCP port")
        if (
            not isinstance(token, str)
            or not 32 <= len(token) <= 512
            or not token.isprintable()
        ):
            raise ValueError("voice token must contain 32-512 printable characters")
        if type(timeout_ms) is not int or not 100 <= timeout_ms <= 120_000:
            raise ValueError("voice timeout must be from 100 through 120000 ms")
        self.endpoint = endpoint
        self.timeout_ms = timeout_ms
        self._token = token
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def __repr__(self):
        return (
            f"VoiceHttpClient(endpoint={self.endpoint!r}, "
            f"timeout_ms={self.timeout_ms!r})"
        )

    def speak(self, request):
        if not isinstance(request, SpeechRequest):
            raise TypeError("request must be a SpeechRequest")
        encoded = json.dumps(
            to_wire(request), allow_nan=False, separators=(",", ":")
        ).encode()
        try:
            response = self._opener.open(
                Request(
                    self.endpoint,
                    data=encoded,
                    headers={
                        "Authorization": "Bearer " + self._token,
                        "Content-Type": "application/json",
                    },
                    method="POST",
                ),
                timeout=self.timeout_ms / 1000,
            )
            try:
                if response.headers.get_content_type() != "application/json":
                    raise VoiceHttpError("voice service returned an invalid response")
                body = response.read(_MAX_VOICE_RESPONSE_BYTES + 1)
            finally:
                response.close()
        except VoiceHttpError:
            raise
        except HTTPError as exc:
            exc.close()
            raise VoiceHttpError("voice service request failed") from exc
        except (URLError, OSError) as exc:
            raise VoiceHttpError("voice service request failed") from exc
        if len(body) > _MAX_VOICE_RESPONSE_BYTES:
            raise VoiceHttpError("voice service response exceeded its limit")
        try:
            outcome = voice_outcome_from_manifest(json.loads(body))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VoiceHttpError("voice service returned invalid JSON") from exc
        if (
            outcome.request_id != request.request_id
            or outcome.profile_id != request.profile_id
            or outcome.delivery is not request.delivery
            or outcome.correlation_id != request.correlation_id
        ):
            raise VoiceHttpError("voice service returned a mismatched outcome")
        terminal = {
            VoiceState.READY,
            VoiceState.PLAYED,
            VoiceState.SYNTHESIS_FAILED,
            VoiceState.PLAYBACK_FAILED,
        }
        if outcome.state not in terminal:
            raise VoiceHttpError("voice service returned a non-terminal outcome")
        return outcome


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
                        {"events": [to_wire(event) for event in service.events(after)]},
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
                    "schema",
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
                    body.get("schema", CONTRACT_VERSION),
                )
                self._reply_json(200, voice_outcome_manifest(service.speak(request)))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._reply_json(400, {"error": str(exc)})

    return ThreadingHTTPServer((host, port), Handler)
