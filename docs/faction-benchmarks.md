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

This is not yet the full benchmark harness. The next layer must orchestrate the
driver against a live campaign, capture save/checkpoints, derive scenario metrics,
resume from a game save when the game process itself is lost, and schedule
providers under equal budgets. External
model runs still require the user-visible preflight notice described in the design
specification.
