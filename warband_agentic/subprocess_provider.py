"""Bounded non-shell subprocess dispatch for provider decision tasks."""

import json
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from warband_agentic.provider_decisions import (
    DecisionUsage,
    ProviderDecisionBatch,
)

SUBPROCESS_PROVIDER_RESULT_SCHEMA = "warband.agentic/subprocess-provider-result/v1"
SUBPROCESS_DISPATCH_STATUS_SCHEMA = "warband.agentic/subprocess-dispatch-status/v1"
_OUTPUT_LIMIT = 256 * 1024


@dataclass(frozen=True, slots=True)
class SubprocessProviderAdapter:
    """One explicit argv and in-memory environment for a provider wrapper."""

    argv: tuple[str, ...] = field(repr=False)
    environment: Mapping[str, str] = field(repr=False)

    def __post_init__(self):
        argv = tuple(self.argv)
        if not 1 <= len(argv) <= 64:
            raise ValueError("provider adapter argv must contain 1-64 values")
        for value in argv:
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 4096
                or "\x00" in value
            ):
                raise ValueError("provider adapter argv contains an invalid value")
        if not isinstance(self.environment, Mapping):
            raise TypeError("provider adapter environment must be a mapping")
        environment = {}
        for key, value in self.environment.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > 256
                or "=" in key
                or "\x00" in key
                or not isinstance(value, str)
                or len(value) > 16_384
                or "\x00" in value
            ):
                raise ValueError("provider adapter environment is invalid")
            environment[key] = value
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "environment", MappingProxyType(environment))


@dataclass(slots=True)
class _RunningAdapter:
    process: subprocess.Popen
    started_ns: int
    input_file: object
    output_file: object


