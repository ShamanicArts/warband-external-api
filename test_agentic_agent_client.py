import tempfile
import threading
import unittest
from pathlib import Path

from test_agentic_agent_api import SessionHarness
from warband_agentic import AgentHttpClient, AgentHttpClientError, make_agent_server


class AgentHttpClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.harness = SessionHarness(Path(self.temp.name) / "events.sqlite3")
        self.token = "a" * 64
        self.server = make_agent_server(self.harness.session, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.client = AgentHttpClient(endpoint, self.token)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.harness.close()
        self.temp.cleanup()

    def test_complete_constrained_session_round_trip(self):
        manifest = self.client.manifest()
        turn = self.client.turn()
        affordance = turn["affordances"][0]

        outcome = self.client.submit(
            {
                "request_id": "mcp:decision:1",
                "affordance_token": affordance["token"],
                "arguments": {"order": "defend"},
                "expected_revision": turn["observation"]["context"]["revision"],
            }
        )

        self.assertEqual(manifest["role"], "faction.sovereign")
        self.assertEqual(outcome["state"], "observed")
        self.assertEqual(self.client.outcome("mcp:decision:1"), outcome)
        events = self.client.events(limit=10)
        self.assertEqual(events["events"][0]["event_type"], "action.observed")

    def test_loopback_credentials_and_stale_errors_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            AgentHttpClient("https://example.com:443", self.token)
        unauthorized = AgentHttpClient(
            f"http://127.0.0.1:{self.server.server_port}", "b" * 64
        )
        with self.assertRaises(AgentHttpClientError) as error:
            unauthorized.turn()
        self.assertEqual(error.exception.status, 403)

        turn = self.client.turn()
        with self.assertRaises(AgentHttpClientError) as error:
            self.client.submit(
                {
                    "request_id": "mcp:stale",
                    "affordance_token": turn["affordances"][0]["token"],
                    "arguments": {"order": "defend"},
                    "expected_revision": 6,
                }
            )
        self.assertEqual(error.exception.status, 409)
        self.assertIn("stale", error.exception.message)


if __name__ == "__main__":
    unittest.main()
