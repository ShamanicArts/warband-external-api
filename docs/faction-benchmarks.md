# Synchronized faction benchmark epochs

`warband_agentic.benchmark.SynchronizedFactionEpoch` is the provider-neutral
decision-epoch core for multi-faction experiments. It coordinates two or more
`NativeFactionAgentApplication` instances without invoking a model, advancing
game time or embedding provider-specific code.

An epoch performs five explicit phases:

1. Queue fresh engine party observations for every faction in sorted faction-ID
   order.
2. Collect role-filtered turns only when all participants share one campaign
   scope and exact game time.
3. Freeze and SHA-256 hash the public turn set, then accept exactly one response
   per faction.
4. Commit submissions in faction-ID order and retain accepted outcomes plus
   invalid/rejected decision errors in the transcript.
5. Resolve every accepted action, run a matching `CampaignEpochDriver` interval,
   and attach its engine-clock plus acknowledged-stop proof.

Controlled party IDs must be disjoint across applications. An overlap fails at
construction rather than making first-response timing determine authority.
Invalid decisions do not erase other factions' records; the transcript preserves
the deterministic partial commit honestly.

The caller supplies JSON `run_metadata`. A real benchmark should include module
and save hashes, scenario seed, model/provider/version/settings, token and time
budgets, pricing/cost, timeout policy and runner version. The epoch transcript
contains the exact filtered turns, turn-set hash, submitted responses, validation
errors, refreshed outcomes and campaign advance. It never contains the private
application objects. `write_transcript(path)` atomically replaces one canonical
JSON artifact only after the epoch is resolved and its fixed-time advance is
complete.

After the synchronized turn set is frozen, `write_checkpoint(path)` atomically
persists a checksummed coordinator checkpoint. Before commitment,
`load_checkpoint(path, applications)` restores that exact turn set so provider
work can continue without recollecting it. After commitment it also restores the
decisions and latest records, verifies the turn hash and faction set, and relies
on each constrained session's durable action recovery. It never calls `submit`.
The earlier refresh-job phase remains non-resumable because the engine reads may
still be pending and no synchronized turn has been proven yet.

`bridge.campaign_epoch_driver.CampaignEpochDriver` starts bounded Native
`rest_for_hours_interactive`, distinguishes command acknowledgement from elapsed
time, compares live engine clock against the epoch target, and queues an explicit
zero-hour stop. Completion requires both target-clock evidence and an acknowledged
stop. A menu/encounter transition or stale telemetry is interruption, not success.
`checkpoint()` records the existing wait/stop command IDs and engine-clock bounds;
`CampaignEpochDriver.restore()` validates those commands against the Store before
continuing. Restoring either a pending wait or pending stop does not enqueue a
replacement. Hosts should atomically retain the committed epoch checkpoint and,
once time advancement begins, the latest driver checkpoint.

## Scenario metrics and scored run artifacts

`BenchmarkScenario` makes scoring policy explicit and versioned. Every
`MetricRule` names a unit, positive weight and one of three objectives:

- `maximize` — reward an increase from the baseline;
- `minimize` — reward a decrease from the baseline; or
- `binary` — award its weight when the final engine fact is true.

Continuous changes are divided by the declared positive scale and clamped to
`[-1, 1]` before multiplying by the weight. Binary metrics score either zero or
their weight. This keeps every component bounded while still allowing losses to
produce negative points. Ties receive the same rank and faction ID is the stable
display-order tiebreaker. There is deliberately no universal definition of a
good Warband faction: settlement, strength, survival and objective weights belong
to the named scenario and version.

`FactionMetricSnapshot` accepts only finite numeric/boolean observations carrying
`engine-observed` or stronger evidence. Baseline and final snapshots must contain
the exact scenario faction and metric sets. The resulting scorecard retains both
values, delta, normalized component, points and evidence for every metric, plus a
SHA-256 hash over the scenario and input snapshots.

`bridge.campaign_metric_collector.CampaignMetricCollector` supplies the first
production-Store adapter for those snapshots. A trusted runner starts it only
after campaign time has stopped. It pages the omniscient `world_parties` engine
export and queries each configured Native faction state while requiring live
protocol-2 campaign context and the same integer game clock throughout. It emits:

- `active_world_parties`: every active exported party assigned to the faction;
- `military_strength`: the sum of their engine member counts, including centers
  and garrisons rather than pretending this is field-army-only strength;
- `settlements`: ownership among the scenario-supplied settlement party IDs; and
- `surviving`: whether the Native faction-state slot is zero (active).

Incomplete/stale pages, changing totals, duplicate rows, failed faction getters,
context transition or clock drift interrupt collection and produce no metric
snapshot. Progress status exposes counts but not bridge command IDs. The retained
evidence explicitly says that pages are separately captured while the integer
clock remains fixed; this is not falsely labelled one atomic engine callback.

