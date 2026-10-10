import json
import unittest
from dataclasses import replace

from warband_agentic import (
    CONTRACT_VERSION,
    ActionOutcome,
    ActionState,
    ActionSubmission,
    ActorKind,
    ActorRef,
    Affordance,
    AuthorityClass,
    ContextKind,
    ContextRef,
    ControlLease,
    Evidence,
    EvidenceLevel,
    Fact,
    FactSource,
    GameEvent,
    LeaseMode,
    ObservationEnvelope,
    RiskClass,
    RoleGrant,
    RoleId,
    contract_manifest,
    to_wire,
)


class AgenticContractTests(unittest.TestCase):
    def setUp(self):
        self.actor = ActorRef("agent:13", ActorKind.AGENT, 13)
        self.context = ContextRef(ContextKind.DIALOGUE, "scene:376", 12, 3, 90)

    def test_observation_distinguishes_fact_sources_and_serializes(self):
        observation = ObservationEnvelope(
            "obs:12",
            self.actor,
            RoleId.NPC_SELF,
            self.context,
            (
                Fact(
                    "dialogue.current",
                    {"entry_id": 2469, "participants": [13, 15]},
                    FactSource.ENGINE_OBSERVED,
                    12,
                ),
                Fact(
                    "memory.last_topic",
                    "supplies",
                    FactSource.APPLICATION_MEMORY,
                    11,
                ),
            ),
            ("factions.hidden_relations",),
            1000,
        )
        wire = to_wire(observation)
        self.assertEqual(wire["schema"], CONTRACT_VERSION)
        self.assertEqual(wire["role"], "npc.self")
        self.assertEqual(wire["facts"][0]["source"], "engine-observed")
        self.assertEqual(wire["facts"][0]["value"]["participants"], [13, 15])
        json.dumps(wire)

    def test_payloads_are_copied_frozen_and_json_only(self):
        source = {"choices": [1, {"id": 2}]}
        fact = Fact("dialogue.choices", source, FactSource.ENGINE_OBSERVED, 12)
        source["choices"].append(3)
        self.assertEqual(to_wire(fact.value), {"choices": [1, {"id": 2}]})
        with self.assertRaises(TypeError):
            fact.value["choices"] = ()
        with self.assertRaisesRegex(TypeError, "non-JSON"):
            Fact("bad", {"value": object()}, FactSource.INFERRED, 12)
        with self.assertRaisesRegex(ValueError, "non-finite"):
            Fact("bad", float("nan"), FactSource.INFERRED, 12)

    def test_affordance_carries_authority_risk_expiry_and_evidence(self):
        affordance = Affordance(
            "aff:leave:3",
            "dialogue.choose",
            "Select the original Native Leave response",
            self.actor,
            (ActorRef("agent:15", ActorKind.PLAYER, 15),),
            self.context,
            AuthorityClass.ACTOR_CONTROL,
            {"type": "object", "properties": {"entry_id": {"const": 2515}}},
            RiskClass.CONSEQUENTIAL,
            False,
            "The dialogue screen will close.",
            EvidenceLevel.ENGINE_OBSERVED,
            1000,
            1500,
        )
        wire = to_wire(affordance)
        self.assertEqual(wire["context"]["revision"], 12)
        self.assertEqual(wire["parameters"]["properties"]["entry_id"]["const"], 2515)
        with self.assertRaisesRegex(ValueError, "expire"):
            replace(affordance, expires_at_ms=1000)

    def test_submission_and_outcome_keep_acknowledgement_distinct_from_observation(
        self,
    ):
        submission = ActionSubmission(
            "act:1", "aff:leave:3", self.actor, {"entry_id": 2515}, 12, 1100
        )
        evidence = Evidence(
            EvidenceLevel.ENGINE_ACKNOWLEDGED,
            "Warband callback",
            "Game accepted command 42",
        )
        outcome = ActionOutcome(
            submission.action_id,
            ActionState.ACKNOWLEDGED,
            self.context,
            None,
            {"result": 0},
            (),
            (evidence,),
            None,
            1200,
        )
        self.assertEqual(to_wire(outcome)["state"], "acknowledged")
        self.assertLess(
            evidence.level.rank,
            EvidenceLevel.ENGINE_OBSERVED.rank,
        )

    def test_game_event_has_order_context_cause_and_subjects(self):
        event = GameEvent(
            2,
            "dialogue.player-choice",
            self.context,
            (self.actor,),
            {"entry_id": 2515, "state": "close_window"},
            Evidence(
                EvidenceLevel.ENGINE_OBSERVED,
                "Warband conversation consequence",
                "Catalog-validated sequence 2",
                2,
            ),
            1300,
            "act:1",
        )
        self.assertEqual(to_wire(event)["evidence"]["event_sequence"], 2)

    def test_role_grants_and_leases_are_explicit_and_expiring(self):
        grant = RoleGrant(
            "grant:elder",
            RoleId.NPC_SELF,
            self.actor,
            (AuthorityClass.OBSERVE, AuthorityClass.ACTOR_CONTROL),
            "npc.self",
            ("dialogue", "movement:self"),
            1000,
            2000,
        )
        lease = ControlLease(
            "lease:elder",
            ActorRef("controller:luna", ActorKind.SYSTEM),
            self.actor,
            ("dialogue",),
            LeaseMode.EXCLUSIVE,
            4,
            1100,
            1500,
        )
        self.assertEqual(to_wire(grant)["authorities"][1], "actor-control")
        self.assertEqual(to_wire(lease)["mode"], "exclusive")

    def test_contract_manifest_is_transport_neutral(self):
        manifest = contract_manifest()
        json.dumps(manifest)
        self.assertEqual(manifest["schema"], CONTRACT_VERSION)
        self.assertIn("faction.sovereign", manifest["roles"])
        self.assertNotIn("mcp", json.dumps(manifest).lower())
        self.assertNotIn("http", json.dumps(manifest).lower())


if __name__ == "__main__":
    unittest.main()
