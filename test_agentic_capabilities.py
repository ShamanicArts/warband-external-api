import unittest

from warband_agentic import (
    ActionSubmission,
    ActorKind,
    ActorRef,
    AuthorityClass,
    CapabilityDefinition,
    CapabilityRegistry,
    ContextKind,
    ContextRef,
    ControlLease,
    EvidenceLevel,
    LeaseMode,
    RiskClass,
    RoleGrant,
    RoleId,
    to_wire,
)


def definition(
    name="dialogue.choose",
    authority=AuthorityClass.ACTOR_CONTROL,
    domain="dialogue",
    contexts=(ContextKind.DIALOGUE,),
    requires_lease=True,
):
    return CapabilityDefinition(
        name,
        "Choose one currently offered original response",
        domain,
        authority,
        contexts,
        {
            "type": "object",
            "properties": {
                "entry_id": {"type": "integer", "minimum": 0},
                "confirmation": {"enum": ["accept"]},
            },
            "required": ["entry_id"],
            "additionalProperties": False,
        },
        RiskClass.CONSEQUENTIAL,
        False,
        "The original Native consequence will run.",
        EvidenceLevel.ENGINE_OBSERVED,
        "native-dialogue-choice",
        requires_lease,
    )


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self):
        tokens = iter(("token:1", "token:2", "token:3", "token:4"))
        self.registry = CapabilityRegistry(lambda: next(tokens))
        self.registry.register(definition())
        self.actor = ActorRef("controller:elder", ActorKind.SYSTEM)
        self.elder = ActorRef("agent:13", ActorKind.AGENT, 13)
        self.context = ContextRef(ContextKind.DIALOGUE, "scene:376", 12, 3, 90)
        self.grant = RoleGrant(
            "grant:elder",
            RoleId.NPC_SELF,
            self.actor,
            (AuthorityClass.OBSERVE, AuthorityClass.ACTOR_CONTROL),
            "npc.self",
            ("dialogue",),
            1000,
            2000,
        )
        self.lease = ControlLease(
            "lease:elder",
            self.actor,
            self.elder,
            ("dialogue",),
            LeaseMode.EXCLUSIVE,
            1,
            1000,
            1600,
        )

    def issue(self, expires=1500):
        return self.registry.issue(
            "dialogue.choose",
            self.actor,
            (self.elder,),
            self.context,
            self.grant,
            1100,
            expires,
        )

    def submit(self, affordance, **changes):
        values = {
            "action_id": "action:1",
            "affordance_token": affordance.token,
            "actor": self.actor,
            "arguments": {"entry_id": 2515},
            "expected_revision": 12,
            "submitted_at_ms": 1200,
        }
        values.update(changes)
        return ActionSubmission(**values)

    def test_discovery_is_filtered_by_grant_domain_authority_and_context(self):
        self.registry.register(
            definition(
                "diplomacy.declare-war",
                AuthorityClass.FACTION_CONTROL,
                "diplomacy",
                (ContextKind.CAMPAIGN,),
                False,
            )
        )
        discovered = self.registry.discover(self.grant, self.context, 1100)
        self.assertEqual([item["name"] for item in discovered], ["dialogue.choose"])
        self.assertNotIn("token", discovered[0])
        self.assertNotIn("handler_id", discovered[0])

    def test_duplicate_registration_and_token_collision_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.registry.register(definition())
        self.issue()
        collision_registry = CapabilityRegistry(lambda: "token:1")
        collision_registry.register(definition())
        collision_registry.issue(
            "dialogue.choose",
            self.actor,
            (self.elder,),
            self.context,
            self.grant,
            1100,
            1500,
        )
        with self.assertRaisesRegex(ValueError, "collision"):
            collision_registry.issue(
                "dialogue.choose",
                self.actor,
                (self.elder,),
                self.context,
                self.grant,
                1100,
                1500,
            )

    def test_issued_affordance_is_bound_and_agent_serializable(self):
        affordance = self.issue()
        wire = to_wire(affordance)
        self.assertEqual(wire["token"], "token:1")
        self.assertEqual(wire["actor"]["runtime_id"], "controller:elder")
        self.assertEqual(wire["targets"][0]["runtime_id"], "agent:13")
        self.assertEqual(wire["context"]["revision"], 12)
        self.assertEqual(wire["required_evidence"], "engine-observed")

    def test_consume_validates_schema_lease_and_is_single_use(self):
        affordance = self.issue()
        action = self.registry.consume(
            self.submit(affordance), self.context, self.grant, 1200, self.lease
        )
        self.assertEqual(action.capability.handler_id, "native-dialogue-choice")
        with self.assertRaisesRegex(ValueError, "already consumed"):
            self.registry.consume(
                self.submit(affordance, action_id="action:2"),
                self.context,
                self.grant,
                1201,
                self.lease,
            )

    def test_stale_changed_expired_and_wrong_actor_submissions_are_rejected(self):
        cases = (
            (
                {"expected_revision": 11},
                self.context,
                1200,
                self.grant,
                self.lease,
                "stale",
            ),
            (
                {},
                ContextRef(ContextKind.DIALOGUE, "scene:376", 13, 3, 91),
                1200,
                self.grant,
                self.lease,
                "context changed",
            ),
            ({}, self.context, 1500, self.grant, self.lease, "expired"),
            (
                {"actor": ActorRef("controller:other", ActorKind.SYSTEM)},
                self.context,
                1200,
                self.grant,
                self.lease,
                "different actor",
            ),
            (
                {"submitted_at_ms": 1099},
                self.context,
                1200,
                self.grant,
                self.lease,
                "timestamp",
            ),
            (
                {"submitted_at_ms": 1201},
                self.context,
                1200,
                self.grant,
                self.lease,
                "timestamp",
            ),
        )
        for changes, context, now, grant, lease, message in cases:
            registry = CapabilityRegistry(lambda: "case-token")
            registry.register(definition())
            affordance = registry.issue(
                "dialogue.choose",
                self.actor,
                (self.elder,),
                self.context,
                self.grant,
                1100,
                1500,
            )
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValueError, message),
            ):
                registry.consume(
                    self.submit(affordance, **changes), context, grant, now, lease
                )

    def test_parameter_schema_rejects_missing_extra_type_enum_and_range(self):
        invalid_arguments = (
            ({}, "missing"),
            ({"entry_id": 2515, "extra": 1}, "unexpected"),
            ({"entry_id": "2515"}, "integer"),
            ({"entry_id": -1}, "minimum"),
            ({"entry_id": 2515, "confirmation": "maybe"}, "allowed"),
        )
        for index, (arguments, message) in enumerate(invalid_arguments):
            registry = CapabilityRegistry(lambda: f"schema:{index}")
            registry.register(definition())
            affordance = registry.issue(
                "dialogue.choose",
                self.actor,
                (self.elder,),
                self.context,
                self.grant,
                1100,
                1500,
            )
            with (
                self.subTest(arguments=arguments),
                self.assertRaisesRegex(ValueError, message),
            ):
                registry.consume(
                    self.submit(affordance, arguments=arguments),
                    self.context,
                    self.grant,
                    1200,
                    self.lease,
                )

    def test_grant_and_lease_scope_bound_affordance_lifetime(self):
        with self.assertRaisesRegex(ValueError, "outlive"):
            self.issue(expires=2001)
        expired_grant = RoleGrant(
            "expired",
            RoleId.NPC_SELF,
            self.actor,
            (AuthorityClass.ACTOR_CONTROL,),
            "npc.self",
            ("dialogue",),
            1,
            1000,
        )
        with self.assertRaisesRegex(ValueError, "expired"):
            self.registry.issue(
                "dialogue.choose",
                self.actor,
                (self.elder,),
                self.context,
                expired_grant,
                1100,
                1200,
            )
        affordance = self.issue()
        wrong_target = ControlLease(
            "wrong",
            self.actor,
            ActorRef("agent:99", ActorKind.AGENT, 99),
            ("dialogue",),
            LeaseMode.EXCLUSIVE,
            1,
            1000,
            1400,
        )
        with self.assertRaisesRegex(ValueError, "outside"):
            self.registry.consume(
                self.submit(affordance),
                self.context,
                self.grant,
                1200,
                wrong_target,
            )

    def test_definition_refuses_ambiguous_parameter_schema(self):
        bad = definition()
        values = {
            field: getattr(bad, field)
            for field in bad.__dataclass_fields__
            if field != "parameters"
        }
        with self.assertRaisesRegex(ValueError, "object schema"):
            CapabilityDefinition(parameters={"type": "string"}, **values)
        with self.assertRaisesRegex(ValueError, "undeclared"):
            CapabilityDefinition(
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": ["missing"],
                },
                **values,
            )


if __name__ == "__main__":
    unittest.main()
