"""Collect engine-evidenced faction metrics while campaign time is held fixed."""

from dataclasses import dataclass
from enum import StrEnum

from warband_agentic import (
    Evidence,
    EvidenceLevel,
    FactionMetricSnapshot,
    MetricObservation,
)

COLLECTION_STATUS_SCHEMA = "warband.agentic/metric-collection-status/v1"


class CampaignMetricCollectionState(StrEnum):
    CREATED = "created"
    COLLECTING = "collecting"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class CampaignMetricCollectionStatus:
    state: CampaignMetricCollectionState
    snapshot_id: str
    game_time: int | None
    pages_complete: int
    faction_queries_complete: int
    reason: str | None
    schema: str = COLLECTION_STATUS_SCHEMA


class CampaignMetricCollector:
    """Page world parties and faction state without allowing game-time drift."""

    def __init__(self, store, snapshot_id, *, faction_ids, settlement_party_ids):
        for name in ("snapshot", "enqueue_operation", "command", "world_result"):
            if not callable(getattr(store, name, None)):
                raise TypeError(f"store must provide {name}()")
        campaign = getattr(store, "campaign", None)
        if not callable(getattr(campaign, "result", None)):
            raise TypeError("store must provide campaign result reads")
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise ValueError("snapshot_id must be a non-empty string")
        factions = tuple(sorted(faction_ids))
        if not 2 <= len(factions) <= 16 or any(
            type(faction_id) is not int or not 0 <= faction_id < 1_000_000
            for faction_id in factions
        ):
            raise ValueError("faction_ids must contain 2-16 bounded integers")
        if len(factions) != len(set(factions)):
            raise ValueError("faction_ids must be unique")
        settlements = tuple(sorted(settlement_party_ids))
        if not 1 <= len(settlements) <= 4096 or any(
            type(party_id) is not int or not 0 <= party_id < 1_000_000
            for party_id in settlements
        ):
            raise ValueError("settlement_party_ids must contain bounded integers")
        if len(settlements) != len(set(settlements)):
            raise ValueError("settlement_party_ids must be unique")
        self.store = store
        self.snapshot_id = snapshot_id
        self.faction_ids = factions
        self.settlement_party_ids = frozenset(settlements)
        self.state = CampaignMetricCollectionState.CREATED
        self._game_time = None
        self._reason = None
        self._page_command_id = None
        self._page_offset = 0
        self._page_total = None
        self._pages_complete = 0
        self._rows = {}
        self._faction_command_ids = {}
        self._faction_facts = {}
        self._metric_snapshot = None

    def begin(self):
        if self.state is not CampaignMetricCollectionState.CREATED:
            raise RuntimeError("campaign metric collection was already started")
        snapshot = self._campaign_snapshot()
        self._game_time = snapshot["clock"]
        try:
            self._queue_page(0)
            for index, faction_id in enumerate(self.faction_ids):
                other_id = self.faction_ids[(index + 1) % len(self.faction_ids)]
                command = self.store.enqueue_operation(
                    "world_query",
                    {
                        "entity": "faction",
                        "entity_id": faction_id,
                        "other_id": other_id,
                    },
                )
                self._faction_command_ids[faction_id] = command["id"]
        except Exception as exc:
            self._interrupt(f"Cannot queue metric reads: {type(exc).__name__}")
            raise
        self.state = CampaignMetricCollectionState.COLLECTING
        return self._status()

    def status(self):
        if self.state is CampaignMetricCollectionState.CREATED:
            raise RuntimeError("campaign metric collection has not started")
        if self.state in (
            CampaignMetricCollectionState.COMPLETE,
            CampaignMetricCollectionState.INTERRUPTED,
        ):
            return self._status()
        try:
            snapshot = self._campaign_snapshot()
            if snapshot["clock"] != self._game_time:
                self._interrupt("Campaign clock changed during metric collection")
                return self._status()
            self._read_current_page()
            self._read_faction_results()
            if (
                self._page_command_id is None
                and len(self._faction_facts) == len(self.faction_ids)
            ):
                self._metric_snapshot = self._build_snapshot()
                self.state = CampaignMetricCollectionState.COMPLETE
        except Exception as exc:
            self._interrupt(f"Metric collection failed: {type(exc).__name__}: {exc}")
        return self._status()

    def snapshot(self):
        if self.state is not CampaignMetricCollectionState.COMPLETE:
            raise RuntimeError("campaign metric collection is not complete")
        return self._metric_snapshot

    def _campaign_snapshot(self):
        snapshot = self.store.snapshot()
        if (
            not snapshot.get("connected")
            or snapshot.get("protocol") != 2
            or snapshot.get("context") != "campaign"
            or type(snapshot.get("clock")) is not int
            or snapshot["clock"] < 0
            or snapshot.get("integration_revision", 0) < 8
        ):
            raise ValueError(
                "metric collection requires live revision-8+ campaign telemetry"
            )
        return snapshot

    def _queue_page(self, offset):
        command = self.store.enqueue_operation(
            "scan_campaign",
            {"dataset": "world_parties", "offset": offset, "limit": 16},
        )
        self._page_command_id = command["id"]
        self._page_offset = offset

    def _read_current_page(self):
        if self._page_command_id is None:
            return
        command = self.store.command(self._page_command_id)
        if command["status"] in ("rejected", "expired", "interrupted"):
            raise RuntimeError("world-party export command did not complete")
        page = self.store.campaign.result(self._page_command_id)
        if not page.get("complete"):
            return
        if page.get("stale"):
            raise RuntimeError("world-party export page is stale")
        if (
            page.get("dataset") != "world_parties"
            or page.get("offset") != self._page_offset
            or page.get("limit") != 16
            or type(page.get("total")) is not int
            or page["total"] < 0
        ):
            raise ValueError("world-party export page metadata is invalid")
        if self._page_total is None:
            self._page_total = page["total"]
        elif page["total"] != self._page_total:
            raise ValueError("world-party total changed between pages")
        for row in page["rows"]:
            party_id = row.get("party_id")
            if party_id in self._rows:
                raise ValueError("world-party rows overlap between pages")
            if (
                type(party_id) is not int
                or type(row.get("faction_id")) is not int
                or type(row.get("members")) is not int
                or row["members"] < 0
            ):
                raise ValueError("world-party row is invalid")
            self._rows[party_id] = row
        self._pages_complete += 1
        next_offset = page.get("next_offset")
        if next_offset is None:
            if len(self._rows) != self._page_total:
                raise ValueError("world-party export ended before its declared total")
            self._page_command_id = None
            return
        if (
            type(next_offset) is not int
            or next_offset != self._page_offset + len(page["rows"])
            or next_offset <= self._page_offset
            or next_offset >= self._page_total
        ):
            raise ValueError("world-party pagination is inconsistent")
        self._queue_page(next_offset)

    def _read_faction_results(self):
        for faction_id, command_id in self._faction_command_ids.items():
            if faction_id in self._faction_facts:
                continue
            command = self.store.command(command_id)
            if command["status"] in ("rejected", "expired", "interrupted"):
                raise RuntimeError("faction metric query did not complete")
            result = self.store.world_result(command_id)
            if not result.get("complete"):
                continue
            facts = result.get("facts", {})
            if (
                facts.get("entity") != "faction"
                or facts.get("faction_id") != faction_id
                or type(facts.get("state")) is not int
            ):
                raise ValueError("faction metric result is invalid")
            self._faction_facts[faction_id] = facts

    def _build_snapshot(self):
        page_evidence = Evidence(
            EvidenceLevel.ENGINE_OBSERVED,
            "Warband world_parties campaign export",
            (
                f"{self._pages_complete} complete pages and {len(self._rows)} active "
                f"parties while integer campaign clock remained {self._game_time}; "
                "pages are separately captured, not one atomic engine callback"
            ),
        )
        observations = {}
        for faction_id in self.faction_ids:
            rows = [
                row
                for row in self._rows.values()
                if row["faction_id"] == faction_id
            ]
            state = self._faction_facts[faction_id]["state"]
            state_evidence = Evidence(
                EvidenceLevel.ENGINE_OBSERVED,
                "Warband faction state getter",
                f"Faction {faction_id} Native state slot read as {state}",
            )
            observations[faction_id] = (
                MetricObservation(
                    "active_world_parties", len(rows), page_evidence
                ),
                MetricObservation(
                    "military_strength",
                    sum(row["members"] for row in rows),
                    page_evidence,
                ),
                MetricObservation(
                    "settlements",
                    sum(
                        row["party_id"] in self.settlement_party_ids for row in rows
                    ),
                    page_evidence,
                ),
                MetricObservation("surviving", state == 0, state_evidence),
            )
        return FactionMetricSnapshot(
            self.snapshot_id, self._game_time, observations
        )

    def _interrupt(self, reason):
        self.state = CampaignMetricCollectionState.INTERRUPTED
        self._reason = reason

    def _status(self):
        return CampaignMetricCollectionStatus(
            self.state,
            self.snapshot_id,
            self._game_time,
            self._pages_complete,
            len(self._faction_facts),
            self._reason,
        )
