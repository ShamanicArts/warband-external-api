# Faction benchmark plans

`warband-benchmark --config PLAN --check` validates one complete Native faction
benchmark plan without creating databases, binding sockets, launching Warband or
calling a model. The packaged [`benchmark.example.json`](../config/benchmark.example.json)
is paired with the packaged host example; replace its paths, IDs, hashes and
provider adapter names for a real scenario.

The `warband.agentic/benchmark-plan/v1` document binds:

- one already-valid application-host plan;
- a versioned `BenchmarkScenario` and its exact faction set;
- one distinct faction-sovereign host session per participant;
- public provider/model/settings assignments with credential-like keys refused;
- one equal `DecisionBudget` for every participant;
- Native campaign epoch count, hours and speed;
- unique settlement party IDs used by metric collection; and
- finite run metadata containing module/save SHA-256 values, scenario seed and
  runner version.

The current plan compiler targets `CampaignMetricCollector`, so the scenario must
declare exactly `active_world_parties`, `military_strength`, `settlements` and
`surviving`. A future collector extension needs a new explicit plan schema or
collector declaration; silently accepting metrics that the runtime cannot emit
would only defer failure until report generation.

Check output is a secret-free `warband.agentic/benchmark-plan-check/v1` summary.
It includes scenario, participant provider/model identities, public settings,
epoch bounds, budget and a hash of run metadata. It omits token values, token-file
paths, database paths and raw metadata. Host-plan validation still verifies token
permissions, module protocol/revision and extension inventory, but check mode
does not open any runtime resource.

This command is deliberately check-only. It does not start the application host,
capture a save, dispatch provider tasks or drive an epoch. Actual model execution
still requires the user-visible preflight naming models, scope, expected cost and
runtime, and evaluation criteria.
