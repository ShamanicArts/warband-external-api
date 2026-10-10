"""Deterministic restricted-agent fixture for interface usability testing."""

from dataclasses import dataclass

from warband_agentic.authority import (
    LeaseBook,
    ObservationFilter,
    default_perception_policies,
)
from warband_agentic.capabilities import CapabilityDefinition, CapabilityRegistry
from warband_agentic.contracts import (
    ActionSubmission,
    ActorKind,
    ActorRef,
    AuthorityClass,
    ContextKind,
    ContextRef,
    EvidenceLevel,
    Fact,
    FactSource,
    LeaseMode,
    ObservationEnvelope,
    RiskClass,
    RoleGrant,
    RoleId,
    to_wire,
)


@dataclass(frozen=True, slots=True)
class UsabilityEvaluation:
    accepted: bool
    score: int
    capability: str | None
    reasons: tuple[str, ...]
    transcript: dict


class FactionUsabilityFixture:
    """One-turn fixture exercising filtered perception and bounded action choice."""

    def __init__(self):
        self.now_ms = 1200
        self.context = ContextRef(ContextKind.CAMPAIGN, "campaign:world", 7, None, 101)
        self.controller = ActorRef("controller:faction:1", ActorKind.SYSTEM)
        self.party = ActorRef("party:17", ActorKind.PARTY, 17)
        self.settlement = ActorRef("settlement:2", ActorKind.SETTLEMENT, 2)
        self.grant = RoleGrant(
            "grant:fixture:swadia",
            RoleId.FACTION_SOVEREIGN,
            self.controller,
            (AuthorityClass.OBSERVE, AuthorityClass.PARTY_COMMAND),
            "faction.sovereign",
            ("party.strategy",),
            1000,
            2000,
        )
        self.leases = LeaseBook(lambda: "lease:fixture:party-17")
        self.lease = self.leases.acquire(
            self.controller,
            self.party,
            ("party.strategy",),
            LeaseMode.EXCLUSIVE,
            1000,
            2000,
        )
        tokens = iter(("aff:defend-praven", "aff:raid-party-99"))
        self.registry = CapabilityRegistry(lambda: next(tokens), self.leases.resolve)
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
                "fixture.party_order",
                True,
            )
        )
        self.observation = self._build_observation()
        self.affordances = (
            self.registry.issue(
                "party.issue-order",
                self.controller,
                (self.party, self.settlement),
                self.context,
                self.grant,
                1100,
                1800,
                {
                    "type": "object",
                    "properties": {
                        "order": {"type": "string", "const": "defend"},
                        "target_id": {"type": "integer", "const": 2},
                    },
                    "required": ("order", "target_id"),
                    "additionalProperties": False,
                },
            ),
            self.registry.issue(
                "party.issue-order",
                self.controller,
                (self.party, ActorRef("party:99", ActorKind.PARTY, 99)),
                self.context,
                self.grant,
                1100,
                1800,
                {
                    "type": "object",
                    "properties": {
                        "order": {"type": "string", "const": "raid"},
                        "target_id": {"type": "integer", "const": 99},
                    },
                    "required": ("order", "target_id"),
                    "additionalProperties": False,
                },
            ),
        )

    def _build_observation(self):
        canonical = ObservationEnvelope(
            "canonical:fixture:1",
            self.controller,
            RoleId.OPERATOR_FULL,
            self.context,
            (
                Fact(
                    "faction.name",
                    "Kingdom of Swadia",
                    FactSource.DEFINITION_METADATA,
                    7,
                ),
                Fact(
                    "settlements.2.name",
                    "Praven",
                    FactSource.DEFINITION_METADATA,
                    7,
                ),
                Fact("reports.2.threat", "imminent", FactSource.ENGINE_OBSERVED, 7),
                Fact("parties.17.status", "available", FactSource.ENGINE_OBSERVED, 7),
                Fact(
                    "operator.enemy_exact_strength",
                    417,
                    FactSource.ENGINE_OBSERVED,
                    7,
                ),
            ),
            (),
            1100,
        )
        filters = ObservationFilter()
        for policy in default_perception_policies():
            filters.register(policy)
        return filters.apply(canonical, self.grant, "fixture:observation:1", 1100)

    def briefing(self):
        return {
            "fixture": "faction-order-v1",
            "task": (
                "Praven (settlement 2) faces an imminent reported threat. Use the "
                "reversible affordance that orders controlled party 17 to defend it. "
                "Do not invent IDs, hidden facts, direct operations, or admin actions."
            ),
            "response_schema": {
                "type": "object",
                "required": ("affordance_token", "arguments", "expected_revision"),
                "additionalProperties": False,
            },
            "observation": to_wire(self.observation),
            "capabilities": self.registry.discover(
                self.grant, self.context, self.now_ms
            ),
            "affordances": [to_wire(item) for item in self.affordances],
        }

    def evaluate(self, response):
        reasons = []
        capability = None
        allowed = {"affordance_token", "arguments", "expected_revision"}
        if not isinstance(response, dict):
            reasons.append("response must be an object")
        elif set(response) != allowed:
            reasons.append("response fields do not match the restricted interface")
        else:
            try:
                submission = ActionSubmission(
                    "fixture:evaluation:1",
                    response["affordance_token"],
                    self.controller,
                    response["arguments"],
                    response["expected_revision"],
                    self.now_ms,
                    self.lease.lease_id,
                )
                validated = self.registry.consume(
                    submission, self.context, self.grant, self.now_ms
                )
                capability = validated.capability.name
                if validated.affordance.token != "aff:defend-praven":
                    reasons.append("selected action does not defend Praven")
            except (KeyError, TypeError, ValueError) as exc:
                reasons.append(str(exc))
        accepted = not reasons
        transcript = {
            "fixture": self.briefing()["fixture"],
            "response": response,
            "accepted": accepted,
            "reasons": list(reasons),
        }
        return UsabilityEvaluation(
            accepted,
            100 if accepted else 0,
            capability,
            tuple(reasons),
            transcript,
        )


def build_faction_usability_fixture():
    return FactionUsabilityFixture()
