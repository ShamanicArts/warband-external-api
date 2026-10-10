"""Explicit preflight-gated CLI for live faction benchmark execution."""

import argparse
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

from bridge.agent_host import AgentApplicationHost
from bridge.benchmark_plan import load_faction_benchmark_plan
from bridge.benchmark_runner import build_host_benchmark_runner
from bridge.provider_adapter_config import load_subprocess_adapter_config

BENCHMARK_EXECUTION_PREFLIGHT_SCHEMA = (
    "warband.agentic/benchmark-execution-preflight/v1"
)
BENCHMARK_EXECUTION_RESULT_SCHEMA = "warband.agentic/benchmark-execution-result/v1"


def _canonical_hash(value):
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def benchmark_execution_preflight(plan, adapter_registry):
    """Return the exact secret-free scope that an operator must acknowledge."""
    participants = [
        {
            "faction_id": participant.faction_id,
            "provider": participant.assignment.provider,
            "model": participant.assignment.model,
            "settings": participant.assignment.manifest()["settings"],
        }
        for participant in plan.participants
    ]
    provider_calls = plan.epoch_count * len(participants)
    maximum_cost = (
        None
        if plan.budget.max_cost_microusd is None
        else plan.budget.max_cost_microusd * provider_calls
    )
    body = {
        "schema": BENCHMARK_EXECUTION_PREFLIGHT_SCHEMA,
        "run_id": plan.run_id,
        "participants": participants,
        "scope": {
            "scenario_id": plan.scenario.scenario_id,
            "scenario_version": plan.scenario.version,
            "epochs": plan.epoch_count,
            "game_hours_per_epoch": plan.epoch_hours,
            "total_game_hours": plan.epoch_count * plan.epoch_hours,
            "provider_calls": provider_calls,
        },
        "limits": {
            **plan.budget.manifest(),
            "maximum_run_cost_microusd": maximum_cost,
        },
        "evaluation": [
            {
                "metric": metric.key,
                "objective": metric.objective.value,
                "weight": metric.weight,
            }
            for metric in plan.scenario.metrics
        ],
        "adapter_providers": adapter_registry.diagnostics()["providers"],
        "runtime": {
            "launches_warband": False,
            "requires_connected_campaign": True,
            "provider_deadline_ms_per_epoch": plan.budget.timeout_ms,
            "wall_time_depends_on_game_and_provider_latency": True,
        },
    }
    return {**body, "confirmation_sha256": _canonical_hash(body)}


def run_host_benchmark(
    plan,
    adapters,
    *,
    checkpoint_path,
    report_path,
    resume,
    host_ready_timeout,
    runtime_timeout,
    poll_interval,
    host_factory=AgentApplicationHost,
    runner_builder=build_host_benchmark_runner,
    clock=time.monotonic,
    sleeper=time.sleep,
):
    """Run against a separately connected game; never launch Warband itself."""
    host = host_factory(plan.host)
    runner = None
    started_at = clock()
    try:
        host.start()
        if not host.wait_until_ready(timeout=host_ready_timeout):
            raise RuntimeError(
                "application host did not receive a ready campaign connection"
            )
        runner = runner_builder(
            plan,
            host,
            adapters,
            checkpoint_path=checkpoint_path,
            report_path=report_path,
            resume=resume,
        )
        if runner.status().state == "created":
            runner.start()
        while True:
            status = runner.poll()
            if status.state == "complete":
                return runner.report()
            if status.state == "interrupted":
                raise RuntimeError(status.reason or "benchmark run was interrupted")
            if clock() - started_at >= runtime_timeout:
                raise RuntimeError("benchmark run exceeded its wall-time limit")
            sleeper(poll_interval)
    finally:
        if runner is not None:
            runner.close()
        host.stop()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--adapter-config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--acknowledge-preflight")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--host-ready-timeout", type=float, default=300.0)
    parser.add_argument("--runtime-timeout", type=float, default=21_600.0)
    parser.add_argument("--poll-interval", type=float, default=0.05)
    args = parser.parse_args(argv)
    try:
        plan = load_faction_benchmark_plan(args.config)
        registry = load_subprocess_adapter_config(
            args.adapter_config,
            required_providers={
                participant.assignment.provider for participant in plan.participants
            },
        )
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    preflight = benchmark_execution_preflight(plan, registry)
    if args.preflight:
        json.dump(preflight, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.checkpoint is None or args.report is None:
        parser.error("--execute requires --checkpoint and --report")
    if args.acknowledge_preflight is None or not hmac.compare_digest(
        args.acknowledge_preflight,
        preflight["confirmation_sha256"],
    ):
        parser.error(
            "--execute requires the confirmation hash from a current --preflight"
        )
    if not 1 <= args.host_ready_timeout <= 3600:
        parser.error("--host-ready-timeout must be from 1 through 3600 seconds")
    if not 1 <= args.runtime_timeout <= 86_400:
        parser.error("--runtime-timeout must be from 1 through 86400 seconds")
    if not 0.01 <= args.poll_interval <= 1:
        parser.error("--poll-interval must be from 0.01 through 1 second")
    try:
        report = run_host_benchmark(
            plan,
            dict(registry.adapters),
            checkpoint_path=args.checkpoint,
            report_path=args.report,
            resume=args.resume,
            host_ready_timeout=args.host_ready_timeout,
            runtime_timeout=args.runtime_timeout,
            poll_interval=args.poll_interval,
        )
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    json.dump(
        {
            "schema": BENCHMARK_EXECUTION_RESULT_SCHEMA,
            "status": "complete",
            "run_id": report["run_id"],
            "epoch_count": report["epoch_count"],
            "report_sha256": report["report_sha256"],
        },
        sys.stdout,
        indent=2,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