class SubprocessDecisionDispatcher:
    """Start all missing provider tasks and poll without blocking the game host."""

    def __init__(self, batch, adapters, *, clock_ns=None):
        if not isinstance(batch, ProviderDecisionBatch):
            raise TypeError("batch must be a ProviderDecisionBatch")
        if not isinstance(adapters, dict):
            raise TypeError("adapters must be a provider-to-adapter mapping")
        normalized = {}
        for provider, adapter in adapters.items():
            if not isinstance(provider, str) or not provider:
                raise ValueError("adapter provider names must be non-empty strings")
            if not isinstance(adapter, SubprocessProviderAdapter):
                raise TypeError(
                    "adapters must contain SubprocessProviderAdapter values"
                )
            normalized[provider] = adapter
        self.batch = batch
        self._adapters = normalized
        self._clock_ns = clock_ns or time.monotonic_ns
        self._state = "created"
        self._running = {}

    def start(self):
        if self._state != "created":
            raise RuntimeError("subprocess decision dispatch was already started")
        self._state = "running"
        tasks = self.batch.tasks()
        for faction_id in self.batch.pending_faction_ids():
            task = tasks[faction_id]
            provider = task["assignment"]["provider"]
            adapter = self._adapters.get(provider)
            if adapter is None:
                self.batch.record_failure(
                    faction_id,
                    "provider-error",
                    "No subprocess adapter is configured for this provider",
                )
                continue
            encoded = json.dumps(
                task,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            process = None
            input_file = None
            output_file = None
            try:
                input_file = tempfile.TemporaryFile()
                input_file.write(encoded)
                input_file.seek(0)
                output_file = tempfile.TemporaryFile()
                started_ns = self._now()
                process = subprocess.Popen(
                    adapter.argv,
                    stdin=input_file,
                    stdout=output_file,
                    stderr=subprocess.DEVNULL,
                    env=dict(adapter.environment),
                    shell=False,
                    start_new_session=True,
                )
                self._running[faction_id] = _RunningAdapter(
                    process,
                    started_ns,
                    input_file,
                    output_file,
                )
            except (OSError, BrokenPipeError) as exc:
                if process is not None:
                    self._terminate(process)
                if input_file is not None:
                    input_file.close()
                if output_file is not None:
                    output_file.close()
                self.batch.record_failure(
                    faction_id,
                    "provider-error",
                    f"Adapter process could not start: {type(exc).__name__}",
                )
        self._finish_if_complete()
        return self.status()

    def poll(self):
        if self._state == "created":
            raise RuntimeError("subprocess decision dispatch has not started")
        if self._state in ("complete", "closed"):
            return self.status()
        now_ns = self._now()
        timeout_ms = self.batch.budget.timeout_ms
        for faction_id, running in tuple(self._running.items()):
            elapsed_ms = max(0, (now_ns - running.started_ns) // 1_000_000)
            return_code = running.process.poll()
            output_size = os.fstat(running.output_file.fileno()).st_size
            if output_size > _OUTPUT_LIMIT:
                self._terminate(running.process)
                self.batch.record_failure(
                    faction_id,
                    "provider-error",
                    "Adapter result exceeded the 256 KiB output limit",
                    DecisionUsage(0, 0, elapsed_ms, None),
                )
            elif return_code is None and elapsed_ms < timeout_ms:
                continue
            elif return_code is None or elapsed_ms > timeout_ms:
                self._terminate(running.process)
                self.batch.record_failure(
                    faction_id,
                    "timeout",
                    "Adapter process exceeded the equal task deadline",
                    DecisionUsage(0, 0, elapsed_ms, None),
                )
            else:
                self._record_process_result(
                    faction_id,
                    running.process,
                    running.output_file,
                    return_code,
                    elapsed_ms,
                )
            running.input_file.close()
            running.output_file.close()
            self._running.pop(faction_id)
        self._finish_if_complete()
        return self.status()

    def status(self):
        return {
            "schema": SUBPROCESS_DISPATCH_STATUS_SCHEMA,
            "state": self._state,
            "batch_id": self.batch.batch_id,
            "pending_factions": list(self.batch.pending_faction_ids()),
            "running_factions": sorted(self._running),
        }

    def close(self):
        if self._state == "closed":
            return self.status()
        for faction_id, running in tuple(self._running.items()):
            elapsed_ms = max(0, (self._now() - running.started_ns) // 1_000_000)
            self._terminate(running.process)
            running.input_file.close()
            running.output_file.close()
            self.batch.record_failure(
                faction_id,
                "cancelled",
                "Subprocess decision dispatch was closed by the host",
                DecisionUsage(0, 0, elapsed_ms, None),
            )
            self._running.pop(faction_id)
        self._state = "closed"
        return self.status()

    def _record_process_result(
        self, faction_id, process, output_file, return_code, elapsed_ms
    ):
        output_file.seek(0)
        output = output_file.read(_OUTPUT_LIMIT + 1)
        if return_code != 0:
            self.batch.record_failure(
                faction_id,
                "provider-error",
                "Adapter process returned a non-zero exit status",
                DecisionUsage(0, 0, elapsed_ms, None),
            )
            return
        if len(output) > _OUTPUT_LIMIT:
            self.batch.record_failure(
                faction_id,
                "provider-error",
                "Adapter result exceeded the 256 KiB output limit",
                DecisionUsage(0, 0, elapsed_ms, None),
            )
            return
        try:
            value = json.loads(output)
            if not isinstance(value, dict) or set(value) != {
                "schema",
                "response",
                "usage",
            }:
                raise ValueError("result fields do not match")
            if value["schema"] != SUBPROCESS_PROVIDER_RESULT_SCHEMA:
                raise ValueError("result schema does not match")
            usage = value["usage"]
            if not isinstance(usage, dict) or set(usage) != {
                "input_tokens",
                "output_tokens",
                "cost_microusd",
            }:
                raise ValueError("usage fields do not match")
            receipt = DecisionUsage(
                usage["input_tokens"],
                usage["output_tokens"],
                elapsed_ms,
                usage["cost_microusd"],
            )
            self.batch.record_success(faction_id, value["response"], receipt)
        except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.batch.record_failure(
                faction_id,
                "provider-error",
                f"Adapter result was invalid: {type(exc).__name__}",
                DecisionUsage(0, 0, elapsed_ms, None),
            )

    @staticmethod
    def _terminate(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            os.killpg(process.pid, signal.SIGKILL)
            if process.poll() is None:
                process.wait(timeout=1)

    def _finish_if_complete(self):
        if not self._running and not self.batch.pending_faction_ids():
            self._state = "complete"

    def _now(self):
        value = self._clock_ns()
        if type(value) is not int or value < 0:
            raise ValueError("clock_ns must return a non-negative integer")
        return value
