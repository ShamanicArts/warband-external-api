"""Bounded Native campaign-time advancement for synchronized benchmark epochs."""

from dataclasses import dataclass
from enum import StrEnum


class CampaignAdvanceState(StrEnum):
    STARTING = "starting"
    ADVANCING = "advancing"
    TARGET_REACHED = "target-reached"
    STOPPING = "stopping"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CampaignAdvanceStatus:
    epoch_id: str
    state: CampaignAdvanceState
    start_clock: int
    target_clock: int
    current_clock: int | None
    elapsed_hours: int | None
    target_reached: bool
    start_command_status: str
    stop_command_status: str | None
    stop_acknowledged: bool
    reason: str | None = None


class CampaignEpochDriver:
    """Drive one bounded Native rest interval and prove its explicit stop."""

    def __init__(self, store, epoch_id):
        for name in ("snapshot", "enqueue_operation", "command"):
            if not callable(getattr(store, name, None)):
                raise TypeError(f"store must provide {name}()")
        if not isinstance(epoch_id, str) or not epoch_id.strip():
            raise ValueError("epoch_id must be a non-empty string")
        self.store = store
        self.epoch_id = epoch_id
        self._start_clock = None
        self._target_clock = None
        self._start_command_id = None
        self._stop_command_id = None

    def begin(self, *, hours, speed):
        if self._start_command_id is not None:
            raise RuntimeError("campaign epoch advance was already started")
        if type(hours) is not int or not 1 <= hours <= 24:
            raise ValueError("hours must be an integer from 1 through 24")
        if type(speed) is not int or not 1 <= speed <= 5:
            raise ValueError("speed must be an integer from 1 through 5")
        snapshot = self._campaign_snapshot()
        clock = snapshot.get("clock")
        if type(clock) is not int or clock < 0:
            raise ValueError("campaign telemetry has no valid engine clock")
        command = self.store.enqueue_operation(
            "campaign_wait", {"hours": hours, "speed": speed}
        )
        self._start_clock = clock
        self._target_clock = clock + hours
        self._start_command_id = command["id"]
        return self.status()

    def request_stop(self):
        status = self.status()
        if self._stop_command_id is not None:
            return status
        if status.state is not CampaignAdvanceState.TARGET_REACHED:
            raise RuntimeError("campaign epoch cannot stop before its target")
        self._campaign_snapshot()
        command = self.store.enqueue_operation(
            "campaign_wait", {"hours": 0, "speed": 1}
        )
        self._stop_command_id = command["id"]
        return self.status()

    def status(self):
        if self._start_command_id is None:
            raise RuntimeError("campaign epoch advance has not started")
        snapshot = self.store.snapshot()
        start = self.store.command(self._start_command_id)
        current_clock = snapshot.get("clock")
        valid_clock = type(current_clock) is int and current_clock >= 0
        elapsed = current_clock - self._start_clock if valid_clock else None
        reached = valid_clock and current_clock >= self._target_clock
        stop_status = None
        stop_acknowledged = False
        if self._stop_command_id is not None:
            stop = self.store.command(self._stop_command_id)
            stop_status = stop["status"]
            stop_acknowledged = stop_status == "acknowledged"

        state = CampaignAdvanceState.STARTING
        reason = None
        if not snapshot.get("connected"):
            state = CampaignAdvanceState.INTERRUPTED
            reason = "Game telemetry became stale or disconnected"
        elif snapshot.get("context") != "campaign":
            state = CampaignAdvanceState.INTERRUPTED
            reason = f"Campaign advance entered {snapshot.get('context')} context"
        elif start["status"] in ("rejected", "expired", "interrupted"):
            state = CampaignAdvanceState.FAILED
            reason = f"Campaign wait command became {start['status']}"
        elif self._stop_command_id is not None:
            if stop_acknowledged and reached:
                state = CampaignAdvanceState.COMPLETE
            elif stop_status in ("rejected", "expired", "interrupted"):
                state = CampaignAdvanceState.FAILED
                reason = f"Campaign stop command became {stop_status}"
            else:
                state = CampaignAdvanceState.STOPPING
        elif reached:
            state = CampaignAdvanceState.TARGET_REACHED
        elif start["status"] in ("dispatched", "acknowledged"):
            state = CampaignAdvanceState.ADVANCING

        return CampaignAdvanceStatus(
            self.epoch_id,
            state,
            self._start_clock,
            self._target_clock,
            current_clock if valid_clock else None,
            elapsed,
            reached,
            start["status"],
            stop_status,
            stop_acknowledged,
            reason,
        )

    def _campaign_snapshot(self):
        snapshot = self.store.snapshot()
        if (
            not snapshot.get("connected")
            or snapshot.get("protocol") != 2
            or snapshot.get("context") != "campaign"
        ):
            raise ValueError(
                "Epoch advancement requires live protocol-2 campaign telemetry"
            )
        if snapshot.get("player_is_captive"):
            raise ValueError("Epoch advancement is unavailable while captive")
        return snapshot
