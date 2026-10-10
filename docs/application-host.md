# Packaged agent application host

`warband-agent-host` owns one game bridge, one durable semantic event log, a
trusted operator control listener and one authenticated constrained HTTP listener
per configured application. The stock CLI packages four built-in application
kinds, including one-shot NPC speech and persistent NPC dialogue, without giving
agents bridge credentials or requiring handwritten Python composition. Trusted
custom launchers can explicitly supply an extension
registry as documented in [the extension SDK guide](extension-sdk.md).
Installed extensions can alternatively be selected by exact ID with repeated
`--extension` arguments; discovery alone never imports them.

The versioned example is
[`config/agent-host.example.json`](../config/agent-host.example.json). Relative
paths resolve from the configuration file, not the caller's working directory.

## Validate before binding

Create every database parent directory and every token file first. Tokens must
contain 64 lowercase hexadecimal characters, have no group/other permissions and
be distinct for the game bridge, operator control, voice service and every agent
session. Host-config v2 adds the authenticated loopback voice relay; v1 remains
accepted as a handoff-only compatibility format.

```bash
mkdir -p runtime
chmod 700 runtime
warband-agent-host --config config/agent-host.example.json --check
```

Check mode reads and validates configuration, tokens, module catalog and
`mcp-build.json`; it does not create databases or bind sockets. It requires
protocol 2 and integration revision 16, rejects port collisions, duplicate
session IDs, more than one player-menu controller, and overlapping faction-party
or NPC-agent ownership. Its JSON diagnostics contain no paths, tokens, private
command IDs or handler names.
For v2 it also validates an exact `http://127.0.0.1:<port>/v1/voice/speech`
endpoint, bounded timeout and distinct private token without contacting or
starting the voice service.
It also requires the build manifest to provide the exact ID/version of every
loaded extension marked as needing compiled module support. If any loaded bundle
declares compiled operations, their full manifests must also exactly match the
generated module; a version match alone is not accepted.

## Run

```bash
warband-agent-host --config /private/path/agent-host.json
```

The bridge and control listeners bind immediately to `127.0.0.1`. The host reports
`waiting-for-game` until valid protocol-2 telemetry arrives, then constructs the
configured registered applications and binds their individual constrained-agent
listeners. Startup is fail-closed: all session sockets must bind before the host
reports `ready`.

Each agent uses only its own session token and the standard endpoints documented
in [the constrained interface](constrained-agent-api.md). The separate operator
token can read safe lifecycle diagnostics:

```text
GET /v1/host/diagnostics
GET /v1/host/extensions
```

The extension endpoint returns compatible declarations and safe resource claims,
not Python factories, paths, tokens or live application objects.

For an in-process benchmark only, `benchmark_bindings()` accepts the validated
faction-to-session map and returns the shared Store plus exactly those matching
faction applications. It is unavailable until the host is ready and rejects
unknown, duplicate or faction-mismatched sessions. This trusted seam is consumed
by [`warband-benchmark-run`](benchmark-runner.md); it is never exposed over HTTP.

Faction and NPC observations require explicit fresh engine reads. A trusted host
or benchmark runner queues them without exposing bridge command IDs:

```text
POST /v1/host/sessions/{session_id}/refresh
```

The refresh request has an empty body and returns only the session ID and queued
job count. Player-menu sessions derive their view directly from current telemetry
and reject explicit refresh. Agents do not receive the operator token.

`native-npc-dialogue` sessions also accept one bounded player line from a trusted
local integration:

```text
POST /v1/host/sessions/{session_id}/utterances
```

The exact JSON body is `{"utterance_id":"...","text":"..."}` and is capped at
2048 transport bytes. This endpoint uses the operator token, not the NPC agent's
token. See [the NPC dialogue guide](npc-speech.md) for sequencing and evidence
boundaries.

After an NPC response reaches engine-observed state, a trusted integration can
request its deterministic voice payload:

```text
POST /v1/host/sessions/{session_id}/voice-requests
```

The exact body contains `action_request_id`, `profile_id`, `delivery` and
`speed`. The response is a provider-neutral `SpeechRequest` ready for
`POST /v1/voice/speech`.

With host-config v2, the same trusted caller can request the complete relay:

```text
POST /v1/host/sessions/{session_id}/voice-dispatches
```

The host creates the same engine-evidence-gated request, authenticates to the
separate loopback voice service and validates its bounded terminal outcome. The
response reports request/correlation IDs, state, optional audio ID and error. A
voice failure is reported but never changes or rolls back the dialogue outcome.
The voice token stays in host memory and is never accepted from a request body or
returned in diagnostics.

`native-npc-speech` and `native-npc-dialogue` sessions may instead include an
`automatic_voice` object containing a trusted `profile_id`, `delivery` and
`speed`. This is accepted only with host-config v2 and a configured voice
service. Once Warband observation is reconciled, the host sends one deduplicated
request on a separate worker; synthesis/playback never blocks the action response.
Runtime diagnostics show configured automatic sessions and bounded status counts,
without tokens, provider settings, text or audio data.

Normal interruption closes every owned HTTP server, joins its threads, and closes
both SQLite connections. It never starts Warband, Wine, Gamescope, a voice model
or an external agent.

## Current limits

- The application set is static for one host process; there is no hot reload.
- The stock CLI loads four reviewed built-in kinds by default. Operators
  may explicitly select installed entry-point extensions by ID, but there is no
  automatic loading or hot reload; JSON never names an import path.
- Refresh scheduling is explicit host/runner policy. The host does not silently
  choose faction decision epochs or repeatedly scan an NPC scene.
- Voice remains a separately authenticated process. Manual or automatic v2 relay
  owns only its loopback credential and bounded HTTP client; it does not co-host
  TTS.
- Automatic dispatch deduplicates repeated reconciliation in one host process.
  Its pending queue/status is not yet a durable restart-recovered outbox.
- The listeners are plaintext loopback interfaces; remote exposure is unsupported.
- Runtime lifecycle is bridge-simulated. A live hardware-rendered multi-session
  acceptance run and final video evidence are still pending.
