"""Authenticated loopback HTTP adapter for one constrained agent session."""

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from warband_agentic.agent_api import (
    AgentConflict,
    AgentNotFound,
    ConstrainedAgentSession,
)
from warband_agentic.contracts import to_wire


def make_agent_server(session, token, host="127.0.0.1", port=8869):
    if not isinstance(session, ConstrainedAgentSession):
        raise TypeError("session must be a ConstrainedAgentSession")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("agent API token must contain at least 32 characters")
    if host != "127.0.0.1":
        raise ValueError("agent API must bind to IPv4 loopback")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args):
            pass

        def _reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self):
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            return hmac.compare_digest(supplied.encode(), token.encode())

        def _authenticate(self):
            if self._authorized():
                return True
            self._reply(403, {"error": "Forbidden"})
            return False

        def do_GET(self):
            if not self._authenticate():
                return
            url = urlparse(self.path)
            try:
                if url.path == "/v1/agent/manifest":
                    self._reply(200, session.manifest())
                elif url.path == "/v1/agent/turn":
                    self._reply(200, to_wire(session.turn()))
                elif url.path == "/v1/agent/events":
                    query = parse_qs(url.query)
                    if any(len(values) != 1 for values in query.values()):
                        raise ValueError("Duplicate event cursor field")
                    allowed = {"after", "limit"}
                    if set(query) - allowed:
                        raise ValueError("Unexpected event cursor field")
                    page = session.events(
                        int(query.get("after", ["0"])[0]),
                        int(query.get("limit", ["100"])[0]),
                    )
                    self._reply(200, to_wire(page))
                elif url.path.startswith("/v1/agent/actions/"):
                    request_id = unquote(
                        url.path.removeprefix("/v1/agent/actions/")
                    )
                    self._reply(200, to_wire(session.outcome(request_id)))
                else:
                    self._reply(404, {"error": "Unknown endpoint"})
            except AgentNotFound as exc:
                self._reply(404, {"error": str(exc)})
            except (TypeError, ValueError) as exc:
                self._reply(400, {"error": str(exc)})

        def do_POST(self):
            if not self._authenticate():
                return
            if urlparse(self.path).path != "/v1/agent/actions":
                self._reply(404, {"error": "Unknown endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("Invalid body length")
                body = json.loads(self.rfile.read(length))
                self._reply(200, to_wire(session.submit(body)))
            except AgentConflict as exc:
                self._reply(409, {"error": str(exc)})
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                self._reply(400, {"error": str(exc)})

    return ThreadingHTTPServer((host, port), Handler)
