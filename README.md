# Warband Agentic Kit (working name)

This project is growing from a game-script-backed MCP bridge into a
provider-neutral agentic modding and scripting kit for Mount & Blade: Warband.
The target architecture is in [the draft design spec](docs/design/spec.md); the
currently proven game integration and its honest limitations are in [MCP.md](MCP.md).

Current foundations include:

- a vanilla-safe Native-derived build using authenticated loopback HTTP;
- real campaign, menu, mission, actor, battle, trade and Native-dialogue seams;
- durable catalog-validated events for committed Native dialogue entries;
- transport-neutral `warband.agentic/v1` contracts for actors, contexts,
  observations, facts, affordances, actions, evidence, roles and control leases;
- role-scoped capability discovery plus expiring, context-bound, single-use
  affordance validation with internal handlers hidden from agents;
- an authenticated [constrained agent API](docs/constrained-agent-api.md) that
  keeps actor/grant/lease/handler identity server-owned and exposes filtered
  turns, bounded submissions, outcomes and session-safe event cursors;
- a production Native-menu application that derives exact-session affordances
  from live bridge telemetry, queues validated selections and reconciles public
  outcomes against Warband acknowledgements without exposing bridge command IDs;
- a [faction-sovereign application](docs/faction-agent.md) that refreshes real
  party facts, verifies faction ownership, leases controlled parties and turns
  reviewed orders into engine-observed outcomes without exposing world control;
- a constrained [NPC speech application](docs/npc-speech.md) that binds one
  freshly scanned scene agent to bounded dialogue, then creates an optional host
  voice request only after Warband reports the utterance, plus a durable
  host-fed player/NPC conversation loop for later in-game text or speech input;
- a trusted [Python extension SDK](docs/extension-sdk.md) with versioned
  declarations, collision checks, validated settings, explicit factories and
  scoped access to reviewed game-operation families, including exact-ID installed
  extension loading and bounded declarative Module System handlers without
  automatic imports;
- trusted control-lease arbitration and role/context/source-filtered observations
  that report omissions without leaking hidden facts;
- semantic adapters for canonical engine observations, committed dialogue events,
  exact-session Native menu attempts, faction party orders and bounded NPC speech;
- a versioned durable semantic event log with strict decoding, ordered cursors,
  source idempotency and honest migration of terminal command/dialogue history;
- an authenticated, loopback-only [host voice service](docs/voice.md) with named
  public profiles, a local Kokoro adapter, optional PipeWire playback, lifecycle
  events and bounded audio retrieval;
- a deterministic [restricted-agent usability fixture](docs/agent-usability.md)
  for later announced cross-model interface tests;
- a provider-neutral [synchronized faction epoch](docs/faction-benchmarks.md)
  that enforces disjoint party control, equal campaign-time turns, deterministic
  commit order, bounded engine-clock advancement, evidence-gated scenario scoring
  and atomic hashed epoch/run artifacts, plus a fixed-clock campaign metric
  collector and restart-safe non-blocking full-epoch orchestration harness,
  with equal-budget provider task/audit contracts but without embedding or
  invoking models;
- a [GPU-safe off-screen test harness](bridge/CUA_RUNBOOK.md) that pins Gamescope
  to a physical AMD GPU, isolates CUA from the desktop, enforces systemd resource
  limits and refuses software rendering or missing game-process GPU proof;
- reproducible tests and retained engine/visual evidence.

The current evidence index and final video ledger live in
[docs/evidence-report.md](docs/evidence-report.md).

## Installable toolkit

The current Python package is `warband-agentic-kit` 0.2.0. A development install
provides six commands:

```bash
uv sync
uv run warband-game-bridge --help
uv run warband-agent-host --help
uv run warband-build-module --help
uv run warband-mcp
uv run warband-voice --help
uv run warband-agent-usability --help
```

See [the packaging guide](docs/packaging.md) for reproducible sdist-to-wheel
builds and isolated Native module generation. See the
[application-host guide](docs/application-host.md) for validated multi-session
runtime startup and the [extension SDK guide](docs/extension-sdk.md) for explicit
custom application registration. The repository is
not ready for public release yet: no project license has been selected, and
fresh-install/live acceptance plus final video evidence remain open.

MCP is one adapter, not the core product boundary. CUA is used only for isolated
launch and independent visual validation, never as an invisible game backend.

## Legacy prototype (reference only)

The following describes the earlier incomplete file-I/O prototype. Its builder
must not be run against working Native, Pendor, or the new WarbandMCP module.

Bridge between Mount & Blade: Warband and external systems (AI agents, LLMs, simulation engines).

## Architecture

```
Warband Mod → file I/O → Bridge Daemon → WebSocket → Agent
    (simple_triggers)    (Python inotify)            (skills)
```

## Structure

- `module/` — Warband module files (compiled .txt format for Native-based module)
- `bridge/` — Python daemon that reads/writes the shared files
- `skills/` — Agent-facing skill files documenting the API surface

## Quick Start

1. Symlink module into Warband:
   ```
   ln -s /home/shamanic/dev/mods/warband-external-api/module \
         /home/shamanic/.local/share/Steam/steamapps/common/MountBlade\ Warband/Modules/ExternalAPI
   ```

2. Browse to Modules directory, verify ExternalAPI shows up.

3. Launch Warband, select ExternalAPI module, start a game.

4. In another terminal:
   ```
   python3 bridge/warband_bridge.py
   ```

5. See state flowing out.
