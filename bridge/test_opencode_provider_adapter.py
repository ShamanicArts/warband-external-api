import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RESULT_SCHEMA = "warband.agentic/subprocess-provider-result/v1"


def task(*, settings=None, max_cost_microusd=50_000):
    return {
        "schema": "warband.agentic/provider-decision-task/v1",
        "task_id": "batch:1:faction:15",
        "batch_id": "batch:1",
        "epoch_id": "epoch:1",
        "faction_id": 15,
        "turn_set_sha256": "a" * 64,
        "turn": {
            "observation": {"context": {"revision": 7}},
            "affordances": [
                {
                    "token": "aff:defend-praven",
                    "parameters": {
                        "order": {"const": "defend"},
                        "target_id": {"const": 2},
                    },
                }
            ],
        },
        "assignment": {
            "provider": "opencode",
            "model": "opencode/muse-spark-1.3-contributor-free",
            "settings": settings or {"variant": "minimal"},
        },
        "budget": {
            "max_input_tokens": 4096,
            "max_output_tokens": 300,
            "timeout_ms": 30_000,
            "max_cost_microusd": max_cost_microusd,
        },
    }


def v2_fake_body(request_id="batch:1:faction:15", *, include_usage=True):
    response = {
        "request_id": request_id,
        "affordance_token": "aff:defend-praven",
        "arguments": {"order": "defend", "target_id": 2},
        "expected_revision": 7,
    }
    assistant = {
        "type": "assistant",
        "content": [{"type": "text", "text": json.dumps(response)}],
        "cost": 0.0035,
    }
    if include_usage:
        assistant["tokens"] = {
            "input": 900,
            "output": 80,
            "reasoning": 10,
            "cache": {"read": 0, "write": 0},
        }
    return f"""
import json
import os
import sys

args = sys.argv[1:]
operation = args[1]
payload = json.loads(args[args.index("--data") + 1]) if "--data" in args else None
params = {{}}
for index, argument in enumerate(args):
    if argument == "--param":
        key, value = args[index + 1].split("=", 1)
        params[key] = value
record_path = os.environ["FAKE_RECORD"]
try:
    with open(record_path, encoding="utf-8") as stream:
        records = json.load(stream)
except FileNotFoundError:
    records = []
records.append({{
    "operation": operation,
    "data": payload,
    "params": params,
    "output_limit": os.environ["OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"],
}})
with open(record_path, "w", encoding="utf-8") as stream:
    json.dump(records, stream)
if operation == "session.create":
    print(json.dumps({{"data": {{"id": "session-1"}}}}))
elif operation == "session.prompt":
    print(json.dumps({{"data": {{"id": "inbox-1"}}}}))
elif operation == "session.context":
    print(json.dumps({{"data": [{json.dumps(assistant)}]}}))
"""


class OpenCodeProviderAdapterTests(unittest.TestCase):
    def run_wrapper(self, fake_body, value=None, *, dialect="v2"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "fake-opencode"
            fake.write_text("#!/usr/bin/env python3\n" + fake_body, encoding="utf-8")
            fake.chmod(0o700)
            record = root / "record.json"
            environment = {
                "PATH": os.environ["PATH"],
                "FAKE_RECORD": str(record),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bridge.opencode_provider_adapter",
                    "--executable",
                    str(fake),
                    "--assignment-provider",
                    "opencode",
                    "--dialect",
                    dialect,
                ],
                input=json.dumps(value or task()),
                text=True,
                capture_output=True,
                cwd=Path(__file__).parents[1],
                env=environment,
                timeout=5,
            )
            recorded = json.loads(record.read_text()) if record.exists() else None
            return completed, recorded

    def test_emits_bounded_receipt_from_session_context_and_denies_all_tools(self):
        completed, records = self.run_wrapper(v2_fake_body())

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema"], RESULT_SCHEMA)
        self.assertEqual(result["response"]["request_id"], "batch:1:faction:15")
        self.assertEqual(
            result["usage"],
            {"input_tokens": 900, "output_tokens": 90, "cost_microusd": 3500},
        )
        operations = [record["operation"] for record in records]
        self.assertEqual(
            operations,
            [
                "session.create",
                "session.prompt",
                "session.wait",
                "session.context",
                "session.remove",
            ],
        )
        created = records[0]
        self.assertEqual(created["output_limit"], "300")
        self.assertEqual(
            created["data"]["model"],
            {
                "providerID": "opencode",
                "id": "muse-spark-1.3-contributor-free",
                "variant": "minimal",
            },
        )
        self.assertEqual(
            created["data"]["permissions"],
            [{"action": "*", "resource": "*", "effect": "deny"}],
        )
        self.assertIn("canonical task JSON", records[1]["data"]["text"])
        self.assertEqual(records[1]["params"], {"sessionID": "session-1"})
        self.assertEqual(records[2]["params"], {"sessionID": "session-1"})
        self.assertEqual(records[3]["params"], {"sessionID": "session-1"})
        self.assertEqual(records[4]["params"], {"sessionID": "session-1"})
        self.assertIsNone(records[2]["data"])
        self.assertIsNone(records[3]["data"])
        self.assertIsNone(records[4]["data"])

    def test_v1_dialect_uses_legacy_deny_all_profile_and_variant_flag(self):
        fake_body = r"""
import json
import os
import sys
with open(os.environ["FAKE_RECORD"], "w", encoding="utf-8") as stream:
    json.dump({
        "argv": sys.argv[1:],
        "config": json.loads(open("opencode.json", encoding="utf-8").read()),
    }, stream)
response = {
    "request_id": "batch:1:faction:15",
    "affordance_token": "aff:defend-praven",
    "arguments": {"order": "defend", "target_id": 2},
    "expected_revision": 7,
}
print(json.dumps({"type": "text", "part": {"text": json.dumps(response)}}))
print(json.dumps({"type": "step_finish", "part": {
    "cost": 0,
    "tokens": {
        "input": 10, "output": 10, "reasoning": 0,
        "cache": {"read": 0, "write": 0},
    }
}}))
"""
        completed, record = self.run_wrapper(fake_body, dialect="v1")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--pure", record["argv"])
        self.assertIn("--variant", record["argv"])
        self.assertEqual(
            record["config"]["agent"]["warband-decision"]["tools"], {"*": False}
        )

    def test_rejects_missing_usage_instead_of_inventing_a_receipt(self):
        completed, records = self.run_wrapper(v2_fake_body(include_usage=False))

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertNotIn("batch:1", completed.stderr)
        self.assertEqual(records[-1]["operation"], "session.remove")

    def test_rejects_unknown_settings_before_starting_provider(self):
        completed, record = self.run_wrapper(
            "raise SystemExit('provider should not start')\n",
            task(settings={"temperature": 0}),
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(record)
        self.assertNotIn("temperature", completed.stderr)

    def test_rejects_response_for_another_task(self):
        completed, _ = self.run_wrapper(v2_fake_body("another-task"))

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")


if __name__ == "__main__":
    unittest.main()
