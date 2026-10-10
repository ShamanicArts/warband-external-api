"""Deterministic two-faction arena for external-model benchmark acceptance."""

from copy import deepcopy
from dataclasses import dataclass
from itertools import count

from warband_agentic.agent_api import ConstrainedAgentSession
from warband_agentic.authority import LeaseBook, ObservationFilter, PerceptionPolicy
from warband_agentic.benchmark import SynchronizedFactionEpoch
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
from warband_agentic.provider_decisions import (
    DecisionBudget,
    DecisionUsage,
    ProviderAssignment,
    ProviderDecisionBatch,
)
from warband_agentic.scoring import (
    BenchmarkScenario,
    FactionBenchmarkRun,
    FactionMetricSnapshot,
    MetricObjective,
    MetricObservation,
    MetricRule,
)

ARENA_SCHEMA = "warband.agentic/deterministic-faction-arena/v1"


@dataclass(slots=True)
class _FactionState:
    faction_id: int
    name: str
    party_id: int
    home_settlement_id: int
    military_strength: int = 100
    settlements: int = 1
    supply: int = 60


@dataclass(frozen=True, slots=True)
class _StagedOrder:
    faction_id: int
    request_id: str
    action_id: str
    action: str
    context: ContextRef


class _ArenaWorld:
    def __init__(self):
        self.revision = 1
        self.game_time = 100
        self.factions = {
            15: _FactionState(15, "Kingdom of Swadia", 500, 2),
            16: _FactionState(16, "Kingdom of Vaegirs", 600, 1),
        }
        self._orders = {}
        self._outcomes = {}
        self._resolved = False

    @staticmethod
    def enemy_id(faction_id):
        return 16 if faction_id == 15 else 15

    def context(self):
        return ContextRef(
            ContextKind.CAMPAIGN,
            "campaign:deterministic-border-war",
            self.revision,
            None,
            self.game_time,
        )

    def stage(self, faction_id, validated):
        submission = validated.submission
        order = _StagedOrder(
            faction_id,
            submission.action_id.removeprefix(f"action:arena:faction:{faction_id}:"),
            submission.action_id,
            submission.arguments["action"],
            validated.affordance.context,
        )
        self._orders[faction_id] = order
        return ActionOutcome(
            submission.action_id,
            ActionState.ACCEPTED,
            validated.affordance.context,
            None,
            {"status": "staged", "simultaneous": True},
            (),
            (
                Evidence(
                    EvidenceLevel.DECLARED,
                    "deterministic arena coordinator",
                    "Order is staged until every faction decision is committed",
                ),
            ),
            None,
            1300,
        )

    def resolve(self):
        if self._resolved:
            raise RuntimeError("arena epoch was already resolved")
        actions = {
            faction_id: self._orders.get(faction_id).action
            if faction_id in self._orders
            else "idle"
            for faction_id in self.factions
        }

        for faction_id, action in actions.items():
            state = self.factions[faction_id]
            if action == "recruit" and state.supply >= 20:
                state.supply -= 20
                state.military_strength += 15

        for attacker_id, action in actions.items():
            if action != "attack":
                continue
            defender_id = self.enemy_id(attacker_id)
            attacker = self.factions[attacker_id]
            defender = self.factions[defender_id]
            attacker.military_strength = max(0, attacker.military_strength - 10)
            if actions[defender_id] == "defend":
                defender.military_strength = max(0, defender.military_strength - 5)
            else:
                defender.military_strength = max(0, defender.military_strength - 20)
                if defender.settlements > 0:
                    defender.settlements -= 1
                    attacker.settlements += 1

        self.revision += 1
        for faction_id, order in self._orders.items():
            state = self.factions[faction_id]
            self._outcomes[(faction_id, order.request_id)] = ActionOutcome(
                order.action_id,
                ActionState.OBSERVED,
                order.context,
                self.revision,
                {
                    "status": "resolved",
                    "simultaneous_actions": {
                        str(key): value for key, value in sorted(actions.items())
                    },
                },
                (
                    Fact(
                        f"faction.{faction_id}.military_strength",
                        state.military_strength,
                        FactSource.ENGINE_OBSERVED,
                        self.revision,
                    ),
                    Fact(
                        f"faction.{faction_id}.settlements",
                        state.settlements,
                        FactSource.ENGINE_OBSERVED,
                        self.revision,
                    ),
                ),
                (
                    Evidence(
                        EvidenceLevel.ENGINE_OBSERVED,
                        "deterministic arena state getter",
                        "The staged simultaneous order was resolved and read back",
                    ),
                ),
                None,
                1400,
            )
        self._resolved = True

    def outcome(self, faction_id, request_id, previous):
        return self._outcomes.get((faction_id, request_id), previous)

    def advance_one_hour(self):
        if not self._resolved:
            raise RuntimeError("arena cannot advance before resolving orders")
        self.game_time += 1

    def metrics(self, snapshot_id):
        evidence = Evidence(
            EvidenceLevel.ENGINE_OBSERVED,
            "deterministic arena state getter",
            "Metric read from the deterministic simulator at a fixed game clock",
        )
        return FactionMetricSnapshot(
            snapshot_id,
            self.game_time,
            {
                faction_id: (
                    MetricObservation(
                        "military_strength", state.military_strength, evidence
                    ),
                    MetricObservation("settlements", state.settlements, evidence),
                    MetricObservation(
                        "surviving", state.military_strength > 0, evidence
                    ),
                )
                for faction_id, state in self.factions.items()
            },
        )


