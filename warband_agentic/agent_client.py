"""Loopback client for one constrained agent session."""

import json
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


class AgentHttpClientError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"Agent API returned HTTP {status}: {message}")
        self.status = status
        self.message = message


class AgentHttpClient:
    """Use one private session credential without exposing the operator bridge."""

    def __init__(self, endpoint, token, *, timeout_ms=5000):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.path not in ("", "/")
            or parsed.params
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("agent endpoint must be an IPv4 loopback HTTP origin")
        if not isinstance(token, str) or len(token) < 32 or not token.isprintable():
            raise ValueError(
                "agent token must contain at least 32 printable characters"
            )
        if type(timeout_ms) is not int or not 100 <= timeout_ms <= 120_000:
            raise ValueError("timeout_ms must be from 100 through 120000")
        self._endpoint = endpoint.rstrip("/")
        self._token = token
        self._timeout = timeout_ms / 1000

    def manifest(self):
        return self._request("/v1/agent/manifest")

    def turn(self):
        return self._request("/v1/agent/turn")

    def submit(self, request):
        return self._request("/v1/agent/actions", request)

    def outcome(self, request_id):
        self._identifier("request_id", request_id)
        return self._request("/v1/agent/actions/" + quote(request_id, safe=""))

    def events(self, after=0, limit=100):
        if type(after) is not int or after < 0:
            raise ValueError("after must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be from 1 through 1000")
        return self._request(
            "/v1/agent/events?" + urlencode({"after": after, "limit": limit})
        )

    def _request(self, path, body=None):
        request = Request(
            self._endpoint + path,
            data=json.dumps(body).encode() if body is not None else None,
            method="POST" if body is not None else "GET",
            headers={
                "Authorization": "Bearer " + self._token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            try:
                payload = json.load(exc)
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            finally:
                exc.close()
            message = payload.get("error", "Agent API request failed")
            raise AgentHttpClientError(exc.code, message) from exc

    @staticmethod
    def _identifier(label, value):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 200
            or not value.isprintable()
        ):
            raise ValueError(f"{label} must be 1-200 printable characters")
