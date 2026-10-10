import json
import unittest

from warband_agentic.usability import build_faction_usability_fixture


class AgentUsabilityFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = build_faction_usability_fixture()

    def correct_response(self):
        return {
            "affordance_token": "aff:defend-praven",
            "arguments": {"order": "defend", "target_id": 2},
            "expected_revision": 7,
        }

    def test_briefing_is_agent_safe_and_self_contained(self):
        briefing = self.fixture.briefing()
        encoded = json.dumps(briefing)
        self.assertIn("operator", briefing["observation"]["omitted"])
        self.assertNotIn("enemy_exact_strength", encoded)
        self.assertNotIn("handler_id", encoded)
        self.assertNotIn("fixture.party_order", encoded)
        self.assertEqual(len(briefing["affordances"]), 2)
        self.assertEqual(briefing["observation"]["role"], "faction.sovereign")

    def test_correct_bounded_action_passes_registry_and_scores(self):
        evaluation = self.fixture.evaluate(self.correct_response())
        self.assertTrue(evaluation.accepted)
        self.assertEqual(evaluation.score, 100)
        self.assertEqual(evaluation.capability, "party.issue-order")
        self.assertTrue(evaluation.transcript["accepted"])

    def test_wrong_but_valid_strategy_is_not_counted_as_task_success(self):
        evaluation = self.fixture.evaluate(
            {
                "affordance_token": "aff:raid-party-99",
                "arguments": {"order": "raid", "target_id": 99},
                "expected_revision": 7,
            }
        )
        self.assertFalse(evaluation.accepted)
        self.assertIn("does not defend", evaluation.reasons[0])

    def test_raw_operations_extra_fields_and_stale_revision_are_rejected(self):
        raw = {**self.correct_response(), "operation": "party_set_ai_behavior"}
        self.assertIn("restricted interface", self.fixture.evaluate(raw).reasons[0])

        stale_fixture = build_faction_usability_fixture()
        stale = {**self.correct_response(), "expected_revision": 6}
        self.assertIn("stale", stale_fixture.evaluate(stale).reasons[0])

    def test_arguments_cannot_escape_issued_constants(self):
        response = self.correct_response()
        response["arguments"] = {"order": "defend", "target_id": 99}
        evaluation = self.fixture.evaluate(response)
        self.assertFalse(evaluation.accepted)
        self.assertIn("required value", evaluation.reasons[0])


if __name__ == "__main__":
    unittest.main()
