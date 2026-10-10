import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from warband_agentic.faction_arena import build_deterministic_faction_arena


def decision_for(task, action, request_id):
    matches = []
    for affordance in task["turn"]["affordances"]:
        properties = affordance["parameters"]["properties"]
        if properties["action"]["const"] == action:
            matches.append(affordance)
    if len(matches) != 1:
        raise AssertionError(f"expected one {action} affordance")
    affordance = matches[0]
    arguments = {
        name: schema["const"]
        for name, schema in affordance["parameters"]["properties"].items()
    }
    return {
        "request_id": request_id,
        "affordance_token": affordance["token"],
        "arguments": arguments,
        "expected_revision": task["turn"]["observation"]["context"]["revision"],
    }


class DeterministicFactionArenaTests(unittest.TestCase):
    def test_briefing_is_synchronized_role_filtered_and_exactly_bounded(self):
        arena = build_deterministic_faction_arena()

        briefing = arena.briefing()

        self.assertEqual(
            briefing["schema"], "warband.agentic/deterministic-faction-arena/v1"
        )
        self.assertEqual(set(briefing["factions"]), {"15", "16"})
        self.assertTrue(briefing["simultaneous_decisions"])
        self.assertFalse(briefing["game_launched"])
        self.assertEqual(len(briefing["turn_set_sha256"]), 64)
        for faction_id in (15, 16):
            task = briefing["factions"][str(faction_id)]
            facts = {
                fact["key"]: fact["value"]
                for fact in task["turn"]["observation"]["facts"]
            }
            enemy_id = 16 if faction_id == 15 else 15
            self.assertEqual(facts[f"faction.{faction_id}.military_strength"], 100)
            self.assertEqual(facts[f"reports.{enemy_id}.strength_band"], "90-110")
            self.assertNotIn(f"faction.{enemy_id}.military_strength", facts)
            self.assertEqual(
                facts["public.resolution_rules"]["timing"],
                "all decisions resolve simultaneously",
            )
            self.assertEqual(
                facts["public.resolution_rules"]["recruit"]["supply_cost"], 20
            )
            self.assertTrue(
                facts["public.resolution_rules"]["defend"][
                    "prevents_settlement_capture"
                ]
            )
            actions = {
                item["parameters"]["properties"]["action"]["const"]
                for item in task["turn"]["affordances"]
            }
            self.assertEqual(actions, {"attack", "defend", "recruit"})
            self.assertEqual(task["response_schema"]["additionalProperties"], False)

    def test_attack_and_recruit_resolve_simultaneously_into_scored_report(self):
        arena = build_deterministic_faction_arena()
        briefing = arena.briefing()
        decisions = {
            15: decision_for(
                briefing["factions"]["15"], "attack", "epoch-1:swadia:attack"
            ),
            16: decision_for(
                briefing["factions"]["16"], "recruit", "epoch-1:vaegirs:recruit"
            ),
        }

        result = arena.resolve(decisions)

        self.assertEqual(result["schema"], "warband.agentic/benchmark-run/v2")
        self.assertEqual(result["epoch_count"], 1)
        self.assertEqual(result["scorecard"]["ranking"], [15, 16])
        final = result["epochs"][0]["metrics"]["factions"]
        swadia = {item["key"]: item["value"] for item in final["15"]}
        vaegirs = {item["key"]: item["value"] for item in final["16"]}
        self.assertEqual(
            swadia,
            {"military_strength": 90, "settlements": 2, "surviving": True},
        )
        self.assertEqual(
            vaegirs,
            {"military_strength": 95, "settlements": 0, "surviving": True},
        )
        transcript = result["epochs"][0]["transcript"]
        self.assertEqual(transcript["state"], "resolved")
        self.assertEqual(transcript["campaign_advance"]["elapsed_hours"], 1)
        for faction_id in ("15", "16"):
            record = transcript["decision_records"][faction_id]
            self.assertTrue(record["accepted"])
            self.assertEqual(record["outcome"]["state"], "observed")
        self.assertEqual(result["run_metadata"]["backend"], "deterministic-simulator")

    def test_cli_exports_one_private_task_and_resolves_two_json_decisions(self):
        exported = subprocess.run(
            [
                sys.executable,
                "-m",
                "warband_agentic.faction_arena_cli",
                "export",
                "--faction",
                "15",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        task = json.loads(exported.stdout)
        self.assertEqual(task["faction_id"], 15)
        self.assertNotIn('"faction_id": 16', exported.stdout)

        arena = build_deterministic_faction_arena()
        briefing = arena.briefing()
        responses = {
            "15": decision_for(
                briefing["factions"]["15"], "defend", "cli:swadia:defend"
            ),
            "16": decision_for(
                briefing["factions"]["16"], "attack", "cli:vaegirs:attack"
            ),
        }
        resolved = subprocess.run(
            [
                sys.executable,
                "-m",
                "warband_agentic.faction_arena_cli",
                "resolve",
            ],
            input=json.dumps(responses),
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(resolved.stdout)
        self.assertEqual(report["epoch_count"], 1)
        self.assertEqual(
            report["epochs"][0]["transcript"]["decisions"]["15"]["request_id"],
            "cli:swadia:defend",
        )

        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory, "decisions.json")
            input_path.write_text(json.dumps(responses))
            from_file = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "warband_agentic.faction_arena_cli",
                    "resolve",
                    str(input_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertEqual(
            json.loads(from_file.stdout)["report_sha256"], report["report_sha256"]
        )

    def test_provider_results_are_equal_budgeted_and_bound_into_report_audit(self):
        arena = build_deterministic_faction_arena()
        briefing = arena.briefing()
        results = {
            15: {
                "assignment": {
                    "provider": "pi",
                    "model": "opencode-go/deepseek-v4.1-flash",
                    "settings": {"reasoning_effort": "high"},
                },
                "response": decision_for(
                    briefing["factions"]["15"],
                    "attack",
                    "providers:swadia:attack",
                ),
                "usage": {
                    "input_tokens": 1800,
                    "output_tokens": 120,
                    "elapsed_ms": 9000,
                    "cost_microusd": None,
                },
            },
            16: {
                "assignment": {
                    "provider": "codex",
                    "model": "gpt-6-luna",
                    "settings": {"reasoning_effort": "medium"},
                },
                "response": decision_for(
                    briefing["factions"]["16"],
                    "defend",
                    "providers:vaegirs:defend",
                ),
                "usage": {
                    "input_tokens": 1700,
                    "output_tokens": 110,
                    "elapsed_ms": 8000,
                    "cost_microusd": None,
                },
            },
        }

        report = arena.resolve_provider_results(results)

        audit = report["epochs"][0]["provider_audit"]
        self.assertEqual(audit["status"], "complete")
        self.assertEqual(audit["budget"], briefing["decision_budget"])
        self.assertEqual(
            audit["records"]["15"]["assignment"]["model"],
            "opencode-go/deepseek-v4.1-flash",
        )
        self.assertEqual(audit["total_usage"]["input_tokens"], 3500)
        self.assertIsNone(audit["total_usage"]["cost_microusd"])

        resolved = subprocess.run(
            [
                sys.executable,
                "-m",
                "warband_agentic.faction_arena_cli",
                "resolve-providers",
            ],
            input=json.dumps({str(key): value for key, value in results.items()}),
            check=True,
            capture_output=True,
            text=True,
        )
        cli_report = json.loads(resolved.stdout)
        self.assertEqual(
            cli_report["epochs"][0]["provider_audit"]["audit_sha256"],
            audit["audit_sha256"],
        )

    def test_over_budget_provider_responses_fail_closed_without_world_actions(self):
        arena = build_deterministic_faction_arena()
        briefing = arena.briefing()
        results = {}
        for faction_id, provider, model, input_tokens, output_tokens in (
            (15, "pi", "opencode-go/deepseek-v4.1-flash", 24_834, 712),
            (16, "codex", "gpt-6-luna", 20_222, 73),
        ):
            results[faction_id] = {
                "assignment": {
                    "provider": provider,
                    "model": model,
                    "settings": {"tools_used": False},
                },
                "response": decision_for(
                    briefing["factions"][str(faction_id)],
                    "defend",
                    f"providers:faction:{faction_id}:defend",
                ),
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "elapsed_ms": 8000,
                    "cost_microusd": None,
                },
            }

        report = arena.resolve_provider_results(results)

        epoch = report["epochs"][0]
        audit = epoch["provider_audit"]
        self.assertEqual(audit["records"]["15"]["status"], "budget-exceeded")
        self.assertEqual(audit["records"]["16"]["status"], "budget-exceeded")
        self.assertIn("output token budget", audit["records"]["15"]["detail"])
        self.assertNotIn("output token budget", audit["records"]["16"]["detail"])
        self.assertFalse(epoch["transcript"]["decision_records"]["15"]["accepted"])
        self.assertFalse(epoch["transcript"]["decision_records"]["16"]["accepted"])
        final = epoch["metrics"]["factions"]
        self.assertEqual(
            {item["key"]: item["value"] for item in final["15"]},
            {"military_strength": 100, "settlements": 1, "surviving": True},
        )
        self.assertEqual(
            {item["key"]: item["value"] for item in final["16"]},
            {"military_strength": 100, "settlements": 1, "surviving": True},
        )


if __name__ == "__main__":
    unittest.main()
