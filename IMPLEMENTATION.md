# Warband agent suite — implementation and evidence map

Target: a deeply integrated agent suite for vanilla Warband/Native, not a desktop
automation wrapper. Pendor support is a separate compatibility exercise; do not
modify the working Pendor installation. Use JJ in this project, no remote pushes.

## Definition of complete

Every exposed operation must have actual game code, bounded arguments, contextual
validation, explicit result/acknowledgement, automated regression coverage and
recorded live evidence. Unsupported capabilities must be discoverable, not implied.
No arbitrary bytecode, memory injection, blind save changes, or mocked state.

The user's explicit scope is **everything that can be exposed through real game
code**: campaign travel/time, trade/equipment/party management, quests/politics,
player combat input, individual NPC control, multi-turn conversations, faction
and world control. Checkpoints are progress boundaries, not permission to stop.
Separate normal-rule actions from explicitly named world/debug interventions;
do not silently substitute CUA or raw state edits for normal gameplay actions.
For an engine limitation, record the exact inspected API and failed live test;
do not label unimplemented work impossible. Images must be shown directly in
OpenCode, never by opening the browser. Preserve the isolated runtime and JJ flow.

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

## Full-control coverage backlog (not optional)

Each subdomain needs observation, typed validated actions, game acknowledgement,
live state-change proof, and discoverable capability/limitations. A broad tool
name or a successful queue insertion does not establish domain coverage.

- **Campaign/map/time:** player destination/stop/arrival/encounter, NPC party
  travel/patrol/escort/attack/retreat, pause/wait/time advancement, party visibility
  versus omniscient queries, path and movement read-back.
- **Trade/economy:** merchant inventories and Native prices, buy/sell/budget/capacity,
  partial goods/modifiers, village trade, prisoners, businesses, rents/taxes,
  food/consumption, economic world interventions separately labelled.
- **Party/characters:** recruit/disband/upgrade, prisoner transfer/recruit/sell,
  garrisons, companion joining/equipment/orders, skills/attributes/proficiencies,
  inventory/equipment and item descriptions; progression versus admin changes.
- **Combat/player input:** equipment selection, attack/block/release, aiming and
  movement if engine APIs permit, formation placement/orders, individual agent
  walking/targeting/AI release, siege/arena/tournament, injury/death/mounts/ammo,
  scene navigation and mission transitions, battle outcome and recovery.
- **NPC/dialogue:** identity/character/faction/relation/quest context, Native
  conversation hooks, player choices/free text, real multi-turn agent replies,
  persistent per-character memory/history, interrupted conversation recovery.
- **Factions/politics:** faction snapshots/relations, Native war/peace scripts,
  liege/vassal/mercenary allegiance, fief assignment/capture/ownership, marshal
  and campaign orders, councils/claims/right-to-rule, courtship/marriage,
  explicit administrative faction/NPC intervention where normal rules differ.
- **Quests/encounters:** inspect goals/progress/parties/timers, Native offer/accept/
  decline/turn-in/fail/abort paths, escort/delivery/rescue/hunt/reputation,
  map/scene encounters and consequences; no fake completion by bare quest flag.
- **World/engine controls:** bounded spawn/disable versus unsafe removal,
  scene props/objects/doors/weather/time, camera/settings/menus/presentations,
  module identity, event streams, checkpoint/save/load support where available.
- **Operational completeness:** durable install/runtime, client registration,
  recovery after game/bridge interruption, cancellation, auditable history,
  compatibility scope and full isolated campaign acceptance with screenshots.

Do not silently omit a subdomain because a convenient opcode is absent. Inspect
Native scripts and the official engine API; attempt bounded live tests; document
confirmed limitations and obtain approval before changing the integration method.

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
- `oklqlzmr`: reviewed Native menu choices; paid recruitment and village entry.
- `prvupwmq`: own-team battle orders; four live orders and durable read-backs.
- `lumkqkkz`: player/NPC combat adapters, scripted NPC walking/release,
  formation placement and main-menu callback lifecycle guard.

Further verified checkpoints: `lumkqkkz` scene control/lifecycle; `tynqtnvp`
Native diplomacy/NPC campaign travel/time; `vrktsppq` merchant inspection/trade
context; `kpvllsqz` full-unmodified goods transactions. Current change `vpvkzots`
adds explicit world encounter scheduling and actual Praven/tavern acceptance.

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

