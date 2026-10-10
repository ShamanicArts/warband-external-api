"""Provider-neutral equal-budget faction decision batches and audit receipts."""

import hashlib
import hmac
import json
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

PROVIDER_DECISION_BATCH_SCHEMA = "warband.agentic/provider-decision-batch/v1"
PROVIDER_DECISION_BATCH_CHECKPOINT_SCHEMA = (
    "warband.agentic/provider-decision-batch-checkpoint/v1"
)


def _bounded_text(name, value, *, maximum=200):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or not value.isprintable()
        or any(character in value for character in "\r\n\x00")
    ):
        raise ValueError(f"{name} must be 1-{maximum} printable characters")
    return value


def _bounded_integer(name, value, *, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} through {maximum}")
    return value


def _json_copy(value, name):
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only finite JSON values") from exc
    if len(encoded.encode()) > 256 * 1024:
        raise ValueError(f"{name} exceeds the 256 KiB limit")
    return json.loads(encoded)


def _canonical_hash(value):
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _reject_credential_settings(value, path="settings"):
    blocked = {
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "authorization",
        "bearer_token",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower().replace("-", "_").replace(" ", "_")
            if normalized in blocked:
                raise ValueError(
                    f"provider settings contain credential-like field {path}.{key}"
                )
            _reject_credential_settings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_credential_settings(item, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class DecisionBudget:
    max_input_tokens: int
    max_output_tokens: int
    timeout_ms: int
    max_cost_microusd: int | None = None

    def __post_init__(self):
        _bounded_integer(
            "max_input_tokens", self.max_input_tokens, minimum=1, maximum=1_000_000
        )
        _bounded_integer(
            "max_output_tokens", self.max_output_tokens, minimum=1, maximum=1_000_000
        )
        _bounded_integer("timeout_ms", self.timeout_ms, minimum=1, maximum=3_600_000)
        if self.max_cost_microusd is not None:
            _bounded_integer(
                "max_cost_microusd",
                self.max_cost_microusd,
                minimum=1,
                maximum=1_000_000_000_000,
            )

    def manifest(self):
        return {
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "timeout_ms": self.timeout_ms,
            "max_cost_microusd": self.max_cost_microusd,
        }


@dataclass(frozen=True, slots=True)
class DecisionUsage:
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    cost_microusd: int | None = None

    def __post_init__(self):
        _bounded_integer("input_tokens", self.input_tokens, maximum=1_000_000_000)
        _bounded_integer("output_tokens", self.output_tokens, maximum=1_000_000_000)
        _bounded_integer("elapsed_ms", self.elapsed_ms, maximum=86_400_000)
        if self.cost_microusd is not None:
            _bounded_integer(
                "cost_microusd", self.cost_microusd, maximum=1_000_000_000_000
            )

    def manifest(self):
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_ms": self.elapsed_ms,
            "cost_microusd": self.cost_microusd,
        }


@dataclass(frozen=True, slots=True)
class ProviderAssignment:
    provider: str
    model: str
    settings: Mapping[str, object]

    def __post_init__(self):
        _bounded_text("provider", self.provider)
        _bounded_text("model", self.model)
        settings = _json_copy(self.settings, "provider settings")
        if not isinstance(settings, dict):
            raise ValueError("provider settings must be an object")
        _reject_credential_settings(settings)
        object.__setattr__(self, "settings", MappingProxyType(settings))

    def manifest(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "settings": deepcopy(dict(self.settings)),
        }


def _usage_budget_violations(budget, usage):
    violations = []
    if usage.input_tokens > budget.max_input_tokens:
        violations.append("input token budget was exceeded")
    if usage.output_tokens > budget.max_output_tokens:
        violations.append("output token budget was exceeded")
    if usage.elapsed_ms > budget.timeout_ms:
        violations.append("time budget was exceeded")
    if budget.max_cost_microusd is not None:
        if usage.cost_microusd is None:
            violations.append("cost was not reported for a cost-bounded task")
        elif usage.cost_microusd > budget.max_cost_microusd:
            violations.append("cost budget was exceeded")
    return violations


class ProviderDecisionBatch:
    """Freeze equal-budget tasks and retain provider-neutral decision receipts."""

    def __init__(self, batch_id, epoch_id, turns, assignments, budget):
        _bounded_text("batch_id", batch_id)
        _bounded_text("epoch_id", epoch_id)
        if not isinstance(budget, DecisionBudget):
            raise TypeError("budget must be a DecisionBudget")
        if not isinstance(turns, dict) or not 2 <= len(turns) <= 16:
            raise ValueError("turns must contain 2-16 factions")
        if not isinstance(assignments, dict) or set(assignments) != set(turns):
            raise ValueError("assignments must exactly match turn factions")
        normalized_turns = {}
        normalized_assignments = {}
        for faction_id in sorted(turns):
            _bounded_integer("faction ID", faction_id, maximum=999_999)
            turn = _json_copy(turns[faction_id], f"faction {faction_id} turn")
            if not isinstance(turn, dict):
                raise ValueError("each faction turn must be an object")
            assignment = assignments[faction_id]
            if not isinstance(assignment, ProviderAssignment):
                raise TypeError("assignments must contain ProviderAssignment values")
            normalized_turns[faction_id] = turn
            normalized_assignments[faction_id] = assignment
        self.batch_id = batch_id
        self.epoch_id = epoch_id
        self.budget = budget
        self._turns = normalized_turns
        self._assignments = normalized_assignments
        self._records = {}
        self._turn_set_sha256 = _canonical_hash(normalized_turns)

    def tasks(self):
        return {
            faction_id: {
                "schema": "warband.agentic/provider-decision-task/v1",
                "task_id": f"{self.batch_id}:faction:{faction_id}",
                "batch_id": self.batch_id,
                "epoch_id": self.epoch_id,
                "faction_id": faction_id,
                "turn_set_sha256": self._turn_set_sha256,
                "turn": deepcopy(turn),
                "assignment": self._assignments[faction_id].manifest(),
                "budget": self.budget.manifest(),
            }
            for faction_id, turn in self._turns.items()
        }

    def record_success(self, faction_id, response, usage):
        self._require_known_faction(faction_id)
        if not isinstance(usage, DecisionUsage):
            raise TypeError("usage must be DecisionUsage")
        value = _json_copy(response, "provider decision response")
        if not isinstance(value, dict):
            raise ValueError("provider decision response must be an object")
        violations = self._budget_violations(usage)
        if violations:
            record = {
                "status": "budget-exceeded",
                "usage": usage.manifest(),
                "discarded_response_sha256": _canonical_hash(value),
                "detail": "; ".join(violations),
            }
            value = self._no_decision(faction_id)
        else:
            record = {
                "status": "success",
                "usage": usage.manifest(),
                "response_sha256": _canonical_hash(value),
                "detail": None,
            }
        return self._record(faction_id, record, value)

    def record_failure(self, faction_id, status, detail, usage=None):
        self._require_known_faction(faction_id)
        if status not in ("timeout", "provider-error", "cancelled"):
            raise ValueError("provider failure status is not supported")
        _bounded_text("provider failure detail", detail, maximum=500)
        if usage is not None and not isinstance(usage, DecisionUsage):
            raise TypeError("usage must be DecisionUsage or None")
        record = {
            "status": status,
            "usage": usage.manifest() if usage is not None else None,
            "detail": detail,
        }
        return self._record(faction_id, record, self._no_decision(faction_id))

    def decisions(self):
        self._require_complete()
        return {
            faction_id: deepcopy(self._records[faction_id][1])
            for faction_id in self._turns
        }

    def pending_faction_ids(self):
        """Return the sorted factions whose provider receipt is still missing."""
        return tuple(
            faction_id for faction_id in self._turns if faction_id not in self._records
        )

    def audit(self):
        self._require_complete()
        records = {
            str(faction_id): {
                "assignment": self._assignments[faction_id].manifest(),
                **deepcopy(self._records[faction_id][0]),
            }
            for faction_id in self._turns
        }
        usages = [
            record[0]["usage"]
            for record in self._records.values()
            if record[0]["usage"] is not None
        ]
        costs = [usage["cost_microusd"] for usage in usages]
        total = {
            "input_tokens": sum(usage["input_tokens"] for usage in usages),
            "output_tokens": sum(usage["output_tokens"] for usage in usages),
            "elapsed_ms_sum": sum(usage["elapsed_ms"] for usage in usages),
            "cost_microusd": (
                sum(costs)
                if len(usages) == len(self._records)
                and all(cost is not None for cost in costs)
                else None
            ),
        }
        body = {
            "schema": PROVIDER_DECISION_BATCH_SCHEMA,
            "batch_id": self.batch_id,
            "epoch_id": self.epoch_id,
            "status": "complete",
            "turn_set_sha256": self._turn_set_sha256,
            "budget": self.budget.manifest(),
            "records": records,
            "total_usage": total,
        }
        return {**body, "audit_sha256": _canonical_hash(body)}

    def checkpoint(self):
        """Return a checksummed partial batch without reissuing provider tasks."""
        payload = {
            "batch_id": self.batch_id,
            "epoch_id": self.epoch_id,
            "turn_set_sha256": self._turn_set_sha256,
            "turns": {
                str(faction_id): deepcopy(turn)
                for faction_id, turn in self._turns.items()
            },
            "assignments": {
                str(faction_id): assignment.manifest()
                for faction_id, assignment in self._assignments.items()
            },
            "budget": self.budget.manifest(),
            "records": {
                str(faction_id): {
                    "receipt": deepcopy(record),
                    "decision": deepcopy(decision),
                }
                for faction_id, (record, decision) in self._records.items()
            },
        }
        return {
            "schema": PROVIDER_DECISION_BATCH_CHECKPOINT_SCHEMA,
            "payload_sha256": _canonical_hash(payload),
            "payload": payload,
        }

    @classmethod
    def from_checkpoint(cls, wrapper):
        """Restore a partial provider batch and validate every retained receipt."""
        if not isinstance(wrapper, dict) or set(wrapper) != {
            "schema",
            "payload_sha256",
            "payload",
        }:
            raise ValueError("Invalid provider decision batch checkpoint fields")
        if wrapper["schema"] != PROVIDER_DECISION_BATCH_CHECKPOINT_SCHEMA:
            raise ValueError("Unsupported provider decision batch checkpoint schema")
        payload = wrapper["payload"]
        if not isinstance(payload, dict) or set(payload) != {
            "batch_id",
            "epoch_id",
            "turn_set_sha256",
            "turns",
            "assignments",
            "budget",
            "records",
        }:
            raise ValueError("Invalid provider decision batch checkpoint payload")
        checksum = wrapper["payload_sha256"]
        if not isinstance(checksum, str) or not hmac.compare_digest(
            checksum, _canonical_hash(payload)
        ):
            raise ValueError(
                "Provider decision batch checkpoint checksum does not match"
            )
        turns = cls._faction_map(payload["turns"], "turns")
        raw_assignments = cls._faction_map(payload["assignments"], "assignments")
        if set(raw_assignments) != set(turns):
            raise ValueError("Provider checkpoint assignments do not match turns")
        assignments = {}
        for faction_id, value in raw_assignments.items():
            if not isinstance(value, dict) or set(value) != {
                "provider",
                "model",
                "settings",
            }:
                raise ValueError("Provider checkpoint assignment is invalid")
            assignments[faction_id] = ProviderAssignment(**value)
        budget = payload["budget"]
        if not isinstance(budget, dict) or set(budget) != {
            "max_input_tokens",
            "max_output_tokens",
            "timeout_ms",
            "max_cost_microusd",
        }:
            raise ValueError("Provider checkpoint budget is invalid")
        batch = cls(
            payload["batch_id"],
            payload["epoch_id"],
            turns,
            assignments,
            DecisionBudget(**budget),
        )
        if payload["turn_set_sha256"] != batch._turn_set_sha256:
            raise ValueError("Provider checkpoint turn set hash does not match")
        records = cls._faction_map(payload["records"], "records", allow_empty=True)
        if not set(records).issubset(turns):
            raise ValueError("Provider checkpoint records contain another faction")
        for faction_id, item in records.items():
            batch._restore_record(faction_id, item)
        return batch

    def _require_known_faction(self, faction_id):
        if faction_id not in self._turns:
            raise ValueError("faction is not part of this decision batch")

    def _record(self, faction_id, record, response):
        candidate = (record, response)
        existing = self._records.get(faction_id)
        if existing is not None:
            if existing == candidate:
                return False
            raise ValueError("provider decision conflicts with the recorded result")
        self._records[faction_id] = candidate
        return True

    def _restore_record(self, faction_id, item):
        if not isinstance(item, dict) or set(item) != {"receipt", "decision"}:
            raise ValueError("Provider checkpoint record is invalid")
        receipt = item["receipt"]
        decision = item["decision"]
        if not isinstance(receipt, dict) or not isinstance(decision, dict):
            raise ValueError("Provider checkpoint receipt is invalid")
        status = receipt.get("status")
        usage_value = receipt.get("usage")
        usage = None
        if usage_value is not None:
            if not isinstance(usage_value, dict) or set(usage_value) != {
                "input_tokens",
                "output_tokens",
                "elapsed_ms",
                "cost_microusd",
            }:
                raise ValueError("Provider checkpoint usage is invalid")
            usage = DecisionUsage(**usage_value)
        common = {"status", "usage", "detail"}
        if status == "success":
            if (
                set(receipt) != common | {"response_sha256"}
                or usage is None
                or receipt["detail"] is not None
                or receipt["response_sha256"] != _canonical_hash(decision)
                or self._budget_violations(usage)
            ):
                raise ValueError("Provider checkpoint success receipt is invalid")
        elif status == "budget-exceeded":
            violations = self._budget_violations(usage) if usage is not None else []
            if (
                set(receipt) != common | {"discarded_response_sha256"}
                or not violations
                or receipt["detail"] != "; ".join(violations)
                or decision != self._no_decision(faction_id)
            ):
                raise ValueError("Provider checkpoint budget receipt is invalid")
        elif status in ("timeout", "provider-error", "cancelled"):
            if set(receipt) != common or decision != self._no_decision(faction_id):
                raise ValueError("Provider checkpoint failure receipt is invalid")
            _bounded_text("provider failure detail", receipt["detail"], maximum=500)
        else:
            raise ValueError("Provider checkpoint status is unsupported")
        self._record(faction_id, receipt, decision)

    def _budget_violations(self, usage):
        return _usage_budget_violations(self.budget, usage)

    def _no_decision(self, faction_id):
        return {"request_id": f"{self.batch_id}:faction:{faction_id}:no-decision"}

    def _require_complete(self):
        if set(self._records) != set(self._turns):
            raise RuntimeError("provider decision batch is incomplete")

    @staticmethod
    def _faction_map(value, label, *, allow_empty=False):
        if not isinstance(value, dict) or (not allow_empty and not value):
            raise ValueError(f"Provider checkpoint {label} must be an object")
        converted = {}
        for key, item in value.items():
            try:
                faction_id = int(key)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Provider checkpoint {label} has invalid faction IDs"
                ) from exc
            if str(faction_id) != key or faction_id in converted:
                raise ValueError(f"Provider checkpoint {label} has invalid faction IDs")
            converted[faction_id] = item
        return converted


