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
- `ykylzmpt`: pause-independent callback polling and 217 menu hooks (57 tests).
- Current change: actual reviewed Native menu actions, session-scoped dispatch,
  register-preserving Native conditions and recruitment acceptance checks.

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

Revision 5 (under live acceptance): 15 reviewed menu actions use the actual compiled
Native conditions/consequences. Each block has a separate script-local namespace;
Native script/menu/scene IDs remain unchanged. Menu initialization snapshots reg0–31
into reserved player troop slots 99940–99971; callbacks restore those values before
evaluating menu conditions and after telemetry. Conditions can refer to initialized
registers, notably recruitment reg5/reg7, so treating them as free-standing booleans
would be wrong. Choices are tied to both menu ID and menu-entry session. Bridge and
game reject mismatches. No arbitrary bytecode or cheat option is exposed.

Live Native actions: camp→camp_action and camp→map passed through MCP, followed by
village→recruit_volunteers in Iyindah. No volunteers were available; trying
`recruit_them` was rejected by game-side Native conditions (result -3), gold unchanged
at 365. Returning recruitment→village→map also passed through MCP. Travel to test
villages still uses CUA (not proof of MCP campaign travel). Positive recruitment
and Native scene entry subsequently passed (below). Artifacts are named
`mcp-*-proof.json` / `mcp-recruit-offer-proof.png` under the isolated runtime.

Paid recruitment acceptance: Azgad, one Swadian Recruit, gold 365→355 and party
1→2. Actual stdio MCP calls, Native cost/capacity/supply script, acknowledgement
and complete before/after party export. Independent CUA party screenshot shows
Swadian Recruit (1), company 2/49 and 355 denars. Evidence:
`mcp-paid-recruitment-proof.json`, `mcp-paid-recruitment-party-proof.png`.
MCP Native `village_center` selection entered Azgad scene 376, template 3,
player agent 15, HP 49; CUA confirmed the rendered village.
`mcp-native-village-entry-proof.json` / `.png`. 67 tests pass.

Original JSON/capture proof is now persisted and versioned in
`evidence/native-actions/` (10 artifacts plus README), not solely in temporary
runtime storage. Files were checked for the private bridge token before copying.

Revision 6: own-team battle orders use `team_give_order`, guarded by the actual
mission's battle-mode flag, a living player agent, dialogue inactivity and the
existing mission-session/scene checks. The team comes from the player agent;
clients cannot choose an enemy team. Formation 0–8 or everyone (9), 15 reviewed
Native orders. Durable SQLite read-back records movement, fire, riding, weapon
and order-position values from `team_get_*` operations for each formation.
No claim of individual combat input, formation placement or battle success.

Live Native Custom Battle, scene 524, template `quick_battle_battle`: stdio MCP
issued hold fire, fire at will, follow and hold position. Each acknowledged;
all nine formations matched the expected engine read-back. Fire getters use
`aordr` (0/1), not command `mordr` (12/13); the initial acceptance assertion
mistakenly compared these enums, was corrected against the pinned official
header/scripts, then all four checks passed. CUA independently showed the
four order messages. Custom Battle setup was CUA, order execution was MCP.
72 active-suite tests pass; 79 opcode IDs match the pinned official header.
Evidence: `evidence/battle-orders/`. The isolated campaign was saved normally
before this test; Native/Pendor files and saves remain untouched.
Live bridge process restart followed by new stdio MCP result calls recovered
all four acknowledged order results and exact formation rows. Durable result
recovery is proven; paused HTTP-outage-loop recovery remains a separate gap.
