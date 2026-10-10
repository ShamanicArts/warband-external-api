import unittest

from warband_agentic import (
    ActionSubmission,
    ActorKind,
    ActorRef,
    AuthorityClass,
    CapabilityRegistry,
    EvidenceLevel,
    FactSource,
    LeaseBook,
    LeaseMode,
    RoleGrant,
    RoleId,
    canonical_observation_from_snapshot,
    context_from_snapshot,
    dialogue_event_from_bridge,
    issue_menu_affordances,
    menu_operation_from_validated,
    register_menu_capability,
    to_wire,
)


def mission_snapshot():
    return {
        "connected": True,
        "protocol": 2,
        "context": "mission",
        "player_gold": 355,
        "player_troop_id": 0,
        "player_hit_points": 49,
        "position": {"x": 152.45, "y": 204.03, "z": 8.67},
        "clock": 90,
        "scene_id": 376,
        "mission_session": 3,
        "player_agent_id": 15,
        "mission_template": "village_center",
        "mission_flags": 0,
        "dialogue_active": True,
        "player_is_captive": False,
        "menu_id": None,
        "menu_session": None,
        "menu_name": None,
        "native_context": {"last_town_id": 93, "last_encounter_party_id": 93},
        "age_seconds": 0.02,
        "source": "Warband engine scripts",
    }


def menu_snapshot():
    return {
        **mission_snapshot(),
        "context": "menu",
        "scene_id": None,
        "mission_session": -1,
        "player_agent_id": -1,
        "mission_template": None,
        "dialogue_active": False,
        "menu_id": 23,
        "menu_session": 10,
        "menu_name": "camp",
    }


