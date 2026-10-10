# Packaged agent application host

`warband-agent-host` owns one game bridge, one durable semantic event log, a
trusted operator control listener and one authenticated constrained HTTP listener
per configured application. It packages the three built-in reference
applications without giving agents bridge credentials or requiring handwritten
Python composition.

The versioned example is
[`config/agent-host.example.json`](../config/agent-host.example.json). Relative
paths resolve from the configuration file, not the caller's working directory.

## Validate before binding

Create every database parent directory and every token file first. Tokens must
contain 64 lowercase hexadecimal characters, have no group/other permissions and
be distinct for the game bridge, operator control and every agent session.

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

## Run

```bash
warband-agent-host --config /private/path/agent-host.json
```

The bridge and control listeners bind immediately to `127.0.0.1`. The host reports
`waiting-for-game` until valid protocol-2 telemetry arrives, then constructs the
configured built-in applications and binds their individual constrained-agent
listeners. Startup is fail-closed: all session sockets must bind before the host
reports `ready`.

Each agent uses only its own session token and the standard endpoints documented
in [the constrained interface](constrained-agent-api.md). The separate operator
token can read safe lifecycle diagnostics:

```text
GET /v1/host/diagnostics
```

Faction and NPC observations require explicit fresh engine reads. A trusted host
or benchmark runner queues them without exposing bridge command IDs:

```text
POST /v1/host/sessions/{session_id}/refresh
```

The refresh request has an empty body and returns only the session ID and queued
job count. Player-menu sessions derive their view directly from current telemetry
and reject explicit refresh. Agents do not receive the operator token.

Normal interruption closes every owned HTTP server, joins its threads, and closes
both SQLite connections. It never starts Warband, Wine, Gamescope, a voice model
or an external agent.

## Current limits

- The application set is static for one host process; there is no hot reload.
- Only the three reviewed built-in application kinds are loadable. Third-party
  extension discovery remains an SDK milestone, not arbitrary Python import.
- Refresh scheduling is explicit host/runner policy. The host does not silently
  choose faction decision epochs or repeatedly scan an NPC scene.
- Voice remains a separately authenticated host process. It is not co-hosted.
- The listeners are plaintext loopback interfaces; remote exposure is unsupported.
- Runtime lifecycle is bridge-simulated. A live hardware-rendered multi-session
  acceptance run and final video evidence are still pending.
