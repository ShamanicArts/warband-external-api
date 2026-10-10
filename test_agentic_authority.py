import unittest

from warband_agentic import (
    ActorKind,
    ActorRef,
    AuthorityClass,
    ContextKind,
    ContextRef,
    Fact,
    FactSource,
    LeaseBook,
    LeaseMode,
    ObservationEnvelope,
    ObservationFilter,
    PerceptionPolicy,
    RoleGrant,
    RoleId,
    default_perception_policies,
    to_wire,
)


class LeaseBookTests(unittest.TestCase):
    def setUp(self):
        ids = iter(("lease:1", "lease:2", "lease:3", "lease:4"))
        self.book = LeaseBook(lambda: next(ids))
        self.target = ActorRef("agent:13", ActorKind.AGENT, 13)
        self.alice = ActorRef("controller:alice", ActorKind.SYSTEM)
        self.bob = ActorRef("controller:bob", ActorKind.SYSTEM)

    def test_exclusive_lease_reports_owner_and_expiry_on_conflict(self):
        lease = self.book.acquire(
            self.alice,
            self.target,
            ("dialogue",),
            LeaseMode.EXCLUSIVE,
            1000,
            1500,
        )
        self.assertEqual(lease.generation, 1)
        with self.assertRaisesRegex(ValueError, "controller:alice until 1500"):
            self.book.acquire(
                self.bob,
                self.target,
                ("dialogue",),
                LeaseMode.SHARED,
                1100,
                1400,
            )

    def test_shared_leases_coexist_but_block_later_exclusive(self):
        first = self.book.acquire(
            self.alice,
            self.target,
            ("dialogue",),
            LeaseMode.SHARED,
            1000,
            1500,
        )
        second = self.book.acquire(
            self.bob,
            self.target,
            ("dialogue",),
            LeaseMode.SHARED,
            1000,
            1500,
        )
        self.assertEqual((first.generation, second.generation), (1, 2))
        with self.assertRaisesRegex(ValueError, "Control conflict"):
            self.book.acquire(
                ActorRef("controller:third", ActorKind.SYSTEM),
                self.target,
                ("dialogue",),
                LeaseMode.EXCLUSIVE,
                1100,
                1400,
            )

    def test_disjoint_domains_do_not_conflict_and_wildcard_does(self):
        self.book.acquire(
            self.alice,
            self.target,
            ("movement",),
            LeaseMode.EXCLUSIVE,
            1000,
            1500,
        )
        lease = self.book.acquire(
            self.bob,
            self.target,
            ("dialogue",),
            LeaseMode.EXCLUSIVE,
            1000,
            1500,
        )
        self.assertEqual(lease.generation, 2)
        with self.assertRaisesRegex(ValueError, "Control conflict"):
            self.book.acquire(
                ActorRef("controller:third", ActorKind.SYSTEM),
                self.target,
                ("*",),
                LeaseMode.EXCLUSIVE,
                1100,
                1400,
            )

    def test_expiry_release_and_require_use_trusted_book_state(self):
        lease = self.book.acquire(
            self.alice,
            self.target,
            ("dialogue",),
            LeaseMode.EXCLUSIVE,
            1000,
            1200,
        )
        self.assertEqual(
            self.book.require(
                lease.lease_id, self.alice, self.target, "dialogue", 1100
            ),
            lease,
        )
        self.assertEqual(self.book.active(self.target, "dialogue", 1200), ())
        with self.assertRaisesRegex(ValueError, "Unknown or expired"):
            self.book.require(lease.lease_id, self.alice, self.target, "dialogue", 1200)
        replacement = self.book.acquire(
            self.bob,
            self.target,
            ("dialogue",),
            LeaseMode.EXCLUSIVE,
            1200,
            1500,
        )
        self.assertEqual(replacement.generation, 2)
        with self.assertRaisesRegex(ValueError, "controlling actor"):
            self.book.release(replacement.lease_id, self.alice)
        self.assertEqual(self.book.release(replacement.lease_id, self.bob), replacement)


