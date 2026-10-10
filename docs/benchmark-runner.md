# Non-blocking benchmark runner

`bridge.benchmark_runner.FactionBenchmarkRunner` is the runtime composition seam
between a validated `FactionBenchmarkPlan`, an initialized
`FactionBenchmarkHarness`, and provider adapters. It does not own a sleep loop,
start the application host, launch Warband, load a save or call a model during
construction. A trusted outer process supplies those resources and calls
`start()` once followed by bounded `poll()` calls.

Each poll advances at most one runner boundary:

1. baseline or post-epoch metric collection;
2. deterministic epoch creation;
3. synchronized turn collection once engine refreshes are complete;
4. equal-budget provider dispatch and receipt collection;
5. action resolution or bounded campaign advancement; or
6. final report generation after the configured epoch count.

`NativeFactionAgentApplication` reports an incomplete engine observation with
the typed `AgentPending` signal. The runner treats that as ordinary waiting and
does not turn it into a failed or fabricated turn. Other errors remain visible to
the caller.

When `checkpoint_path` is configured, every safe state is atomically persisted:
ready, awaiting decisions, resolving actions, advancing the campaign and
collecting post-epoch metrics. During provider dispatch, each poll therefore
captures newly completed receipts. Recovery is explicit:

```python
harness = FactionBenchmarkHarness.load_checkpoint(
    checkpoint_path,
    store,
    faction_applications,
)
runner = FactionBenchmarkRunner(
    plan,
    harness,
    adapters,
    checkpoint_path=checkpoint_path,
    report_path=report_path,
)
```

On its next poll the runner creates a dispatcher over the restored batch, whose
`pending_faction_ids()` excludes every persisted receipt. Stable task IDs should
still be forwarded as provider idempotency keys because no local checkpoint can
eliminate the crash window after a remote service accepts a request but before
its receipt reaches durable storage.

`close()` terminates any active subprocess dispatcher and persists its audited
cancellations without advancing game time. A completed or interrupted runner is
already terminal and `close()` leaves that result intact. The status object
contains only run/epoch progress and the subprocess dispatcher's secret-free
status; argv, environment, process IDs and provider output stay private.

The current integration tests use deterministic fake engine adapters and tiny
local dispatch fixtures. They prove runner sequencing, typed pending behavior,
automatic partial-receipt checkpoints and missing-only restart. They do not prove
a live Warband run or any provider-specific wrapper. Before a real model run, the
operator must receive the required preflight naming models, scope, expected
cost/runtime and evaluation criteria.

## Preflight-gated live command

`warband-benchmark-run` supplies the outer host loop while preserving the
side-effect-free `warband-benchmark --check` command. It never launches Warband;
the operator connects a campaign instance separately using the GPU-safe runbook.

Execution is deliberately two-step. First inspect the exact models, factions,
epoch/game-time scope, provider-call count, token/time/cost limits and scoring
metrics:

```bash
warband-benchmark-run \
  --config benchmark.json \
  --adapter-config provider-adapters.json \
  --preflight
```

The output contains `confirmation_sha256`. Execution refuses to open host
databases, bind listeners or start wrappers unless the current hash is supplied:

```bash
warband-benchmark-run \
  --config benchmark.json \
  --adapter-config provider-adapters.json \
  --execute \
  --acknowledge-preflight HASH_FROM_PREVIOUS_COMMAND \
  --checkpoint benchmark.checkpoint.json \
  --report benchmark.report.json
```

Use `--resume` only with an existing checkpoint. New runs refuse existing
checkpoint or report targets, and resumed runs refuse an existing final report.
Host readiness and total wall time have bounded configurable deadlines. On
completion, interruption, timeout or Ctrl-C, active provider children are
closed and the application host releases its loopback listeners and databases.
