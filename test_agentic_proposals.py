import unittest
from types import SimpleNamespace

from warband_agentic import (
    ActionOutcome,
    ActionState,
    ActorKind,
    ActorRef,
    Affordance,
    AuthorityClass,
    ContextKind,
    ContextRef,
    EvidenceLevel,
    MechanicalProposalBroker,
    MechanicalProposalState,
    RiskClass,
)


class FakeTargetSession:
    def __init__(self):
        self.context = ContextRef(ContextKind.CAMPAIGN, "campaign:world", 7, None, 90)
        self.actor = ActorRef("controller:faction:15", ActorKind.SYSTEM)
        self.target = ActorRef("party:17", ActorKind.PARTY, 17)
        self.affordance = Affordance(
            "private:affordance:defend-praven",
            "party.issue-order",
            "Defend Praven",
            self.actor,
            (self.target,),
            self.context,
            AuthorityClass.PARTY_COMMAND,
            {
                "type": "object",
                "properties": {
                    "order": {"type": "string", "const": "defend"},
                    "target_id": {"type": "integer", "const": 2},
                },
                "required": ("order", "target_id"),
                "additionalProperties": False,
            },
            RiskClass.REVERSIBLE,
            True,
            "The party will abandon its current order.",
            EvidenceLevel.ENGINE_OBSERVED,
            1000,
            2000,
        )
        self.submissions = []

    def turn(self):
        return SimpleNamespace(
            observation=SimpleNamespace(context=self.context),
            affordances=(self.affordance,),
        )

    def submit(self, request):
        self.submissions.append(request)
        return ActionOutcome(
            "action:" + request["request_id"],
            ActionState.ACCEPTED,
            self.context,
            None,
            {"status": "queued"},
            (),
            (),
            None,
            1300,
        )


class MechanicalProposalBrokerTests(unittest.TestCase):
    def setUp(self):
        self.now = 1200
        self.target = FakeTargetSession()
        self.source_context = ContextRef(
            ContextKind.MISSION, "mission:scene-42", 3, 1, 90
        )
        self.broker = MechanicalProposalBroker(
            clock_ms=lambda: self.now,
            token_factory=lambda: "proposal-option:1",
            proposal_id_factory=lambda: "proposal:1",
        )

    def offer(self):
        return self.broker.offer(
            source_session_id="village-elder",
            source_context=self.source_context,
            title="Ask the Swadian patrol to defend Praven",
            target_session_id="swadia",
            target_session=self.target,
            affordance_token=self.target.affordance.token,
            arguments={"order": "defend", "target_id": 2},
            required_acceptors=("player", "swadia-sovereign"),
        )

    def test_observed_proposal_requires_every_acceptor_before_exact_submission(self):
        option = self.offer()

        self.assertEqual(option["proposal_token"], "proposal-option:1")
        self.assertNotIn(self.target.affordance.token, str(option))
        self.assertEqual(
            self.broker.options("village-elder", self.source_context), (option,)
        )
        proposal = self.broker.commit(
            option["proposal_token"], "action:npc-turn:1", self.source_context
        )
        self.assertEqual(proposal["state"], MechanicalProposalState.PENDING.value)
        with self.assertRaisesRegex(ValueError, "not approved"):
            self.broker.execute(proposal["proposal_id"])

        pending = self.broker.decide(proposal["proposal_id"], "player", accept=True)
        self.assertEqual(pending["state"], "pending")
        approved = self.broker.decide(
            proposal["proposal_id"], "swadia-sovereign", accept=True
        )
        self.assertEqual(approved["state"], "approved")

        outcome = self.broker.execute(proposal["proposal_id"])
        self.assertIs(outcome.state, ActionState.ACCEPTED)
        self.assertEqual(
            self.target.submissions,
            [
                {
                    "request_id": "mechanical:proposal:1",
                    "affordance_token": self.target.affordance.token,
                    "arguments": {"order": "defend", "target_id": 2},
                    "expected_revision": 7,
                }
            ],
        )
        self.assertIs(self.broker.execute(proposal["proposal_id"]), outcome)
        self.assertEqual(
            self.broker.proposal(proposal["proposal_id"])["state"], "submitted"
        )

    def test_rejection_and_stale_target_never_execute(self):
        option = self.offer()
        rejected = self.broker.commit(
            option["proposal_token"], "action:npc-turn:reject", self.source_context
        )
        rejected = self.broker.decide(rejected["proposal_id"], "player", accept=False)
        self.assertEqual(rejected["state"], "rejected")
        with self.assertRaisesRegex(ValueError, "no longer accepts"):
            self.broker.decide(rejected["proposal_id"], "swadia-sovereign", accept=True)
        self.assertEqual(self.target.submissions, [])

        second_target = FakeTargetSession()
        second = MechanicalProposalBroker(
            clock_ms=lambda: self.now,
            token_factory=lambda: "proposal-option:2",
            proposal_id_factory=lambda: "proposal:2",
        )
        option = second.offer(
            source_session_id="village-elder",
            source_context=self.source_context,
            title="Defend Praven",
            target_session_id="swadia",
            target_session=second_target,
            affordance_token=second_target.affordance.token,
            arguments={"order": "defend", "target_id": 2},
            required_acceptors=("player",),
        )
        proposal = second.commit(
            option["proposal_token"], "action:npc-turn:stale", self.source_context
        )
        second.decide(proposal["proposal_id"], "player", accept=True)
        second_target.context = ContextRef(
            ContextKind.CAMPAIGN, "campaign:world", 8, None, 91
        )
        with self.assertRaisesRegex(ValueError, "became stale"):
            second.execute(proposal["proposal_id"])
        self.assertEqual(second.proposal(proposal["proposal_id"])["state"], "stale")
        self.assertEqual(second_target.submissions, [])

    def test_invalid_arguments_expiry_and_conflicting_commit_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "required value"):
            self.broker.offer(
                source_session_id="village-elder",
                source_context=self.source_context,
                title="Bad proposal",
                target_session_id="swadia",
                target_session=self.target,
                affordance_token=self.target.affordance.token,
                arguments={"order": "raid", "target_id": 2},
                required_acceptors=("player",),
            )
        option = self.offer()
        proposal = self.broker.commit(
            option["proposal_token"], "action:npc-turn:1", self.source_context
        )
        self.assertEqual(self.broker.options("village-elder", self.source_context), ())
        self.assertEqual(
            self.broker.commit(
                option["proposal_token"], "action:npc-turn:1", self.source_context
            ),
            proposal,
        )
        with self.assertRaisesRegex(ValueError, "already committed"):
            self.broker.commit(
                option["proposal_token"],
                "action:npc-turn:different",
                self.source_context,
            )
        self.now = 2000
        self.assertEqual(self.broker.options("village-elder", self.source_context), ())


if __name__ == "__main__":
    unittest.main()