`FactionBenchmarkRun` binds one baseline, one or more complete resolved epoch
transcripts and an evidenced metric snapshot after each fixed-time advance. It
revalidates faction coverage, run metadata, turn-set content hash, monotonic game
time, target/stop proof and clock arithmetic rather than trusting a transcript's
`resolved` label. `write_report(path)` atomically emits one canonical run artifact
containing the scenario, metadata, exact epoch records, metric snapshots, final
scorecard and report hash. Calling `report()` finalizes the run against later
mutation.

## Non-blocking live-run harness

`bridge.faction_benchmark_harness.FactionBenchmarkHarness` composes the pieces
above into one provider-neutral state machine. It collects an evidenced baseline,
freezes an equal-time turn set, accepts one externally obtained decision per
faction, resolves every accepted action, advances and explicitly stops the
campaign clock, collects post-epoch metrics, and appends the validated epoch to a
scored run. `finalize()` freezes the canonical report; `write_report(path)` uses
the run artifact's atomic writer.

The harness does not own a busy loop. A host pumps Warband telemetry and calls
`poll()`; each call advances at most one orchestration step. Turn collection and
decision submission are explicit boundaries, so provider latency cannot advance
game time. A metric-collection interruption or failed/interrupted clock advance
puts the harness in an honest terminal `interrupted` state instead of inventing a
baseline, result, or score.

An unfinished `FactionBenchmarkRun` can emit and restore a checksummed checkpoint;
restore strictly rebuilds its scenario and engine-evidenced metric objects and
revalidates every retained epoch. The harness wraps that state together with the
active epoch and clock-driver checkpoints in one atomically replaced document.
Safe restore points are: ready between epochs, awaiting decisions over a frozen
turn set, resolving committed actions, advancing an already-started clock
interval, and post-advance metrics. The awaiting-decisions checkpoint may embed
a checksummed partial `ProviderDecisionBatch`; completed receipts survive and
only missing factions remain dispatchable. Restore never resubmits decisions or
starts a replacement wait. Post-advance recovery may restart the read-only
fixed-clock metric scan. Baseline collection and incomplete refresh jobs remain
intentionally non-resumable.

The [non-blocking runner](benchmark-runner.md) now composes these phases and
automatically persists every safe state. Remaining work is host/CLI wiring,
provider-specific wrappers, game-supported save capture and process-loss
recovery. The SHA-256 fields detect corruption and inconsistency; they are not
signatures against a malicious local editor. External model runs still require
the user-visible preflight notice described in the design specification.

## Equal-budget provider handoff and audit

`warband_agentic.ProviderDecisionBatch` freezes one task per faction from the
exact synchronized turn set. Every task carries the same `DecisionBudget` limits
for input tokens, output tokens, elapsed time and optional micro-US-dollar cost,
while `ProviderAssignment` records the provider, model and public inference
settings. Credential-like settings are refused so tokens and API keys cannot leak
into tasks, checkpoints or reports.

Provider adapters execute outside the core and report a bounded `DecisionUsage`.
An answer that exceeds any declared limit is discarded. Timeout, provider-error
and cancellation receipts become explicit no-decisions, allowing the other
factions' records to commit without fabricating an answer. Exact retry receipts
are idempotent; conflicting reuse fails closed. The completed audit retains
assignments, statuses, response hashes and reported token/time/cost usage, and is
SHA-256-bound to the frozen turn set.

A partially completed batch has its own checksummed checkpoint. Restore retains
finished receipts and frozen tasks, so a host can resume only the missing provider
calls without intentionally reissuing completed work. Binding that batch to the
harness carries its checkpoint inside the same atomic awaiting-decisions
artifact. A hard crash between a remote provider accepting a request and the host
persisting its receipt can still duplicate a call, so wrappers should use the
stable task ID as their provider idempotency key. Frozen turns also do not make
affordance tokens valid indefinitely; the host must finish before their declared
expiry.

`FactionBenchmarkHarness.submit_provider_batch()` binds that audit to the active
epoch before committing decisions. Canonical `benchmark-run/v2` reports retain
the validated audit beside each epoch's transcript and metrics. Raw/manual
decision submission remains supported and produces a `null` provider audit.
Identical caps are not a claim that different tokenizers, pricing schemes or
hardware have identical semantics; the actual reported usage remains visible.

The first [subprocess provider adapter](provider-adapters.md) concurrently starts
trusted local wrappers, polls without blocking the game host and hard-kills calls
at the common deadline. Provider-specific authentication and request translation
remain inside those wrappers. No external model was invoked while implementing or
testing this contract.

The check-only [`warband-benchmark`](benchmark-plan.md) command compiles a
versioned plan against the referenced application-host configuration before any
runtime side effect. It catches faction/session mismatches, metric sets the Native
collector cannot produce, unsafe provider settings, missing reproducibility
metadata and invalid epoch/budget bounds. Live execution is intentionally not
claimed by that command yet.
