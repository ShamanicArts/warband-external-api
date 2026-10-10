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

## OpenCode and ShelfCode

`warband-provider-opencode` is the first provider-specific wrapper. It supports
the current ShelfCode/OpenCode v2 CLI by default and legacy OpenCode v1 through
`--dialect v1`. The v2 form is suitable for catalog IDs such as
`opencode/muse-spark-1.3-contributor-free`; a plan's optional `variant` setting is
placed in the v2 model reference. The v1 form passes the variant as a separate
CLI flag. Any other public provider setting is rejected before a child starts.

Each call uses a fresh empty temporary game-work directory. V2 attaches to the
already registered local ShelfCode service, creates one session with the chosen
model and a session-level deny-all permission rule, prompts it, waits, reads the
final assistant message and deletes the session. Cancellation first requests an
interrupt/delete before the dispatcher's process-group kill grace expires. V1
runs a private CLI process with a local deny-all agent profile and plugins
disabled. Both forms disable automatic sharing/updating and ask for exactly one
constrained response object.

The wrapper accepts only provider-reported message/step usage. Input usage
includes cache reads/writes and output usage includes reasoning, so the benchmark
errs conservatively. Provider-reported USD cost is converted to integer
microdollars; an unavailable cost remains `null` and therefore fails any non-null
cost cap in the benchmark core. Missing token usage, malformed output, a stale
revision, unknown affordance or another task's request ID fails closed; the
wrapper never invents a receipt.

Example adapter entry:

```json
{
  "provider": "opencode-v2",
  "argv": [
    "/installed/bin/warband-provider-opencode",
    "--executable", "/installed/bin/shuvcode",
    "--assignment-provider", "opencode-v2",
    "--dialect", "v2"
  ],
  "pass_environment": ["HOME", "PATH"]
}
```

Add credential or endpoint variable names to `pass_environment` only when the
chosen OpenCode provider needs them. The loader requires every named variable to
exist. V2 also requires the selected model to exist in the attached service's
catalog. The benchmark dispatcher now starts each wrapper in its own process group;
deadline and cancellation cleanup terminate the wrapper and its provider CLI
together instead of orphaning an inference process. A host crash after provider
acceptance but before receipt persistence can still duplicate a call because the
CLI does not expose a portable request-id idempotency primitive.

An inert local-service probe has verified v2 session creation, empty-context
reading and deletion with the real CLI, including path-parameter handling. It sent
no prompt and performed no inference. Prompt completion, the experimental wait
route and usage extraction remain deliberately unverified against a real model
until the required model-run preflight is presented to the operator.

Cursor's documented headless JSON result currently omits token and cost usage, so
it is not yet wired into the equal-budget runner. Treating guessed counts as
provider receipts would make the benchmark look fair when it is not. Cursor/Grok
remains a wrapper gap rather than a fake implementation.