class SnapshotAdapterTests(unittest.TestCase):
    def test_engine_snapshot_becomes_source_labelled_canonical_observation(self):
        observation = canonical_observation_from_snapshot(
            mission_snapshot(), 12, "obs:12", 1000
        )
        wire = to_wire(observation)
        self.assertEqual(wire["context"]["kind"], "mission")
        self.assertEqual(wire["context"]["scope_id"], "scene:376")
        self.assertEqual(wire["context"]["session_id"], 3)
        facts = {fact.key: fact for fact in observation.facts}
        self.assertEqual(facts["player.gold"].value, 355)
        self.assertIs(facts["player.gold"].source, FactSource.ENGINE_OBSERVED)
        self.assertIs(facts["mission.template"].source, FactSource.DEFINITION_METADATA)
        self.assertNotIn("age_seconds", str(wire))
        self.assertNotIn("Warband engine scripts", str(wire))

    def test_adapter_refuses_disconnected_old_or_unknown_context(self):
        for change in (
            {"connected": False},
            {"protocol": 1},
            {"context": "desktop"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                context_from_snapshot({**mission_snapshot(), **change}, 1)


class DialogueEventAdapterTests(unittest.TestCase):
    def test_committed_native_row_becomes_engine_observed_semantic_event(self):
        row = {
            "sequence": 2,
            "source": "Warband conversation consequence",
            "event": "player_choice",
            "entry_id": 2515,
            "symbol": "village_elder_talk:close_window",
            "text_template": "[Leave]",
            "input_state_id": 1203,
            "input_state": "village_elder_talk",
            "output_state_id": 6,
            "output_state": "close_window",
            "speaker": 69631,
            "conversation_troop_id": 691,
            "conversation_agent_id": 13,
            "mission_session": 3,
            "received_at": 1791610931.5346751,
        }
        event = dialogue_event_from_bridge(row, 376, 13, 42)
        wire = to_wire(event)
        self.assertEqual(wire["sequence"], 42)
        self.assertEqual(wire["event_type"], "dialogue.player-choice")
        self.assertEqual(wire["context"]["scope_id"], "scene:376")
        self.assertEqual(wire["payload"]["entry_id"], 2515)
        self.assertEqual(wire["payload"]["source_sequence"], 2)
        self.assertEqual(wire["evidence"]["level"], "engine-observed")
        self.assertEqual(
            [subject["runtime_id"] for subject in wire["subjects"]],
            ["agent:13", "troop:691"],
        )


class MenuActionAdapterTests(unittest.TestCase):
    def setUp(self):
        tokens = iter(("menu:0", "menu:1"))
        self.book = LeaseBook(lambda: "lease:player-menu")
        self.controller = ActorRef("controller:player", ActorKind.SYSTEM)
        self.player = ActorRef("player:troop:0", ActorKind.PLAYER, 0)
        self.lease = self.book.acquire(
            self.controller,
            self.player,
            ("player.menu",),
            LeaseMode.EXCLUSIVE,
            1000,
            1600,
        )
        self.registry = CapabilityRegistry(lambda: next(tokens), self.book.resolve)
        register_menu_capability(self.registry)
        self.context = context_from_snapshot(menu_snapshot(), 20)
        self.grant = RoleGrant(
            "grant:player",
            RoleId.PLAYER_STRATEGIC,
            self.controller,
            (AuthorityClass.ACTOR_CONTROL,),
            "player.strategic",
            ("player.menu",),
            1000,
            2000,
        )
        self.options = {
            "state": menu_snapshot(),
            "actions": [
                {
                    "id": 0,
                    "menu_id": 23,
                    "menu": "camp",
                    "option": "camp_action",
                    "text_template": "Take an action.",
                },
                {
                    "id": 1,
                    "menu_id": 23,
                    "menu": "camp",
                    "option": "resume_travelling",
                    "text_template": "Resume travelling.",
                },
            ],
            "availability": "Candidates only; Native conditions checked on selection.",
        }

    def test_current_menu_candidates_become_exact_session_attempt_affordances(self):
        affordances = issue_menu_affordances(
            self.registry,
            self.options,
            self.controller,
            self.player,
            self.context,
            self.grant,
            1100,
            1500,
        )
        self.assertEqual([item.token for item in affordances], ["menu:0", "menu:1"])
        self.assertEqual(
            [
                item.parameters["properties"]["action_id"]["const"]
                for item in affordances
            ],
            [0, 1],
        )
        self.assertEqual(
            affordances[1].parameters["properties"]["action_id"]["title"],
            "Resume travelling.",
        )
        self.assertIs(
            affordances[0].required_evidence, EvidenceLevel.ENGINE_ACKNOWLEDGED
        )

    def test_validated_affordance_resolves_to_existing_allowlisted_operation(self):
        affordance = issue_menu_affordances(
            self.registry,
            self.options,
            self.controller,
            self.player,
            self.context,
            self.grant,
            1100,
            1500,
        )[1]
        submission = ActionSubmission(
            "action:menu:1",
            affordance.token,
            self.controller,
            {"action_id": 1},
            20,
            1200,
            self.lease.lease_id,
        )
        validated = self.registry.consume(submission, self.context, self.grant, 1200)
        self.assertEqual(
            menu_operation_from_validated(validated),
            {"operation": "select_menu", "arguments": {"action_id": 1}},
        )

    def test_candidate_and_semantic_context_must_be_the_same_menu_entry(self):
        changed = {**menu_snapshot(), "menu_session": 11}
        with self.assertRaisesRegex(ValueError, "does not match"):
            issue_menu_affordances(
                self.registry,
                {**self.options, "state": changed},
                self.controller,
                self.player,
                self.context,
                self.grant,
                1100,
                1500,
            )

        duplicate = {**self.options, "actions": [self.options["actions"][0]] * 2}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            issue_menu_affordances(
                self.registry,
                duplicate,
                self.controller,
                self.player,
                self.context,
                self.grant,
                1100,
                1500,
            )

        unsafe = {
            **self.options,
            "actions": [{**self.options["actions"][0], "condition_script": 610}],
        }
        with self.assertRaisesRegex(ValueError, "safe catalog metadata"):
            issue_menu_affordances(
                self.registry,
                unsafe,
                self.controller,
                self.player,
                self.context,
                self.grant,
                1100,
                1500,
            )


if __name__ == "__main__":
    unittest.main()
