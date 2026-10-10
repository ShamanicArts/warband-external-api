"""Deterministic constrained-session backend for direct MCP acceptance tests."""

from itertools import count

from warband_agentic.agent_api import ConstrainedAgentSession
from warband_agentic.authority import (
    LeaseBook,
    ObservationFilter,
    default_perception_policies,
)
from warband_agentic.capabilities import CapabilityDefinition, CapabilityRegistry
from warband_agentic.contracts import (
    ActionOutcome,
    ActionState,
    ActorKind,
    ActorRef,
    AuthorityClass,
    ContextKind,
    ContextRef,
    Evidence,
    EvidenceLevel,
    Fact,
    FactSource,
    LeaseMode,
    ObservationEnvelope,
    RiskClass,
    RoleGrant,
    RoleId,
)


class FactionMcpUsabilityFixture:
    """One direct-MCP session that forces a single stale-context recovery."""

    def __init__(self):
        self._revision = 7
        self._first_observation = True
        self._selected_order = None
        self._dispatch_count = 0
        self.controller = ActorRef("controller:faction:1", ActorKind.SYSTEM)
        self.party = ActorRef("party:17", ActorKind.PARTY, 17)
        self.praven = ActorRef("settlement:2", ActorKind.SETTLEMENT, 2)
        self.enemy = ActorRef("party:99", ActorKind.PARTY, 99)
        self.grant = RoleGrant(
            "grant:mcp-fixture:swadia",
            RoleId.FACTION_SOVEREIGN,
            self.controller,
            (AuthorityClass.OBSERVE, AuthorityClass.PARTY_COMMAND),
            "faction.sovereign",
            ("party.strategy",),
            1000,
            10_000,
        )
        self.leases = LeaseBook(lambda: "lease:mcp-fixture:party-17")
        self.lease = self.leases.acquire(
            self.controller,
            self.party,
            ("party.strategy",),
            LeaseMode.EXCLUSIVE,
            1000,
            10_000,
        )
        token_numbers = count(1)
        self.registry = CapabilityRegistry(
            lambda: f"mcp-fixture-token-{next(token_numbers)}",
            self.leases.resolve,
        )
        self.registry.register(
            CapabilityDefinition(
                "party.issue-order",
                "Issue one bounded strategic order to a controlled faction party",
                "party.strategy",
                AuthorityClass.PARTY_COMMAND,
                (ContextKind.CAMPAIGN,),
                {
                    "type": "object",
                    "properties": {
                        "order": {"type": "string", "enum": ("defend", "raid")},
                        "target_id": {"type": "integer", "minimum": 0},
                    },
                    "required": ("order", "target_id"),
                    "additionalProperties": False,
                },
                RiskClass.REVERSIBLE,
                True,
                "The party will abandon its current strategic order.",
                EvidenceLevel.ENGINE_OBSERVED,
                "fixture.party-order",
                True,
            )
        )
        filters = ObservationFilter()
        for policy in default_perception_policies():
            filters.register(policy)
        self.session = ConstrainedAgentSession(
            "session:mcp-usability:swadia",
            self.grant,
            self.registry,
            filters,
            self._observation,
            self._affordances,
            self._dispatch,
            lambda affordance: self.lease.lease_id,
            clock_ms=lambda: 1200,
            action_id_factory=lambda request_id: f"action:{request_id}",
        )

    @property
    def dispatch_count(self):
        return self._dispatch_count

    @property
    def selected_order(self):
        return self._selected_order

    @staticmethod
    def task():
        return (
            "Praven (settlement 2) faces an imminent threat. Use your constrained "
            "Warband tools to order controlled party 17 to defend it. If the game "
            "context changes, fetch a fresh turn and reason again. Finish only after "
            "you inspect the action outcome."
        )

    def _context(self, revision):
        return ContextRef(
            ContextKind.CAMPAIGN,
            "campaign:world",
            revision,
            None,
            101,
        )

    def _observation(self):
        revision = self._revision
        if self._first_observation:
            self._first_observation = False
            self._revision = 8
        facts = [
            Fact(
                "faction.name",
                "Kingdom of Swadia",
                FactSource.DEFINITION_METADATA,
                revision,
            ),
            Fact(
                "settlements.2.name",
                "Praven",
                FactSource.DEFINITION_METADATA,
                revision,
            ),
            Fact(
                "reports.2.threat",
                "imminent",
                FactSource.ENGINE_OBSERVED,
                revision,
            ),
            Fact(
                "parties.17.status",
                "available",
                FactSource.ENGINE_OBSERVED,
                revision,
            ),
            Fact(
                "operator.enemy_exact_strength",
                417,
                FactSource.ENGINE_OBSERVED,
                revision,
            ),
        ]
        if self._selected_order is not None:
            facts.append(
                Fact(
                    "parties.17.order",
                    self._selected_order,
                    FactSource.ENGINE_OBSERVED,
                    revision,
                )
            )
        return ObservationEnvelope(
            f"canonical:mcp-usability:{revision}",
            self.controller,
            RoleId.OPERATOR_FULL,
            self._context(revision),
            tuple(facts),
            (),
            1100,
        )

    def _affordances(self, registry, grant, observation, now_ms):
        if self._selected_order is not None:
            return ()
        choices = (
            ("defend", self.praven),
            ("raid", self.enemy),
        )
        return tuple(
            registry.issue(
                "party.issue-order",
                self.controller,
                (self.party, target),
                observation.context,
                grant,
                now_ms,
                5000,
                {
                    "type": "object",
                    "properties": {
                        "order": {"type": "string", "const": order},
                        "target_id": {"type": "integer", "const": target.game_id},
                    },
                    "required": ("order", "target_id"),
                    "additionalProperties": False,
                },
            )
            for order, target in choices
        )

    def _dispatch(self, validated):
        self._dispatch_count += 1
        self._selected_order = validated.submission.arguments["order"]
        self._revision = validated.affordance.context.revision + 1
        return ActionOutcome(
            validated.submission.action_id,
            ActionState.OBSERVED,
            validated.affordance.context,
            self._revision,
            {"result": 0},
            (
                Fact(
                    "parties.17.order",
                    self._selected_order,
                    FactSource.ENGINE_OBSERVED,
                    self._revision,
                ),
            ),
            (
                Evidence(
                    EvidenceLevel.ENGINE_OBSERVED,
                    "deterministic MCP fixture",
                    f"Party 17 order read back as {self._selected_order}",
                ),
            ),
            None,
            1300,
        )


def build_faction_mcp_usability_fixture():
    return FactionMcpUsabilityFixture()
