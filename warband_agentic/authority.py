"""Control-lease arbitration and policy-filtered observation delivery."""

import secrets
from dataclasses import dataclass
from threading import RLock

from warband_agentic.contracts import (
    CONTRACT_VERSION,
    ActorRef,
    ContextKind,
    ControlLease,
    FactSource,
    LeaseMode,
    ObservationEnvelope,
    RoleGrant,
    RoleId,
)


def _nonempty(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _timestamp(name, value):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _domains_overlap(left, right):
    return "*" in left or "*" in right or bool(set(left) & set(right))


class LeaseBook:
    """Issue trusted leases and reject conflicting live control ownership."""

    def __init__(self, lease_id_factory=None):
        self._leases = {}
        self._generations = {}
        self._lease_id_factory = lease_id_factory or (
            lambda: "lease:" + secrets.token_urlsafe(18)
        )
        self._lock = RLock()

    def acquire(
        self,
        controller,
        target,
        domains,
        mode,
        issued_at_ms,
        expires_at_ms,
    ):
        if not isinstance(controller, ActorRef) or not isinstance(target, ActorRef):
            raise TypeError("controller and target must be ActorRef values")
        if not isinstance(mode, LeaseMode):
            raise TypeError("mode must be a LeaseMode")
        domains = tuple(domains)
        _timestamp("issued_at_ms", issued_at_ms)
        _timestamp("expires_at_ms", expires_at_ms)
        if expires_at_ms <= issued_at_ms:
            raise ValueError("lease must expire after it is issued")
        with self._lock:
            self._expire(issued_at_ms)
            for active in self._leases.values():
                if active.target != target or not _domains_overlap(
                    active.domains, domains
                ):
                    continue
                if active.controller == controller:
                    raise ValueError("Controller already holds an overlapping lease")
                if mode is LeaseMode.EXCLUSIVE or active.mode is LeaseMode.EXCLUSIVE:
                    raise ValueError(
                        "Control conflict with "
                        f"{active.controller.runtime_id} until {active.expires_at_ms}"
                    )
            lease_id = self._lease_id_factory()
            _nonempty("lease_id", lease_id)
            if lease_id in self._leases:
                raise ValueError("Control lease ID collision")
            generation = self._generations.get(target, 0) + 1
            lease = ControlLease(
                lease_id,
                controller,
                target,
                domains,
                mode,
                generation,
                issued_at_ms,
                expires_at_ms,
            )
            self._generations[target] = generation
            self._leases[lease_id] = lease
            return lease

    def active(self, target, domain, now_ms):
        if not isinstance(target, ActorRef):
            raise TypeError("target must be an ActorRef")
        _nonempty("domain", domain)
        _timestamp("now_ms", now_ms)
        with self._lock:
            self._expire(now_ms)
            return tuple(
                lease
                for lease in self._leases.values()
                if lease.target == target
                and (domain in lease.domains or "*" in lease.domains)
            )

    def require(self, lease_id, controller, target, domain, now_ms):
        _nonempty("lease_id", lease_id)
        _timestamp("now_ms", now_ms)
        with self._lock:
            self._expire(now_ms)
            lease = self._leases.get(lease_id)
            if lease is None:
                raise ValueError("Unknown or expired control lease")
            if lease.controller != controller or lease.target != target:
                raise ValueError("Control lease actor binding does not match")
            if domain not in lease.domains and "*" not in lease.domains:
                raise ValueError("Control lease lacks required domain")
            return lease

    def resolve(self, lease_id, now_ms):
        """Resolve only a lease that this book actually issued and still owns."""
        _nonempty("lease_id", lease_id)
        _timestamp("now_ms", now_ms)
        with self._lock:
            self._expire(now_ms)
            lease = self._leases.get(lease_id)
            if lease is None:
                raise ValueError("Unknown or expired control lease")
            return lease

    def release(self, lease_id, controller):
        _nonempty("lease_id", lease_id)
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                raise ValueError("Unknown control lease")
            if lease.controller != controller:
                raise ValueError("Only the controlling actor may release this lease")
            del self._leases[lease_id]
            return lease

    def _expire(self, now_ms):
        expired = [
            lease_id
            for lease_id, lease in self._leases.items()
            if now_ms >= lease.expires_at_ms
        ]
        for lease_id in expired:
            del self._leases[lease_id]


@dataclass(frozen=True, slots=True)
class PerceptionPolicy:
    policy_id: str
    role: RoleId
    fact_prefixes: tuple[str, ...]
    sources: tuple[FactSource, ...]
    contexts: tuple[ContextKind, ...]
    schema: str = CONTRACT_VERSION

    def __post_init__(self):
        _nonempty("policy_id", self.policy_id)
        if not isinstance(self.role, RoleId):
            raise TypeError("role must be a RoleId")
        prefixes = tuple(self.fact_prefixes)
        if any(not isinstance(prefix, str) or not prefix for prefix in prefixes):
            raise ValueError("fact_prefixes must contain non-empty strings")
        object.__setattr__(self, "fact_prefixes", prefixes)
        sources = tuple(self.sources)
        if not sources or any(not isinstance(source, FactSource) for source in sources):
            raise TypeError("sources must contain FactSource values")
        object.__setattr__(self, "sources", sources)
        contexts = tuple(self.contexts)
        if not contexts or any(
            not isinstance(context, ContextKind) for context in contexts
        ):
            raise TypeError("contexts must contain ContextKind values")
        object.__setattr__(self, "contexts", contexts)
        if self.schema != CONTRACT_VERSION:
            raise ValueError("unsupported contract schema")

    def allows(self, fact):
        return fact.source in self.sources and any(
            prefix == "*" or fact.key == prefix or fact.key.startswith(prefix + ".")
            for prefix in self.fact_prefixes
        )


class ObservationFilter:
    """Project canonical facts through a named role perception policy."""

    def __init__(self):
        self._policies = {}

    def register(self, policy):
        if not isinstance(policy, PerceptionPolicy):
            raise TypeError("policy must be a PerceptionPolicy")
        if policy.policy_id in self._policies:
            raise ValueError(
                f"Perception policy already registered: {policy.policy_id}"
            )
        self._policies[policy.policy_id] = policy

    def apply(self, canonical, grant, observation_id, issued_at_ms):
        if not isinstance(canonical, ObservationEnvelope) or not isinstance(
            grant, RoleGrant
        ):
            raise TypeError("apply requires ObservationEnvelope and RoleGrant values")
        _nonempty("observation_id", observation_id)
        _timestamp("issued_at_ms", issued_at_ms)
        if issued_at_ms < grant.issued_at_ms or (
            grant.expires_at_ms is not None and issued_at_ms >= grant.expires_at_ms
        ):
            raise ValueError("Role grant is not active")
        policy = self._policies.get(grant.perception_policy)
        if policy is None:
            raise ValueError("Unknown perception policy")
        if policy.role != grant.role:
            raise ValueError("Perception policy role does not match grant")
        if canonical.context.kind not in policy.contexts:
            raise ValueError("Perception policy is invalid in this context")
        visible = tuple(fact for fact in canonical.facts if policy.allows(fact))
        hidden_categories = {
            fact.key.split(".", 1)[0]
            for fact in canonical.facts
            if not policy.allows(fact)
        }
        return ObservationEnvelope(
            observation_id,
            grant.grantee,
            grant.role,
            canonical.context,
            visible,
            tuple(sorted(set(canonical.omitted) | hidden_categories)),
            issued_at_ms,
        )


def default_perception_policies():
    """Return conservative initial policies from the architecture specification."""
    all_sources = tuple(FactSource)
    all_contexts = tuple(ContextKind)
    return (
        PerceptionPolicy(
            "observer.readonly",
            RoleId.OBSERVER_READONLY,
            ("public",),
            all_sources,
            all_contexts,
        ),
        PerceptionPolicy(
            "player.strategic",
            RoleId.PLAYER_STRATEGIC,
            ("player", "campaign", "menu", "dialogue", "public", "memory"),
            all_sources,
            all_contexts,
        ),
        PerceptionPolicy(
            "npc.self",
            RoleId.NPC_SELF,
            (
                "self",
                "scene",
                "party",
                "relationships",
                "known_events",
                "dialogue",
                "public",
                "memory",
            ),
            all_sources,
            all_contexts,
        ),
        PerceptionPolicy(
            "party.commander",
            RoleId.PARTY_COMMANDER,
            (
                "self",
                "party",
                "route",
                "nearby_threats",
                "orders",
                "known_events",
                "public",
                "memory",
            ),
            all_sources,
            all_contexts,
        ),
        PerceptionPolicy(
            "faction.sovereign",
            RoleId.FACTION_SOVEREIGN,
            (
                "self",
                "faction",
                "settlements",
                "parties",
                "diplomacy",
                "reports",
                "known_events",
                "public",
                "memory",
            ),
            all_sources,
            all_contexts,
        ),
        PerceptionPolicy(
            "test.director",
            RoleId.TEST_DIRECTOR,
            ("*",),
            all_sources,
            all_contexts,
        ),
        PerceptionPolicy(
            "operator.full",
            RoleId.OPERATOR_FULL,
            ("*",),
            all_sources,
            all_contexts,
        ),
    )
