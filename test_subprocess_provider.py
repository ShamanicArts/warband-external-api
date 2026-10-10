import sys
import time
import unittest

from warband_agentic import (
    DecisionBudget,
    ProviderAssignment,
    ProviderDecisionBatch,
    SubprocessDecisionDispatcher,
    SubprocessProviderAdapter,
)


def responding_adapter():
    code = """
import json
import sys
task = json.load(sys.stdin)
faction_id = task["faction_id"]
json.dump({
    "schema": "warband.agentic/subprocess-provider-result/v1",
    "response": {"request_id": f"decision:{faction_id}"},
    "usage": {
        "input_tokens": 500 + faction_id,
        "output_tokens": 40,
        "cost_microusd": 2000,
    },
}, sys.stdout)
"""
    return SubprocessProviderAdapter((sys.executable, "-c", code), environment={})


def sleeping_adapter():
    code = """
import json
import sys
import time
json.load(sys.stdin)
time.sleep(0.5)
json.dump({
    "schema": "warband.agentic/subprocess-provider-result/v1",
    "response": {"request_id": "too-late"},
    "usage": {"input_tokens": 1, "output_tokens": 1, "cost_microusd": 1},
}, sys.stdout)
"""
    return SubprocessProviderAdapter((sys.executable, "-c", code), environment={})


def oversized_adapter():
    code = """
import sys
sys.stdout.write("x" * (256 * 1024 + 1))
"""
    return SubprocessProviderAdapter((sys.executable, "-c", code), environment={})


class SubprocessDecisionDispatcherTests(unittest.TestCase):
    def test_concurrent_local_adapters_complete_one_equal_budget_batch(self):
        batch = ProviderDecisionBatch(
            "batch:subprocess",
            "epoch:subprocess",
            {15: {"turn": 15}, 16: {"turn": 16}},
            {
                15: ProviderAssignment("adapter-a", "model-a", {}),
                16: ProviderAssignment("adapter-b", "model-b", {}),
            },
            DecisionBudget(1000, 100, 2000, 10_000),
        )
        dispatcher = SubprocessDecisionDispatcher(
            batch,
            {"adapter-a": responding_adapter(), "adapter-b": responding_adapter()},
        )
        self.addCleanup(dispatcher.close)

        status = dispatcher.start()
        self.assertEqual(status["state"], "running")
        for _ in range(100):
            status = dispatcher.poll()
            if status["state"] == "complete":
                break
            time.sleep(0.01)

        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["pending_factions"], [])
        self.assertEqual(
            batch.decisions(),
            {
                15: {"request_id": "decision:15"},
                16: {"request_id": "decision:16"},
            },
        )
        audit = batch.audit()
        self.assertEqual(audit["records"]["15"]["status"], "success")
        self.assertEqual(audit["records"]["16"]["status"], "success")
        self.assertEqual(audit["total_usage"]["cost_microusd"], 4000)

    def test_host_deadline_kills_slow_adapter_and_records_timeout(self):
        batch = ProviderDecisionBatch(
            "batch:timeout",
            "epoch:timeout",
            {15: {"turn": 15}, 16: {"turn": 16}},
            {
                15: ProviderAssignment("slow", "model-slow", {}),
                16: ProviderAssignment("fast", "model-fast", {}),
            },
            DecisionBudget(1000, 100, 50, 10_000),
        )
        dispatcher = SubprocessDecisionDispatcher(
            batch,
            {"slow": sleeping_adapter(), "fast": responding_adapter()},
        )
        self.addCleanup(dispatcher.close)
        dispatcher.start()

        for _ in range(100):
            status = dispatcher.poll()
            if status["state"] == "complete":
                break
            time.sleep(0.01)

        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["running_factions"], [])
        audit = batch.audit()
        self.assertEqual(audit["records"]["15"]["status"], "timeout")
        self.assertEqual(audit["records"]["16"]["status"], "success")
        self.assertEqual(
            batch.decisions()[15],
            {"request_id": "batch:timeout:faction:15:no-decision"},
        )

    def test_oversized_output_is_stopped_and_audited_without_pipe_deadlock(self):
        batch = ProviderDecisionBatch(
            "batch:oversized",
            "epoch:oversized",
            {15: {"turn": 15}, 16: {"turn": 16}},
            {
                15: ProviderAssignment("oversized", "model-large", {}),
                16: ProviderAssignment("fast", "model-fast", {}),
            },
            DecisionBudget(1000, 100, 2000, 10_000),
        )
        dispatcher = SubprocessDecisionDispatcher(
            batch,
            {"oversized": oversized_adapter(), "fast": responding_adapter()},
        )
        self.addCleanup(dispatcher.close)
        dispatcher.start()

        for _ in range(100):
            status = dispatcher.poll()
            if status["state"] == "complete":
                break
            time.sleep(0.01)

        self.assertEqual(status["state"], "complete")
        audit = batch.audit()
        self.assertEqual(audit["records"]["15"]["status"], "provider-error")
        self.assertIn("256 KiB", audit["records"]["15"]["detail"])
        self.assertEqual(audit["records"]["16"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