Revision 7 adds typed formation placement, equipped-weapon selection, individual
NPC walking/release, and actor attack/block operations. Scene bounds, living
human actors, dialogue inactivity, and mission/scene scope are validated in
game. Actor controls default to the player's team; explicit world_control allows
other teams (override not yet live-tested). This is actual NPC walking, not
teleport. NPC combat follows Native tutorial's scripted/no-auto-attack mode and
requires release afterwards to restore AI. Census exports real equipment,
wielded weapon, attack/defend/direction, and scripted destination.

Live proof retained in `evidence/scene-control/`: player equipped weapon selection,
nine matching hold points, a Swadian Footman walking 1.75m closer, upward Sword
ready state (attack 1, direction 3), shield block (defend 2, direction 5), clears
and release acknowledgements. **Player held attack remains ineffective**, with
both throwing and melee weapons. Do not call this verified player combat input.
Failed original attempts are retained alongside positive proof. Initial placement
ordering was wrong (hold resets the point); set point after hold and retested.

Main-menu lifecycle fix: append mcp_http_active global, set on mission/menu
entry, clear before Native quit, test before every callback's troop access.
This fixes late callbacks after troops unload. Live exit: 0 script errors before
and after, stopped heartbeat, correctly disconnected MCP after stale window.
86 tests pass; 96 opcode IDs checked against the pinned official header.

Revision 8 exposes durable faction/party getter results, reviewed Native war/peace
scripts, campaign-party AI, and bounded attackable interactive rest/stop.
Diplomacy is either player-ruler authority or explicitly labelled world control;
other-party AI requires world control. Validate actual active parties before
engine getters; reject fixed centers for motion. Native faction catalog parser
now handles the prior note-count sharing the next definition's line, retaining
all 34 faction IDs and seven kingdoms.

`evidence/campaign-world/` retains actual MCP commands/results and CUA captures:
non-ruler war rejected, world war relation 0→−40 and actual declaration screen,
world peace −40→0 and actual agreement screen, faction and party inspection.
Party 386 travelled 3.9043 map units toward party 26 (3.9032 distance improvement)
while Native attackable rest advanced clock 102→103, then MCP stopped resting.
No teleport, clock editing or CUA implementation. **Player travel remains open**:
AI getter accepted travel, but resting holds main party stationary. The zero-motion
test is retained and does not prove free-running player travel is impossible.
95 tests pass, targeted Ruff clean, Pyright zero errors, 108 official opcode IDs.

Revision 9 work in progress: actual merchant inventory/base values/quantities,
merchant gold and original Native buy/sell factor scripts, bounded durable pages
scoped to the exact town_trade menu entry. Four merchants (arms/armor/goods/horses)
live-exported all 384 non-equipped slots; 37/44/32/5 stocked. Player gold stayed
355; independent goods UI matched merchant gold 703 and actual stock. Stock and
factor observations are NOT final transaction quotes. Buy/sell remains pending.
Three more reviewed menu actions cover marketplace→town and war/peace continue.
Trade UI instrumentation uses separate `trade` context, disables underlying menu
actions and keeps nonce-controlled polling. Live check: fresh heartbeats during
trade UI, merchant inspection rejected, normal market/town/map transitions after
closing UI. War/peace continue actions also live-verified. Actual UI buy prices
match truncating base_value*Native_buy_factor/100 for unmodified Oil 454, Tools
397 and full Bread 46; this is not yet a formula proven for modifiers/partial
stacks. Current live build is revision 9; prior builds retained. 101 tests pass,
targeted Ruff clean, 110 official opcode IDs.

Next: preserve original evidence, then implement guarded full-unmodified-stack
buy/sell with original Native economic event scripts and independently measured
inventory, gold and market-price consequences. Extend modifiers/partial stacks
only after corresponding actual price and transaction evidence.
Do not substitute base_value*factor for a verified transaction price formula.

