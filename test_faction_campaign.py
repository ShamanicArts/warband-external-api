import json
import subprocess
import sys
import unittest

from warband_agentic.faction_arena import build_deterministic_faction_campaign


def decision_for(task, action, request_id):
    affordance = next(
        item
        for item in task["turn"]["affordances"]
        if item["parameters"]["properties"]["action"]["const"] == action
    )
    return {
        "request_id": request_id,
        "affordance_token": affordance["token"],
        "arguments": {
            name: schema["const"]
            for name, schema in affordance["parameters"]["properties"].items()
        },
        "expected_revision": task["turn"]["observation"]["context"]["revision"],
    }


def fact_map(task):
    return {fact["key"]: fact["value"] for fact in task["turn"]["observation"]["facts"]}


class DeterministicFactionCampaignTests(unittest.TestCase):
    def test_submit_opens_a_fresh_role_filtered_turn_over_persistent_state(self):
        campaign = build_deterministic_faction_campaign(epoch_count=2)
        first = campaign.briefing()
        first_tokens = {
            faction_id: {
                item["token"]
                for item in first["factions"][faction_id]["turn"]["affordances"]
            }
            for faction_id in ("15", "16")
        }

        step = campaign.submit(
            {
                15: decision_for(
                    first["factions"]["15"], "attack", "epoch-1:swadia:attack"
                ),
                16: decision_for(
                    first["factions"]["16"], "defend", "epoch-1:vaegirs:defend"
                ),
            }
        )

        self.assertEqual(step["state"], "awaiting-decisions")
        self.assertEqual(step["completed_epochs"], 1)
        second = step["briefing"]
        self.assertEqual(second["epoch_number"], 2)
        for faction_id in ("15", "16"):
            context = second["factions"][faction_id]["turn"]["observation"]["context"]
            self.assertEqual(context["revision"], 2)
            self.assertEqual(context["game_time"], 101)
            second_tokens = {
                item["token"]
                for item in second["factions"][faction_id]["turn"]["affordances"]
            }
            self.assertTrue(first_tokens[faction_id].isdisjoint(second_tokens))

        swadia = fact_map(second["factions"]["15"])
        vaegirs = fact_map(second["factions"]["16"])
        self.assertEqual(swadia["faction.15.military_strength"], 90)
        self.assertEqual(vaegirs["faction.16.military_strength"], 95)
        self.assertEqual(
            swadia["public.previous_actions"], {"15": "attack", "16": "defend"}
        )
        self.assertNotIn("faction.16.military_strength", swadia)
        self.assertNotIn("faction.15.military_strength", vaegirs)

    def test_three_epoch_strategy_produces_one_canonical_campaign_report(self):
        campaign = build_deterministic_faction_campaign(epoch_count=3)
        choices = (
            ("attack", "defend"),
            ("recruit", "attack"),
            ("attack", "recruit"),
        )

        for epoch_number, (swadia_action, vaegirs_action) in enumerate(choices, 1):
            briefing = campaign.briefing()
            step = campaign.submit(
                {
                    15: decision_for(
                        briefing["factions"]["15"],
                        swadia_action,
                        f"epoch-{epoch_number}:swadia:{swadia_action}",
                    ),
                    16: decision_for(
                        briefing["factions"]["16"],
                        vaegirs_action,
                        f"epoch-{epoch_number}:vaegirs:{vaegirs_action}",
                    ),
                }
            )
            expected_state = (
                "complete" if epoch_number == len(choices) else "awaiting-decisions"
            )
            self.assertEqual(step["state"], expected_state)

        report = step["report"]
        self.assertEqual(report, campaign.report())
        self.assertEqual(report["epoch_count"], 3)
        self.assertEqual(
            [epoch["transcript"]["campaign_game_time"] for epoch in report["epochs"]],
            [100, 101, 102],
        )
        self.assertEqual(
            [epoch["metrics"]["game_time"] for epoch in report["epochs"]],
            [101, 102, 103],
        )
        final = report["epochs"][-1]["metrics"]["factions"]
        self.assertEqual(
            {item["key"]: item["value"] for item in final["15"]},
            {"military_strength": 75, "settlements": 1, "surviving": True},
        )
        self.assertEqual(
            {item["key"]: item["value"] for item in final["16"]},
            {"military_strength": 80, "settlements": 1, "surviving": True},
        )
        self.assertEqual(report["scorecard"]["ranking"], [16, 15])
        self.assertEqual(report["scorecard"]["factions"]["15"]["total_points"], -5.0)
        self.assertEqual(report["scorecard"]["factions"]["16"]["total_points"], -2.0)
        with self.assertRaisesRegex(RuntimeError, "complete"):
            campaign.briefing()
        with self.assertRaisesRegex(RuntimeError, "complete"):
            campaign.submit({})

    def test_previous_epoch_affordance_is_audited_as_rejected_without_action(self):
        campaign = build_deterministic_faction_campaign(epoch_count=2)
        first = campaign.briefing()
        first_swadia = decision_for(
            first["factions"]["15"], "attack", "epoch-1:swadia:attack"
        )
        campaign.submit(
            {
                15: first_swadia,
                16: decision_for(
                    first["factions"]["16"], "defend", "epoch-1:vaegirs:defend"
                ),
            }
        )
        second = campaign.briefing()

        stale_swadia = {
            **first_swadia,
            "request_id": "epoch-2:swadia:stale-token",
            "expected_revision": 2,
        }
        step = campaign.submit(
            {
                15: stale_swadia,
                16: decision_for(
                    second["factions"]["16"],
                    "recruit",
                    "epoch-2:vaegirs:recruit",
                ),
            }
        )

        stale_record = step["report"]["epochs"][1]["transcript"]["decision_records"][
            "15"
        ]
        self.assertFalse(stale_record["accepted"])
        self.assertEqual(stale_record["error_type"], "AgentConflict")
        self.assertIn("active turn", stale_record["error"])
        self.assertEqual(campaign.world.previous_actions, {15: "idle", 16: "recruit"})

    def test_cli_campaign_stream_emits_each_private_turn_then_final_report(self):
        decisions = (
            {
                "15": {
                    "request_id": "stream:epoch-1:swadia:attack",
                    "affordance_token": "arena-f15-token-1",
                    "arguments": {"action": "attack", "target_id": 1},
                    "expected_revision": 1,
                },
                "16": {
                    "request_id": "stream:epoch-1:vaegirs:defend",
                    "affordance_token": "arena-f16-token-2",
                    "arguments": {"action": "defend", "target_id": 1},
                    "expected_revision": 1,
                },
            },
            {
                "15": {
                    "request_id": "stream:epoch-2:swadia:recruit",
                    "affordance_token": "arena-f15-token-6",
                    "arguments": {"action": "recruit", "target_id": 500},
                    "expected_revision": 2,
                },
                "16": {
                    "request_id": "stream:epoch-2:vaegirs:attack",
                    "affordance_token": "arena-f16-token-4",
                    "arguments": {"action": "attack", "target_id": 2},
                    "expected_revision": 2,
                },
            },
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "warband_agentic.faction_arena_cli",
                "campaign",
                "--epochs",
                "2",
            ],
            input="".join(json.dumps(item) + "\n" for item in decisions),
            check=True,
            capture_output=True,
            text=True,
        )

        events = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(
            [event["type"] for event in events], ["turn", "turn", "report"]
        )
        self.assertEqual(events[0]["briefing"]["epoch_number"], 1)
        self.assertEqual(events[1]["briefing"]["epoch_number"], 2)
        self.assertEqual(events[2]["report"]["epoch_count"], 2)
        self.assertEqual(events[2]["report"]["scorecard"]["ranking"], [16, 15])

    def test_each_epoch_can_bind_equal_budget_provider_receipts(self):
        campaign = build_deterministic_faction_campaign(epoch_count=2)

        for epoch_number in (1, 2):
            briefing = campaign.briefing()
            results = {}
            for faction_id, action, provider, model in (
                (15, "defend", "pi", "opencode-go/deepseek-v4.1-flash"),
                (16, "defend", "codex", "gpt-6-luna"),
            ):
                results[faction_id] = {
                    "assignment": {
                        "provider": provider,
                        "model": model,
                        "settings": {"reasoning_level": "low"},
                    },
                    "response": decision_for(
                        briefing["factions"][str(faction_id)],
                        action,
                        f"providers:epoch-{epoch_number}:faction-{faction_id}",
                    ),
                    "usage": {
                        "input_tokens": 1200,
                        "output_tokens": 80,
                        "elapsed_ms": 2000,
                        "cost_microusd": None,
                    },
                }
            step = campaign.submit_provider_results(results)

        audits = [epoch["provider_audit"] for epoch in step["report"]["epochs"]]
        self.assertEqual(
            [audit["batch_id"] for audit in audits],
            ["arena:campaign:batch:1", "arena:campaign:batch:2"],
        )
        self.assertEqual(
            [audit["total_usage"]["input_tokens"] for audit in audits],
            [2400, 2400],
        )
        self.assertTrue(
            all(
                record["status"] == "success"
                for audit in audits
                for record in audit["records"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