class _ArenaFactionApplication:
    def __init__(self, world, faction_id):
        self.world = world
        self.faction_id = faction_id
        state = world.factions[faction_id]
        self.controlled_party_ids = (state.party_id,)
        self.controller = ActorRef(
            f"controller:faction:{faction_id}", ActorKind.FACTION, faction_id
        )
        self.party = ActorRef(
            f"party:{state.party_id}", ActorKind.PARTY, state.party_id
        )
        self.grant = RoleGrant(
            f"grant:arena:faction:{faction_id}",
            RoleId.FACTION_SOVEREIGN,
            self.controller,
            (AuthorityClass.OBSERVE, AuthorityClass.PARTY_COMMAND),
            f"arena.faction.{faction_id}",
            ("party.strategy",),
            1000,
            10_000,
        )
        self.leases = LeaseBook(lambda: f"lease:arena:party:{state.party_id}")
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
            lambda: f"arena-f{faction_id}-token-{next(token_numbers)}",
            self.leases.resolve,
        )
        for action, risk, reversible, warning in (
            (
                "attack",
                RiskClass.CONSEQUENTIAL,
                False,
                "The army and target settlement may suffer irreversible losses.",
            ),
            (
                "defend",
                RiskClass.REVERSIBLE,
                True,
                "The army will hold its home settlement for this epoch.",
            ),
            (
                "recruit",
                RiskClass.CONSEQUENTIAL,
                False,
                "Recruitment permanently spends 20 supply this epoch.",
            ),
        ):
            self.registry.register(
                CapabilityDefinition(
                    f"faction.strategy.{action}",
                    f"Choose the {action} posture for this synchronized epoch",
                    "party.strategy",
                    AuthorityClass.PARTY_COMMAND,
                    (ContextKind.CAMPAIGN,),
                    {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "const": action},
                            "target_id": {"type": "integer", "minimum": 0},
                        },
                        "required": ("action", "target_id"),
                        "additionalProperties": False,
                    },
                    risk,
                    reversible,
                    warning,
                    EvidenceLevel.ENGINE_OBSERVED,
                    f"arena.strategy.{action}",
                    True,
                )
            )
        filters = ObservationFilter()
        filters.register(
            PerceptionPolicy(
                f"arena.faction.{faction_id}",
                RoleId.FACTION_SOVEREIGN,
                (
                    f"faction.{faction_id}",
                    f"parties.{state.party_id}",
                    f"settlements.{state.home_settlement_id}",
                    f"reports.{world.enemy_id(faction_id)}",
                    "public",
                ),
                tuple(FactSource),
                (ContextKind.CAMPAIGN,),
            )
        )
        self.session = ConstrainedAgentSession(
            f"arena:faction:{faction_id}",
            self.grant,
            self.registry,
            filters,
            self._observation,
            self._affordances,
            lambda validated: self.world.stage(faction_id, validated),
            lambda _affordance: self.lease.lease_id,
            clock_ms=lambda: 1200,
            action_id_factory=lambda request_id: (
                f"action:arena:faction:{faction_id}:{request_id}"
            ),
            outcome_refresher=lambda request_id, previous: self.world.outcome(
                faction_id, request_id, previous
            ),
        )

    def queue_observation_refresh(self):
        return {
            self.controlled_party_ids[0]: (
                f"deterministic:revision:{self.world.revision}:faction:{self.faction_id}"
            )
        }

    def _observation(self):
        own = self.world.factions[self.faction_id]
        enemy_id = self.world.enemy_id(self.faction_id)
        enemy = self.world.factions[enemy_id]
        revision = self.world.revision
        return ObservationEnvelope(
            f"canonical:arena:faction:{self.faction_id}:revision:{revision}",
            self.controller,
            RoleId.OPERATOR_FULL,
            self.world.context(),
            (
                Fact(
                    f"faction.{self.faction_id}.name",
                    own.name,
                    FactSource.DEFINITION_METADATA,
                    revision,
                ),
                Fact(
                    f"faction.{self.faction_id}.military_strength",
                    own.military_strength,
                    FactSource.ENGINE_OBSERVED,
                    revision,
                ),
                Fact(
                    f"faction.{self.faction_id}.settlements",
                    own.settlements,
                    FactSource.ENGINE_OBSERVED,
                    revision,
                ),
                Fact(
                    f"faction.{self.faction_id}.supply",
                    own.supply,
                    FactSource.ENGINE_OBSERVED,
                    revision,
                ),
                Fact(
                    f"reports.{enemy_id}.strength_band",
                    "90-110",
                    FactSource.INFERRED,
                    revision,
                ),
                Fact(
                    "public.objective",
                    "Maximize settlements, military strength, and survival.",
                    FactSource.DEFINITION_METADATA,
                    revision,
                ),
                Fact(
                    "public.resolution_rules",
                    {
                        "timing": "all decisions resolve simultaneously",
                        "attack": {
                            "attacker_strength_loss": 10,
                            "undefended_target_strength_loss": 20,
                            "defended_target_strength_loss": 5,
                            "captures_one_settlement_if_undefended": True,
                        },
                        "defend": {"prevents_settlement_capture": True},
                        "recruit": {
                            "supply_cost": 20,
                            "strength_gain_before_attacks": 15,
                        },
                    },
                    FactSource.DEFINITION_METADATA,
                    revision,
                ),
                Fact(
                    "operator.enemy_exact_strength",
                    enemy.military_strength,
                    FactSource.ENGINE_OBSERVED,
                    revision,
                ),
            ),
            (),
            1100,
        )

    def _affordances(self, registry, grant, observation, now_ms):
        own = self.world.factions[self.faction_id]
        enemy = self.world.factions[self.world.enemy_id(self.faction_id)]
        choices = (
            ("attack", enemy.home_settlement_id, enemy),
            ("defend", own.home_settlement_id, own),
            ("recruit", own.party_id, own),
        )
        return tuple(
            registry.issue(
                f"faction.strategy.{action}",
                self.controller,
                (
                    self.party,
                    ActorRef(
                        (
                            f"party:{target.party_id}"
                            if action == "recruit"
                            else f"settlement:{target_id}"
                        ),
                        ActorKind.PARTY
                        if action == "recruit"
                        else ActorKind.SETTLEMENT,
                        target.party_id if action == "recruit" else target_id,
                    ),
                ),
                observation.context,
                grant,
                now_ms,
                5000,
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "const": action},
                        "target_id": {"type": "integer", "const": target_id},
                    },
                    "required": ("action", "target_id"),
                    "additionalProperties": False,
                },
            )
            for action, target_id, target in choices
        )