Revision 10 live: guarded full-unmodified goods quote/buy/sell adapter, exact
item/slot/price agreement and marketplace-entry scope. Original Native economic
event scripts are invoked; not generic inventory editing or UI automation.
Actual MCP bought Bread 50/50 for 46: player gold 355→309, merchant 703→749;
sold same full stack for 41: player 309→350, merchant 749→708. Independent UI
captures confirm both balances and player stack presence/removal; UI sell tooltip
41 matches quote. Wrong-price requests rejected before mutation; insufficient
funds for Oil and mismatched source item also engine-rejected with unchanged
exact stock/gold facts. Bread factors changed 93/81→sell83 after buy→92/80 after
roundtrip, proving economic consequences (roundtrip is not rollback).

Gear, unique items, modifiers and partially consumed stacks intentionally rejected.
Price agreement is recomputed at execution, not a reservation. Control-flow tests
are labelled models, not engine acceptance. 108 active-suite tests; 121 official
opcode IDs verified. Actual bridge restart followed by fresh MCP recovered exact
executed buy/sell facts without retrying effects. Original quote/buy/sell/status
and independent UI evidence retained in evidence/goods-trade. Live full goods
transaction acceptance is Bread only; wider goods coverage remains to test.

Revision 11: explicit world center encounter scheduling through Native's existing
auto_enter_town trigger; do not present it as player travel. Direct HTTP-callback
map_free failed repeatedly; tagged guard probe returned -10, identifying that
guard. Rather than bypass it, schedule original Native auto-entry, retaining its
map_free check in the original trigger. Reject existing Native auto-entry/siege/
menu/camp tasks, captivity/non-campaign and non-center parties. Require explicit
world_control=True; default rejected. Scheduling facts describe target BEFORE
entry and do not establish arrival.

Actual MCP proof at Praven 26: Native reached town menu through transient
castle_outside; unchanged player position (-97.3,35.87,1.22), clock101 and gold355.
Two acceptance-harness failures (racing an unnecessary wait request, then stopping
at the intermediate gate menu) retained, not hidden; final original test passes by
waiting for expected menu. Actual Native town_tavern action entered scene103,
town_default, seven living agents including Jeremus. Fresh independent screenshot
confirms tavern; initial capture was still loading and is retained separately.
Castles/villages/mobile encounters, scheduled cancellation and additional quest
encounter outcomes need acceptance. CUA tavern Tab exit did not take effect;
leave-scene API/normal exit acceptance remains unfinished. Current game remains
in Praven tavern, isolated save unchanged. 111 tests; 123 official opcode IDs.

Revision 12: `warband_leave_town_scene` adapts the exactly recognized installed
Native town_default Tab permission (no active tavern attacker) plus living-player,
dialogue, battle and exact scene/session guards. Request provides confirmation;
engine finish_mission performs teardown, not CUA input or arbitrary mission abort.
Actual tavern scene103→Praven town menu passed with gold355/encounter26 unchanged;
independent screenshot verifies returned menu. First request rejected because
recognized-handler metadata was accidentally only in build manifest; corrected
runtime catalog after verifying all game-code bytes identical, regression added.

Town streets use town_center, not town_default: attempted additional acceptance
was wrongly scoped, and correctly rejected. Their Native Tab escape/prison-break/
mission-mode guards remain unadapted. Village departures have quest consequences
and stay unsupported. Live active-brawl/dead-player departure rejections still
need separate acceptance. 118 tests, targeted Ruff clean, Pyright zero errors,
124 official opcode IDs. Current game is Praven streets scene59, mission session3.

Revision 13: independently recognize exact installed town_center Tab handler,
retain escape/prison-break refusal, default/disguised-mode checks and original
mission_enable_talk effect before engine teardown. Conservatively reject siege
defense too. Runtime catalog lists both recognized mission IDs; streets require
revision13 telemetry. Actual MCP entered streets scene59, then departure returned
to Praven town with gold355/encounter26 unchanged. Fresh independent before/after
screenshots verify actual scene/menu. Original tavern departure re-tested on same
build: scene103/session3→town also passed. Tests explicitly label condition-mode
simulation a model, not live escape/quest acceptance. Disguised/escape/prison-break/
siege/dead-player/brawl cases still need actual acceptance; village exits remain
unsupported pending their Native quest consequences. 121 tests; Ruff clean;
Pyright zero errors; 125 official opcode IDs. Current game at Praven town menu.
