import threading
import unittest

from warband_agentic import AgentHttpClient, AgentHttpClientError, make_agent_server
from warband_agentic.mcp_usability import build_faction_mcp_usability_fixture


class FactionMcpUsabilityFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = build_faction_mcp_usability_fixture()
        self.token = "a" * 64
        self.server = make_agent_server(self.fixture.session, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = AgentHttpClient(
            f"http://127.0.0.1:{self.server.server_port}", self.token
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_direct_session_forces_refresh_then_observes_exact_action(self):
        first = self.client.turn()
        defend = first["affordances"][0]
        self.assertEqual(first["observation"]["context"]["revision"], 7)
        self.assertNotIn(
            "operator.enemy_exact_strength",
            {fact["key"] for fact in first["observation"]["facts"]},
        )

        with self.assertRaises(AgentHttpClientError) as stale:
            self.client.submit(
                {
                    "request_id": "decision:stale-attempt",
                    "affordance_token": defend["token"],
                    "arguments": {"order": "defend", "target_id": 2},
                    "expected_revision": 7,
                }
            )
        self.assertEqual(stale.exception.status, 409)

        refreshed = self.client.turn()
        defend = refreshed["affordances"][0]
        request = {
            "request_id": "decision:refreshed-defense",
            "affordance_token": defend["token"],
            "arguments": {"order": "defend", "target_id": 2},
            "expected_revision": 8,
        }
        outcome = self.client.submit(request)

        self.assertEqual(outcome["state"], "observed")
        self.assertEqual(outcome["facts"][0]["value"], "defend")
        self.assertEqual(self.client.outcome(request["request_id"]), outcome)
        self.assertEqual(self.fixture.selected_order, "defend")
        self.assertEqual(self.fixture.dispatch_count, 1)

    def test_manifest_exposes_direct_agent_rules_without_private_bindings(self):
        manifest = self.client.manifest()

        self.assertEqual(
            manifest["submission"]["authorization"]["source"],
            "turn.affordances[]",
        )
        self.assertEqual(
            manifest["submission"]["request_id"]["example"],
            "decision:epoch-12:party-17",
        )
        self.assertNotIn("fixture.party-order", str(manifest))


if __name__ == "__main__":
    unittest.main()
