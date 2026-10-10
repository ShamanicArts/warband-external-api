# Synchronized faction benchmark epochs

`warband_agentic.benchmark.SynchronizedFactionEpoch` is the provider-neutral
decision-epoch core for multi-faction experiments. It coordinates two or more
`NativeFactionAgentApplication` instances without invoking a model, advancing
game time or embedding provider-specific code.

An epoch performs four explicit phases:

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

After decisions are committed, `write_checkpoint(path)` atomically persists a
checksummed coordinator checkpoint. `load_checkpoint(path, applications)`
restores the exact turn set, decisions and latest records, verifies the turn hash
and faction set, and relies on each constrained session's durable action recovery.
It never calls `submit`. Deliberately, refreshing and collecting states are not
resumable: their observation jobs and affordance tokens are time-sensitive and
must not be presented as safely durable.

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

This is not yet the full benchmark harness. The next layer must orchestrate the
driver and metric collector against a live campaign, capture save/checkpoints,
resume from a game save when the game process itself is lost, and schedule
providers under equal budgets. External
model runs still require the user-visible preflight notice described in the design
specification.
