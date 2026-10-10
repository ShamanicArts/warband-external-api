# Packaging and local installation

The Python distribution is named `warband-agentic-kit`. It contains the semantic
runtime, bridge applications, Native module builder, MCP adapter, host voice
service and declarative Python extension SDK. It intentionally contains no Native
assets, generated module, save,
database, token or evidence artifact.

## Development install

From a checkout:

```bash
uv sync
uv run warband-game-bridge --help
uv run warband-agent-host --help
uv run warband-build-module --help
uv run warband-voice --help
uv run warband-agent-usability --help
uv run warband-benchmark --help
uv run warband-benchmark-run --help
uv run warband-provider-opencode --help
uv run warband-kit-install --help
```

The MCP command is `uv run warband-mcp`. It uses stdio and expects
`WARBAND_TOKEN_FILE`; `WARBAND_BRIDGE_URL` defaults to
`http://127.0.0.1:8765`.

## Reproducible artifact build

Build the wheel from the source distribution, not from an old local `build/`
directory:

```bash
uv build --sdist --out-dir dist
uv build --wheel --out-dir dist dist/warband_agentic_kit-0.2.0.tar.gz
```

`test_packaging.py` repeats that path, checks the locked project metadata and
artifact contents, installs the wheel into a temporary location, imports the
runtime outside the checkout, and starts every non-MCP command through `--help`.
The wheel also carries the host, benchmark, provider-adapter and voice example
JSON under `share/warband-agentic-kit/examples`.
The current host example uses host-config v2 and therefore needs a distinct
private `voice.token` matching the separately started `warband-voice` service.
Legacy v1 host configs remain valid and expose voice handoff without the relay.

## Guided private install

The installed `warband-kit-install` command has a deterministic, agent-friendly
interface. `plan` is target-read-only and prints a secret-free JSON plan. `apply`
builds a new module from the user's own Native installation, creates a private
runtime/configuration root, validates the generated module/host contract and
prints a secret-free receipt:

```bash
warband-kit-install plan \
  --native /path/to/Modules/Native \
  --install-root /private/path/warband-agentic

warband-kit-install apply \
  --native /path/to/Modules/Native \
  --install-root /private/path/warband-agentic
```

The default module destination is the new sibling `Modules/WarbandMCP`; use
`--module-output` to select another new path. Both final paths and their parents
are validated before work starts. Apply stages the module and private root,
claims only previously absent destinations, and rolls back its own outputs when
validation fails. It never modifies Native, an existing output or an MCP client.

The private root contains four distinct mode-0600 credentials, a host config with
one restricted `native-menu` starter session, a configurable local Kokoro voice
service, an MCP stdio server snippet, a secret-free install manifest and explicit
launch instructions. Add NPC and faction sessions only after selecting real live
agent/party IDs and reviewed order options. Playback defaults to disabled; pass
`--voice-playback pipewire` only when host audio playback is wanted.

Vanilla Warband always sends HTTP to loopback port 80. Unless `--bridge-port 80`
is selected, the receipt honestly reports that the operator must route
`127.0.0.1:80` to the chosen bridge port. The installer does not request root,
change firewall policy or create a privileged forwarder. MCP registration remains
manual because client configuration formats and trust policies differ.

The retained installed-wheel, rollback and real-Native acceptance evidence is in
`evidence/packaging/`. Hardware-rendered boot of a fresh installer-generated
module is retained separately in `evidence/runtime/installer-generated-boot/`.

## Build an isolated game module

The builder copies a user-owned Native module and instruments the copy. The
output path must not already exist and must not be inside the source Native
directory.

```bash
warband-build-module \
  --native /path/to/Modules/Native \
  --output /path/to/Modules/WarbandMCP \
  --token-file /private/path/warband.token

warband-game-bridge \
  --token-file /private/path/warband.token \
  --database /private/path/warband.sqlite \
  --catalog /path/to/Modules/WarbandMCP/mcp-catalog.json
```

Create the token with `warband-game-bridge --create-token` only when the target
file does not exist. Keep the token, generated module, database and saves private.
The bridge binds to loopback. Use the GPU-safe runbook for any agent-initiated
game launch; software rendering is forbidden.
The generated build manifest inventories `warband.native` 0.2.0. Application-host
validation compares that inventory to loaded module-required extensions before
opening either runtime database or any listener.

## Current release blockers

- No project license has been selected. Public distribution is blocked until the
  license and referenced-source/dependency terms are resolved.
- The Python artifact, built-in multi-session host and fail-closed guided installer
  are reproducible. MCP-client registration remains deliberately manual.
- Explicit Python extension registration and exact-ID installed entry-point
  loading are packaged. Automatic loading, new compiled-handler generation and
  hot reload are not.
- Hardware-rendered boot from an installer-generated module is proven. Exact-window
  unfocused input reaches main-menu hover but not activation, so live bridge
  connectivity, semantic interaction evidence and final video clips remain open.