def validate_provider_decision_audit(
    value,
    *,
    epoch_id,
    faction_ids,
    turn_set_sha256,
    decisions,
):
    """Strictly bind one provider audit to an epoch's turns and decisions."""
    audit = _json_copy(value, "provider decision audit")
    expected = {
        "schema",
        "batch_id",
        "epoch_id",
        "status",
        "turn_set_sha256",
        "budget",
        "records",
        "total_usage",
        "audit_sha256",
    }
    if not isinstance(audit, dict) or set(audit) != expected:
        raise ValueError("provider decision audit fields do not match")
    if audit["schema"] != PROVIDER_DECISION_BATCH_SCHEMA:
        raise ValueError("provider decision audit schema is unsupported")
    _bounded_text("provider batch_id", audit["batch_id"])
    if audit["epoch_id"] != epoch_id or audit["status"] != "complete":
        raise ValueError("provider decision audit does not match the resolved epoch")
    if audit["turn_set_sha256"] != turn_set_sha256:
        raise ValueError("provider decision audit turn set does not match")
    body = {key: item for key, item in audit.items() if key != "audit_sha256"}
    checksum = audit["audit_sha256"]
    if not isinstance(checksum, str) or not hmac.compare_digest(
        checksum, _canonical_hash(body)
    ):
        raise ValueError("provider decision audit checksum does not match")
    budget = audit["budget"]
    if not isinstance(budget, dict) or set(budget) != {
        "max_input_tokens",
        "max_output_tokens",
        "timeout_ms",
        "max_cost_microusd",
    }:
        raise ValueError("provider decision audit budget is invalid")
    budget_contract = DecisionBudget(**budget)
    expected_factions = tuple(sorted(faction_ids))
    records = audit["records"]
    if not isinstance(records, dict) or set(records) != {
        str(faction_id) for faction_id in expected_factions
    }:
        raise ValueError("provider decision audit factions do not match")
    if not isinstance(decisions, dict):
        raise ValueError("provider decision audit decisions do not match factions")
    try:
        decision_map = {int(key): item for key, item in decisions.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "provider decision audit decisions do not match factions"
        ) from exc
    if len(decision_map) != len(decisions) or set(decision_map) != set(
        expected_factions
    ):
        raise ValueError("provider decision audit decisions do not match factions")
    usages = []
    for faction_id in expected_factions:
        record = records[str(faction_id)]
        if not isinstance(record, dict):
            raise ValueError("provider decision audit record is invalid")
        common = {"assignment", "status", "usage", "detail"}
        status = record.get("status")
        usage_contract = None
        if status == "success":
            if set(record) != common | {"response_sha256"}:
                raise ValueError("successful provider decision audit is invalid")
            if record["detail"] is not None or record["usage"] is None:
                raise ValueError("successful provider decision receipt is incomplete")
            if record["response_sha256"] != _canonical_hash(decision_map[faction_id]):
                raise ValueError("provider response hash does not match the decision")
        elif status == "budget-exceeded":
            if set(record) != common | {"discarded_response_sha256"}:
                raise ValueError("over-budget provider decision audit is invalid")
            _bounded_text("budget violation detail", record["detail"], maximum=500)
            expected_decision = {
                "request_id": (f"{audit['batch_id']}:faction:{faction_id}:no-decision")
            }
            if decision_map[faction_id] != expected_decision:
                raise ValueError("over-budget provider result was not discarded")
        elif status in ("timeout", "provider-error", "cancelled"):
            if set(record) != common:
                raise ValueError("failed provider decision audit is invalid")
            _bounded_text("provider failure detail", record["detail"], maximum=500)
            expected_decision = {
                "request_id": (f"{audit['batch_id']}:faction:{faction_id}:no-decision")
            }
            if decision_map[faction_id] != expected_decision:
                raise ValueError("failed provider result is not a no-decision")
        else:
            raise ValueError("provider decision audit status is unsupported")
        assignment = record["assignment"]
        if not isinstance(assignment, dict) or set(assignment) != {
            "provider",
            "model",
            "settings",
        }:
            raise ValueError("provider assignment receipt is invalid")
        ProviderAssignment(**assignment)
        usage = record["usage"]
        if usage is not None:
            if not isinstance(usage, dict) or set(usage) != {
                "input_tokens",
                "output_tokens",
                "elapsed_ms",
                "cost_microusd",
            }:
                raise ValueError("provider usage receipt is invalid")
            usage_contract = DecisionUsage(**usage)
            usages.append(usage)
        violations = (
            _usage_budget_violations(budget_contract, usage_contract)
            if usage_contract is not None
            else []
        )
        if status == "success" and violations:
            raise ValueError("successful provider usage exceeds its declared budget")
        if status == "budget-exceeded" and (
            not violations or record["detail"] != "; ".join(violations)
        ):
            raise ValueError("provider budget-exceeded receipt is inconsistent")
    costs = [usage["cost_microusd"] for usage in usages]
    expected_total = {
        "input_tokens": sum(usage["input_tokens"] for usage in usages),
        "output_tokens": sum(usage["output_tokens"] for usage in usages),
        "elapsed_ms_sum": sum(usage["elapsed_ms"] for usage in usages),
        "cost_microusd": (
            sum(costs)
            if len(usages) == len(records) and all(cost is not None for cost in costs)
            else None
        ),
    }
    if audit["total_usage"] != expected_total:
        raise ValueError("provider decision audit totals do not match receipts")
    return audit
