# Warband agent suite — implementation and evidence map

Target: a deeply integrated agent suite for vanilla Warband/Native, not a desktop
automation wrapper. Pendor support is a separate compatibility exercise; do not
modify the working Pendor installation. Use JJ in this project, no remote pushes.

## Definition of complete

Every exposed operation must have actual game code, bounded arguments, contextual
validation, explicit result/acknowledgement, automated regression coverage and
recorded live evidence. Unsupported capabilities must be discoverable, not implied.
No arbitrary bytecode, memory injection, blind save changes, or mocked state.

## Incremental work

1. **Transport foundation** — verified: authenticated HTTP, queued commands,
   replay/deduplication, expiry, restart interruption, stdio MCP.
2. **Scene foundation** — verified in training yard: agent census, guarded debug
   relocation, one-turn externally generated NPC speech, opening/closing events.
3. **Campaign observation** — first live checks passed: campaign telemetry; export
   party members/prisoners, player inventory, character stats and paginated world
   parties. Make exports complete/out-of-order safe, provenance-labelled and stale-aware.
   All six first pages and complete inventory/character pagination verified;
   CUA character stats match. Prisoner export has only been checked with zero prisoners.
4. **Integration breadth** — 41 single-player missions instrumented, village live-verified;
   instrument actual single-player missions, not just
   the training yard; verify town, tavern, battle and campaign/mission transitions.
5. **Campaign control** — guarded destination orders and stop; inspect native
   economic, recruitment, quest, encounter, trade and party-management interfaces
   before adding their actions. Actions must use normal game rules, not cheat edits.
6. **Combat control** — formation/unit orders and bounded movement; inspect native
   team/agent control operations. Keep debug teleport explicitly separate.
7. **NPC conversations** — game-initiated hooks, character/faction/relation/quest
   context, player choices/free-text input, multi-turn responses while dialogue is
   open, persistent per-character conversation history and reconnect recovery.
   LLM remains the MCP caller; do not lock the integration to one provider.
8. **Packaging/recovery** — durable runtime outside temporary directories,
   reproducible build/install, connection/capability diagnostics, cancellation,
   event/history queries, module identity/version checks and client configuration.
9. **Acceptance** — test an entire new isolated campaign journey (travel, town,
   quest, trade/recruit, battle, companion dialogue, save/reload). Record actual
   MCP calls and independent CUA screenshots; never overwrite existing saves.

## Current evidence

`MCP.md` contains the verified baseline and artifact paths. Automated tests are
not substitutes for live game checks. Compiled modules embed a secret: never
track or serve them. The legacy `module/` remains local and ignored because it
contains installed game assets, not the authoritative readable integration source.

## JJ checkpoints

- `ntypolot`: verified transport/scene/NPC baseline (29 tests).
- `wyuutpxx`: campaign observation and honest capability discovery (41 tests).
- `tmnokvyk`: 41 single-player mission hooks; village dialogue/save reload (47 tests).
- Current change: pause-independent HTTP callback loop and Native menu context.

## Live campaign notes

Isolated new WarbandMCP save: copied prefix Documents / Mount&Blade Warband
Savegames / WarbandMCP / sg00.sav. It is a new module-specific slot, not a Native
or Pendor save. Initial merchant quest was accepted normally through CUA.
The test character was later captured/released normally; no stats or save bytes
were edited. Full character pagination contains 47 rows, inventory has 58 slots.
Declaration-of-war menu and looter encounter paused polling. Menu/context events
and pause-safe read/command handling are required, not optional packaging polish.
Artifacts: `/tmp/shuvcode/warband-cua/campaign-proof.json`,
`campaign-pagination-proof.json`, and `campaign-character-proof.png`.
Inventory empty-slot guard was revalidated on integration revision 3 after reload:
`/tmp/shuvcode/warband-cua/inventory-guard-proof.json`.

Revision 3 instruments 41 single-player mission templates, excludes `multiplayer*`
templates and additionally guards execution with vanilla `game_in_multiplayer_mode`.
Native zero-spawn templates encode spawn-count/trigger-count together (`0 2`);
the parser has a regression fixture for the actual `camera_test` seam.
Village live proof: scene 434, template 3 `village_center`, session 1, 10 living
humans. Supplied text rendered by a villager, opening and closing observed,
command acknowledged; `/tmp/shuvcode/warband-cua/village-gameplay-proof.json`
and `village-dialogue-proof.png`. Battle/tavern transitions still unverified.
NPC replies are rejected in battle-mode missions in both bridge and game code.
Exit wording still says "Back to training" in other scenes: fix as part of real
multi-turn dialogue rather than present the current dialogue UX as finished.

Revision 4: 217 Native menu entry hooks plus return/map-context clearing;
asynchronous callback long-poll with a 250ms idle wait and poll nonce echo.
Superseded polls may still deliver commands, whose game-side scope/deduplication
remains authoritative, but cannot spawn duplicate callback loops. Read-only
campaign exports are permitted from menu context. Scene mutations are refused
during MCP dialogue. Bootstrap preserves integer registers 0–19, s127 and pos1;
reserved scratch registers s123/pos47 are unused by the pinned Native source.
An HTTP outage while paused still requires a menu entry or advancing time to
reseed polling; automatic error-callback recovery remains pending.

Live proof: nine complete acknowledged pages each on paused campaign and paused
camp menu, with clock unchanged at hour 93 (`paused-campaign-proof.json`,
`paused-menu-proof.json`). CUA `pulse-camp.png` verifies the camp menu; MCP reports
menu ID 23/name `camp`. Bootstrap after a fresh paused save reload passed: no
telemetry before opening camp, fresh menu telemetry afterwards with clock 93.
`bootstrap-full-campaign-proof.json` covers all dataset types after bootstrap
(world limited to 32 pages in that run). `paused-full-world-proof.json` completes
all 36 world pages: 562 unique active parties, clock 93 throughout, final cursor
null. CUA `bootstrap-camp-proof.png` / `menu-return-map-proof.png` verify menu and
return to the paused map; MCP context returned to `campaign` with menu fields null.
