# Python extension SDK

The extension SDK lets a trusted host launcher register constrained application
kinds without patching `warband-agent-host` or putting Python import paths in its
JSON configuration. It is a composition and review boundary, not a Python
sandbox: installed extension code runs in the host process and must be trusted.
The untrusted boundary remains each agent's constrained session and token.

An `AgenticExtension` declares:

- a stable extension ID, semantic version and description;
- compatible game protocol and integration-revision range;
- application kinds, validated settings schemas and supported roles;
- semantic capabilities and exact bridge-operation families used by each kind;
- host-level exclusive ownership derived from settings; and
- exact builder/runtime resource claims for collision detection.

`ExtensionRegistry.register()` atomically rejects duplicate extension IDs,
application kinds, incompatible protocol/revision ranges and colliding resource
claims. Its operator catalog contains declarations only—never factories,
credentials or live application objects.

## Register an application explicitly

Factories receive a `ScopedGameBackend`, session ID, shared semantic event log
and validated settings. They must return an object whose `session` is a
`ConstrainedAgentSession`; declared refresh support must match whether the object
provides `queue_observation_refresh()`.

```python
from bridge.agent_host import AgentApplicationHost, load_agent_host_plan
from bridge.application_extensions import built_in_extension_registry
from my_mod.agent_app import MyNpcApplication, extension_definition

registry = built_in_extension_registry()
registry.register(
    extension_definition,
    {"my-mod-npc": MyNpcApplication},
)

plan = load_agent_host_plan("/private/path/agent-host.json", registry)
AgentApplicationHost(plan).serve_forever()
```

An installed package can expose the same trusted bundle through standard Python
distribution metadata:

```toml
[project.entry-points."warband_agentic.extensions"]
"my.mod" = "my_mod.agent_app:extension_bundle"
```

The entry point must be a zero-argument callable returning `ExtensionBundle`.
Its entry-point name must exactly equal the bundle's declared extension ID. The
stock host never imports every discovered package: the operator explicitly names
each trusted extension to load.

```bash
warband-agent-host \
  --extension my.mod \
  --config /private/path/agent-host.json \
  --check
```

Missing, ambiguous, incompatible or malformed named extensions fail before
database creation or socket binding. Unnamed entry points are not imported.

The matching session configuration names only the registered kind and its
declared settings:

```json
{
  "kind": "my-mod-npc",
  "session_id": "village-elder",
  "token_file": "elder.token",
  "port": 8890,
  "agent_id": 7
}
```

The launcher—not JSON—chooses which Python code to import and trust. A missing or
extra setting fails plan validation before databases or sockets are created.
Exclusive ownership rules prevent two configured applications from claiming the
same player, party, NPC or extension-defined resource.

## Scoped game backend

Factories do not receive the raw bridge `Store`. `ScopedGameBackend` permits
telemetry/catalog reads and rejects queueing or reading commands outside the
application's declared operation families. The built-in declarations currently
use:

| Application kind | Allowed operations |
|---|---|
| `native-menu` | `select_menu` |
| `native-faction` | `world_query`, `party_order` |
| `native-npc-speech` | `scan_agents`, `npc_say` |

This constrains accidental authority and makes review concrete. It cannot contain
malicious installed Python, which already has process-level access; extensions
must therefore be installed and registered as trusted code.

The authenticated operator endpoint exposes the loaded declaration catalog:

```text
GET /v1/host/extensions
```

## Current limits

- The stock `warband-agent-host` CLI registers only `warband.native` 0.2.0 unless
  the operator supplies one or more explicit `--extension` IDs. There is no
  automatic package loading, runtime dynamic loading or hot reload.
- The SDK composes applications over existing reviewed bridge operation families.
  It does not yet compile new ModSys handlers, allocate slots/registers/globals or
  merge new callback seams; declarations can reserve those resource names for
  future builder integration, but that is structural metadata only.
- Broad compatibility with other Warband modules is not implied. The current
  protocol/revision target remains the generated revision-16 Native module.
