# Provider adapters

The core never imports a model SDK. `SubprocessDecisionDispatcher` is the first
concrete adapter for executing a `ProviderDecisionBatch` through trusted local
wrapper programs while keeping the benchmark contract provider-neutral.

Each `SubprocessProviderAdapter` contains an argv tuple and an explicit in-memory
environment. Dispatch uses `shell=False`; no command string is interpreted by a
shell. The environment is not written into tasks, checkpoints, audits or
diagnostics. Adapter processes are still trusted code with the user's filesystem
and network authority—this is process lifecycle isolation, not a security
sandbox.

The dispatcher starts every missing faction task before the host begins polling.
One canonical `provider-decision-task/v1` JSON object is supplied on stdin. The
wrapper writes exactly one bounded object on stdout:

```json
{
  "schema": "warband.agentic/subprocess-provider-result/v1",
  "response": {
    "request_id": "decision:15",
    "affordance_token": "opaque",
    "arguments": {},
    "expected_revision": 7
  },
  "usage": {
    "input_tokens": 900,
    "output_tokens": 80,
    "cost_microusd": 3500
  }
}
```

Elapsed time is measured by the host rather than trusted from the wrapper. The
dispatcher is non-blocking after `start()`: the host calls `poll()`, and each call
checks completion and the common task deadline. A child still running at the
deadline is killed and recorded as a timeout. Non-zero exit, malformed JSON,
wrong schema or output crossing 256 KiB becomes a provider-error receipt
without retaining stdout or stderr. Anonymous temporary output storage prevents
pipe deadlock, and polling stops a writer after it crosses the limit. `close()`
kills and records cancellation for every remaining child.

Restored partial batches expose only missing faction IDs, so completed provider
calls are not reissued. Different provider names can map to different argv/env
adapters in the same batch. Credentials belong only in the adapter's in-memory
environment or its own external credential mechanism; they must never appear in
the benchmark plan's public settings.

`bridge.provider_adapter_config.load_subprocess_adapter_config()` loads the
versioned `subprocess-adapters/v1` document used by the live runner. Each entry
contains a provider name, explicit argv and a list of environment-variable names
to pass. Relative executables resolve against the configuration directory and
must be executable files. Credential-like argv flags are rejected; values are
read only from the named environment variables. Adapter reprs and check
diagnostics omit argv, environment names and values. The packaged
`provider-adapters.example.json` is a template and its placeholder executables
must be replaced before use.

The repository tests concurrency, valid receipts and hard timeout cleanup with
tiny local Python subprocesses. They do not invoke a model, provider API, BB
agent, Warband or voice service. Before any real model run, the operator must
receive the required preflight naming models, scope, expected cost/runtime and
evaluation criteria.
