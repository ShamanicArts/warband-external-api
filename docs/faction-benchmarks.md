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

Controlled party IDs must be disjoint across applications. An overlap fails at
construction rather than making first-response timing determine authority.
Invalid decisions do not erase other factions' records; the transcript preserves
the deterministic partial commit honestly.

The caller supplies JSON `run_metadata`. A real benchmark should include module
and save hashes, scenario seed, model/provider/version/settings, token and time
budgets, pricing/cost, timeout policy and runner version. The epoch transcript
contains the exact filtered turns, turn-set hash, submitted responses, validation
errors and refreshed outcomes. It never contains the private application objects.

This is not yet the full benchmark harness. The next layer must pause/advance a
real campaign by fixed game time, stop rest safely, capture checkpoints, derive
scenario metrics, persist transcripts atomically, resume interrupted runs, and
schedule providers under equal budgets. External model runs still require the
user-visible preflight notice described in the design specification.
