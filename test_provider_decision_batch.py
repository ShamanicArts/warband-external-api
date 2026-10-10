import unittest
from copy import deepcopy

from warband_agentic import (
    DecisionBudget,
    DecisionUsage,
    ProviderAssignment,
    ProviderDecisionBatch,
)


class ProviderDecisionBatchTests(unittest.TestCase):
    def test_equal_budget_tasks_and_success_receipts_produce_audited_decisions(self):
        budget = DecisionBudget(
            max_input_tokens=4096,
            max_output_tokens=300,
            timeout_ms=30_000,
            max_cost_microusd=50_000,
        )
        turns = {
            15: {"observation": {"faction": 15}, "affordances": [{"token": "a"}]},
            16: {"observation": {"faction": 16}, "affordances": [{"token": "b"}]},
        }
        assignments = {
            15: ProviderAssignment("openai", "luna", {"temperature": 0}),
            16: ProviderAssignment("cursor", "grok-4.6", {"temperature": 0}),
        }
        batch = ProviderDecisionBatch(
            "batch:epoch-1",
            "epoch:1",
            turns,
            assignments,
            budget,
        )

        tasks = batch.tasks()

        self.assertEqual(list(tasks), [15, 16])
        self.assertEqual(tasks[15]["budget"], tasks[16]["budget"])
        self.assertEqual(tasks[15]["turn"], turns[15])
        self.assertEqual(tasks[16]["assignment"]["model"], "grok-4.6")
        first = {
            "request_id": "decision:15",
            "affordance_token": "a",
            "arguments": {"order": "defend", "target_id": 2},
            "expected_revision": 7,
        }
        second = {
            "request_id": "decision:16",
            "affordance_token": "b",
            "arguments": {"order": "attack", "target_id": 3},
            "expected_revision": 7,
        }
        batch.record_success(
            15,
            first,
            DecisionUsage(900, 80, 1200, 3_500),
        )
        batch.record_success(
            16,
            second,
            DecisionUsage(1100, 95, 1800, 4_200),
        )

        self.assertEqual(batch.decisions(), {15: first, 16: second})
        audit = batch.audit()
        self.assertEqual(audit["schema"], "warband.agentic/provider-decision-batch/v1")
        self.assertEqual(audit["status"], "complete")
        self.assertEqual(audit["records"]["15"]["status"], "success")
        self.assertEqual(audit["records"]["16"]["usage"]["cost_microusd"], 4_200)
        self.assertEqual(audit["total_usage"]["input_tokens"], 2000)
        self.assertEqual(audit["total_usage"]["output_tokens"], 175)
        self.assertEqual(audit["total_usage"]["cost_microusd"], 7_700)
        self.assertEqual(len(audit["turn_set_sha256"]), 64)
        self.assertEqual(len(audit["audit_sha256"]), 64)

    def test_timeouts_and_over_budget_responses_become_audited_no_decisions(self):
        batch = ProviderDecisionBatch(
            "batch:bounded",
            "epoch:bounded",
            {15: {"turn": 15}, 16: {"turn": 16}},
            {
                15: ProviderAssignment("provider-a", "model-a", {}),
                16: ProviderAssignment("provider-b", "model-b", {}),
            },
            DecisionBudget(100, 20, 1000, 500),
        )
        over_budget_response = {
            "request_id": "decision:too-large",
            "affordance_token": "a",
            "arguments": {},
            "expected_revision": 1,
        }

        self.assertTrue(
            batch.record_success(
                15,
                over_budget_response,
                DecisionUsage(101, 10, 900, 400),
            )
        )
        self.assertFalse(
            batch.record_success(
                15,
                over_budget_response,
                DecisionUsage(101, 10, 900, 400),
            )
        )
        batch.record_failure(
            16,
            "timeout",
            "The provider exceeded the equal 1000 ms deadline",
            DecisionUsage(80, 0, 1000, 200),
        )

        decisions = batch.decisions()
        self.assertEqual(
            decisions,
            {
                15: {"request_id": "batch:bounded:faction:15:no-decision"},
                16: {"request_id": "batch:bounded:faction:16:no-decision"},
            },
        )
        audit = batch.audit()
        self.assertEqual(audit["records"]["15"]["status"], "budget-exceeded")
        self.assertIn("input token", audit["records"]["15"]["detail"])
        self.assertEqual(audit["records"]["16"]["status"], "timeout")
        self.assertNotIn("response_sha256", audit["records"]["16"])
        with self.assertRaisesRegex(ValueError, "conflicts"):
            batch.record_success(
                15,
                {**over_budget_response, "request_id": "different"},
                DecisionUsage(50, 10, 900, 400),
            )

    def test_public_provider_settings_refuse_embedded_credentials(self):
        with self.assertRaisesRegex(ValueError, "credential-like"):
            ProviderAssignment(
                "openai",
                "luna",
                {"transport": {"api_key": "must-not-enter-artifacts"}},
            )

    def test_partial_batch_checkpoint_recovers_receipts_without_reissuing_tasks(self):
        batch = ProviderDecisionBatch(
            "batch:recover",
            "epoch:recover",
            {15: {"turn": 15}, 16: {"turn": 16}},
            {
                15: ProviderAssignment("provider-a", "model-a", {}),
                16: ProviderAssignment("provider-b", "model-b", {}),
            },
            DecisionBudget(1000, 100, 30_000, 10_000),
        )
        first_response = {"request_id": "decision:15"}
        first_usage = DecisionUsage(500, 40, 1000, 2_000)
        batch.record_success(15, first_response, first_usage)

        checkpoint = batch.checkpoint()
        restored = ProviderDecisionBatch.from_checkpoint(checkpoint)

        self.assertEqual(restored.tasks(), batch.tasks())
        self.assertFalse(restored.record_success(15, first_response, first_usage))
        restored.record_failure(16, "provider-error", "Provider returned no result")
        self.assertEqual(restored.audit()["records"]["15"]["status"], "success")
        self.assertEqual(restored.audit()["records"]["16"]["status"], "provider-error")

        damaged = deepcopy(checkpoint)
        damaged["payload"]["epoch_id"] = "epoch:tampered"
        with self.assertRaisesRegex(ValueError, "checksum"):
            ProviderDecisionBatch.from_checkpoint(damaged)


if __name__ == "__main__":
    unittest.main()
