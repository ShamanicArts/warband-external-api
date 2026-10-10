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

    def __init__(
        self,
        *,
        revision=7,
        fixture_name="faction-order-v1",
        observation_suffix="1",
        tokens=("aff:defend-praven", "aff:raid-party-99"),
    ):
        self.fixture_name = fixture_name
        self.now_ms = 1200
        self.context = ContextRef(
            ContextKind.CAMPAIGN, "campaign:world", revision, None, 101
        )
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
        token_source = iter(tokens)
        self.registry = CapabilityRegistry(
            lambda: next(token_source), self.leases.resolve
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
                "fixture.party_order",
                True,
            )
        )
        self.observation = self._build_observation(observation_suffix)
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

    def _build_observation(self, observation_suffix):
        revision = self.context.revision
        canonical = ObservationEnvelope(
            f"canonical:fixture:{observation_suffix}",
            self.controller,
            RoleId.OPERATOR_FULL,
            self.context,
            (
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
            ),
            (),
            1100,
        )
        filters = ObservationFilter()
        for policy in default_perception_policies():
            filters.register(policy)
        return filters.apply(
            canonical,
            self.grant,
            f"fixture:observation:{observation_suffix}",
            1100,
        )

    def briefing(self):
        return {
            "fixture": self.fixture_name,
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
                if validated.affordance.token != self.affordances[0].token:
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


class FactionRevisionRecoveryFixture(FactionUsabilityFixture):
    """A refreshed turn that requires abandoning a stale token and revision."""

    def __init__(self):
        super().__init__(
            revision=8,
            fixture_name="faction-revision-recovery-v2",
            observation_suffix="2",
            tokens=("aff:defend-praven-r8", "aff:raid-party-99-r8"),
        )

    def briefing(self):
        briefing = super().briefing()
        briefing["task"] = (
            "The previous defense submission was rejected because the campaign "
            "context advanced. Retry the requested defense of Praven using only a "
            "currently issued affordance. Do not reuse the stale token or revision."
        )
        briefing["action_binding"] = {
            "expected_revision": self.context.revision,
            "source": "observation.context.revision",
            "rule": (
                "Copy this integer exactly into response.expected_revision. "
                "Affordance tokens from earlier revisions are invalid."
            ),
        }
        briefing["prior_attempt"] = {
            "response": {
                "affordance_token": "aff:defend-praven",
                "arguments": {"order": "defend", "target_id": 2},
                "expected_revision": 7,
            },
            "outcome": {
                "accepted": False,
                "code": "stale_context",
                "message": "Expected revision 7 is stale; current revision is 8.",
            },
        }
        return briefing


def build_faction_usability_fixture():
    return FactionUsabilityFixture()


def build_faction_revision_recovery_fixture():
    return FactionRevisionRecoveryFixture()