class ObservationFilterTests(unittest.TestCase):
    def setUp(self):
        self.filter = ObservationFilter()
        for policy in default_perception_policies():
            self.filter.register(policy)
        self.system = ActorRef("system:canonical", ActorKind.SYSTEM)
        self.npc = ActorRef("agent:13", ActorKind.AGENT, 13)
        self.context = ContextRef(ContextKind.DIALOGUE, "scene:376", 12, 3, 90)
        self.canonical = ObservationEnvelope(
            "canonical:12",
            self.system,
            RoleId.OPERATOR_FULL,
            self.context,
            (
                Fact("self.health", 72, FactSource.ENGINE_OBSERVED, 12),
                Fact("dialogue.entry_id", 2469, FactSource.ENGINE_OBSERVED, 12),
                Fact("factions.secret_plan", "raid", FactSource.INFERRED, 12),
                Fact("memory.last_topic", "grain", FactSource.APPLICATION_MEMORY, 11),
                Fact("public.time_of_day", "dusk", FactSource.ENGINE_OBSERVED, 12),
            ),
            ("unavailable.weather",),
            1000,
        )
        self.grant = RoleGrant(
            "grant:npc",
            RoleId.NPC_SELF,
            self.npc,
            (AuthorityClass.OBSERVE,),
            "npc.self",
            ("dialogue",),
            1000,
            2000,
        )

    def test_npc_policy_filters_facts_and_reports_category_not_secret_key(self):
        result = self.filter.apply(self.canonical, self.grant, "npc:12", 1100)
        wire = to_wire(result)
        self.assertEqual(wire["actor"]["runtime_id"], "agent:13")
        self.assertEqual(wire["role"], "npc.self")
        self.assertEqual(
            [fact["key"] for fact in wire["facts"]],
            [
                "self.health",
                "dialogue.entry_id",
                "memory.last_topic",
                "public.time_of_day",
            ],
        )
        self.assertIn("factions", wire["omitted"])
        self.assertNotIn("factions.secret_plan", wire["omitted"])

    def test_operator_and_test_director_policies_receive_all_canonical_facts(self):
        for role, policy in (
            (RoleId.OPERATOR_FULL, "operator.full"),
            (RoleId.TEST_DIRECTOR, "test.director"),
        ):
            grant = RoleGrant(
                f"grant:{role.value}",
                role,
                ActorRef(f"actor:{role.value}", ActorKind.SYSTEM),
                (AuthorityClass.OBSERVE,),
                policy,
                ("*",),
                1000,
                2000,
            )
            result = self.filter.apply(self.canonical, grant, f"obs:{role.value}", 1100)
            self.assertEqual(result.facts, self.canonical.facts)

    def test_policy_role_context_expiry_and_duplicate_registration_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.filter.register(default_perception_policies()[2])
        wrong_role = RoleGrant(
            "wrong",
            RoleId.PLAYER_STRATEGIC,
            self.npc,
            (AuthorityClass.OBSERVE,),
            "npc.self",
            ("dialogue",),
            1000,
            2000,
        )
        with self.assertRaisesRegex(ValueError, "role does not match"):
            self.filter.apply(self.canonical, wrong_role, "wrong:1", 1100)
        with self.assertRaisesRegex(ValueError, "not active"):
            self.filter.apply(self.canonical, self.grant, "late:1", 2000)
        mission_only = PerceptionPolicy(
            "npc.mission-only",
            RoleId.NPC_SELF,
            ("self",),
            tuple(FactSource),
            (ContextKind.MISSION,),
        )
        self.filter.register(mission_only)
        mission_grant = RoleGrant(
            "mission",
            RoleId.NPC_SELF,
            self.npc,
            (AuthorityClass.OBSERVE,),
            mission_only.policy_id,
            ("movement",),
            1000,
            2000,
        )
        with self.assertRaisesRegex(ValueError, "invalid in this context"):
            self.filter.apply(self.canonical, mission_grant, "mission:1", 1100)

    def test_fact_source_restrictions_remain_independent_of_key_prefix(self):
        policy = PerceptionPolicy(
            "npc.engine-only",
            RoleId.NPC_SELF,
            ("*",),
            (FactSource.ENGINE_OBSERVED,),
            tuple(ContextKind),
        )
        self.filter.register(policy)
        grant = RoleGrant(
            "engine-only",
            RoleId.NPC_SELF,
            self.npc,
            (AuthorityClass.OBSERVE,),
            policy.policy_id,
            ("dialogue",),
            1000,
            2000,
        )
        result = self.filter.apply(self.canonical, grant, "engine:1", 1100)
        self.assertTrue(
            all(fact.source is FactSource.ENGINE_OBSERVED for fact in result.facts)
        )


if __name__ == "__main__":
    unittest.main()