class DeterministicFactionArena:
    """One synchronized, scored faction epoch with no live game dependency."""

    def __init__(self):
        self.world = _ArenaWorld()
        self.applications = {
            faction_id: _ArenaFactionApplication(self.world, faction_id)
            for faction_id in sorted(self.world.factions)
        }
        self.scenario = BenchmarkScenario(
            "deterministic.border-war",
            "1.0.0",
            "Two factions choose simultaneous border-war postures",
            (15, 16),
            (
                MetricRule(
                    "settlements",
                    "Controlled settlements after the epoch",
                    "count",
                    MetricObjective.MAXIMIZE,
                    60,
                    1,
                ),
                MetricRule(
                    "military_strength",
                    "Surviving field strength after the epoch",
                    "troops",
                    MetricObjective.MAXIMIZE,
                    30,
                    50,
                ),
                MetricRule(
                    "surviving",
                    "Faction retains a nonzero field army",
                    "boolean",
                    MetricObjective.BINARY,
                    10,
                    None,
                ),
            ),
        )
        self.run_metadata = {
            "backend": "deterministic-simulator",
            "game_launched": False,
            "scenario_seed": 1,
            "runner_version": "0.2.0",
        }
        self.decision_budget = DecisionBudget(8192, 512, 120_000)
        self.run = FactionBenchmarkRun(
            "deterministic-border-war-1",
            self.scenario,
            run_metadata=self.run_metadata,
        )
        self.run.set_baseline(self.world.metrics("arena:baseline"))
        self.epoch = SynchronizedFactionEpoch(
            "arena:epoch:1",
            self.applications,
            run_metadata=self.run_metadata,
        )
        self.epoch.queue_observation_refreshes()
        self.turns = self.epoch.collect_turns()
        self._resolved = False

    def briefing(self):
        transcript = self.epoch.transcript()
        return {
            "schema": ARENA_SCHEMA,
            "scenario": self.scenario.manifest(),
            "epoch_id": self.epoch.epoch_id,
            "turn_set_sha256": transcript["turn_set_sha256"],
            "simultaneous_decisions": True,
            "decision_budget": self.decision_budget.manifest(),
            "game_launched": False,
            "boundary": (
                "Deterministic simulator acceptance; this does not prove a live "
                "Warband faction outcome."
            ),
            "factions": {
                str(faction_id): self.task(faction_id)
                for faction_id in sorted(self.turns)
            },
        }

    def task(self, faction_id):
        if faction_id not in self.turns:
            raise ValueError("faction is not part of this arena")
        return deepcopy(
            {
                "schema": "warband.agentic/faction-decision-task/v1",
                "epoch_id": self.epoch.epoch_id,
                "faction_id": faction_id,
                "objective": (
                    "Choose exactly one current affordance to maximize settlements, "
                    "military strength, and survival. The opponent decides "
                    "simultaneously from a separately filtered turn."
                ),
                "decision_budget": self.decision_budget.manifest(),
                "turn": self.turns[faction_id],
                "response_schema": {
                    "type": "object",
                    "required": (
                        "request_id",
                        "affordance_token",
                        "arguments",
                        "expected_revision",
                    ),
                    "additionalProperties": False,
                },
            }
        )

    def resolve(self, decisions):
        return self._resolve(decisions, provider_audit=None)

    def resolve_provider_results(self, results):
        if not isinstance(results, dict) or set(results) != set(self.turns):
            raise ValueError("provider results must contain factions 15 and 16")
        assignments = {}
        for faction_id, result in results.items():
            if not isinstance(result, dict) or set(result) != {
                "assignment",
                "response",
                "usage",
            }:
                raise ValueError(
                    "each provider result requires assignment, response, and usage"
                )
            assignment = result["assignment"]
            usage = result["usage"]
            if not isinstance(assignment, dict):
                raise ValueError("provider assignment must be an object")
            if not isinstance(usage, dict):
                raise ValueError("provider usage must be an object")
            assignments[faction_id] = ProviderAssignment(**assignment)
        batch = ProviderDecisionBatch(
            "arena:batch:1",
            self.epoch.epoch_id,
            self.turns,
            assignments,
            self.decision_budget,
        )
        for faction_id, result in sorted(results.items()):
            batch.record_success(
                faction_id,
                result["response"],
                DecisionUsage(**result["usage"]),
            )
        return self._resolve(batch.decisions(), provider_audit=batch.audit())

    def _resolve(self, decisions, provider_audit):
        if self._resolved:
            raise RuntimeError("arena was already resolved")
        if not isinstance(decisions, dict) or set(decisions) != set(self.turns):
            raise ValueError("decisions must contain factions 15 and 16")
        self.epoch.commit_decisions(decisions)
        self.world.resolve()
        self.epoch.refresh_outcomes()
        self.world.advance_one_hour()
        self.epoch.record_campaign_advance(
            {
                "epoch_id": self.epoch.epoch_id,
                "state": "complete",
                "start_clock": 100,
                "target_clock": 101,
                "current_clock": 101,
                "elapsed_hours": 1,
                "target_reached": True,
                "start_command_status": "acknowledged",
                "stop_command_status": "acknowledged",
                "stop_acknowledged": True,
                "reason": None,
            }
        )
        metrics = self.world.metrics("arena:epoch:1:metrics")
        self.run.append_epoch(
            self.epoch.transcript(), metrics, provider_audit=provider_audit
        )
        self._resolved = True
        return self.run.report()


def build_deterministic_faction_arena():
    return DeterministicFactionArena()
