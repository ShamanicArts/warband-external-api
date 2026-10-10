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
The wheel also carries the host and voice example JSON under
`share/warband-agentic-kit/examples`.

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

## Current release blockers

- No project license has been selected. Public distribution is blocked until the
  license and referenced-source/dependency terms are resolved.
- The Python artifact and built-in multi-session host are reproducible, but there
  is not yet a guided installer or automatic MCP-client registration.
- Explicit Python extension registration is packaged. Installed-package
  discovery, new compiled-handler generation and hot reload are not.
- A fresh-install end-to-end module build and game acceptance run still needs
  retained hardware-rendered evidence and final video clips.
