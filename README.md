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
- reproducible tests and retained engine/visual evidence.

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
