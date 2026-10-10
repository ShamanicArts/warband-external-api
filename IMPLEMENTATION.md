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

The final kit handoff also requires a collated evidence report. Every material
capability claim must link its automated tests, raw live proof and introducing JJ
change, state its limitations, and include short isolated-runtime video clips when
motion, UI or interaction sequence is materially part of the claim. Terminal-only
video is not a substitute for structured evidence of persistence or policy logic.

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

Revision14: separate `warband_leave_village_scene` uses exact recognized Native
village_center Tab recipe, including active/not-succeeded/not-failed/state1 hunt
guard, original cf_troop_agent_is_alive, then original fail_quest/succeed_quest
scripts before teardown. Native scripts also write the quest journal notes;
no direct quest-flag editing. Explicit request is confirmation with documented
potential irreversible quest failure, not normal-menu permission bypass.

Actual peaceful Azgad scene376/session2→village menu passed with gold355 and
encounter93 unchanged; separate screenshots verify real scene and returned menu.
Post-departure actual quest export contains only Collect Five Men (quest86), so
no claim of live active-hunt consequences. Recognition and condition-flow model
tests preserve both hunt branches; actual active-hunt fail/succeed outcomes still
need acceptance. 123 tests; targeted Ruff clean; Pyright zero errors;128 opcode IDs.
Current live game at Azgad village menu, clock101; campaign save not written.

Revision15: original Native NPC conversation entry, not custom npc_say. Require
unique active troop instance, <=4m real engine distance, living human NPC/player,
no dialogue/custom speech job, no battle, exact recognized town/village mission
and scene/session. Engine start accepts troop, so duplicate instances refused.
Actual conversation_screen_is_active is sampled only in mission triggers (its
documented scope), never assumed usable in HTTP callback. Guard slot set during
entry dispatch; periodic engine screen sampler clears it after actual closure.

Actual Azgad elder Native greeting and task/supplies/scouting/Leave choices appear
in independent screenshot after real MCP. Explicit NPC control moved elder from
23.23m→3.40m; actual scene getters verify movement, then normal AI restored before
entry. This is explicit NPC world setup, not player walking. Far entry rejected;
an attempted player relocation setup failed (initial >10m bridge refusal; later
bounded step acknowledged but player remained at original coords and subsequent
step engine-rejected). Failures retained, no movement inference from ack.

Real active dialogue refused village departure, repeated entry and relocation.
CUA clicked original Leave only for cleanup, NOT MCP choice execution; fresh
engine sampler then reported dialogue=false and screenshot returned to scene.
Native MCP choices, multi-turn conversation and quest acceptance still absent.
126 tests; Ruff clean; Pyright zero errors;130 official opcode IDs. Current game
Azgad scene376/session2, player15, gold355, elder13 nearby, no active dialogue.

## Revision 16 — dialogue choices and agentic-kit foundation (in progress)

The product target is now a releasable, provider-neutral Warband agentic modding
and scripting kit rather than a flat MCP tool collection. The draft architecture
is in `docs/design/spec.md`: semantic observations/affordances/actions/events,
role-filtered perception and control leases, an extension SDK, constrained agent
interfaces, host-side pluggable voice, dialogue/faction reference applications and
reproducible multi-faction benchmarks. MCP remains one adapter. Human-equivalent
twitch player control is explicitly not a release prerequisite.

First implementation seam: `module_system/dialogue_actions.py` parses the complete
compiled version-2 Native conversation graph with operation-boundary validation.
Against the installed Native corpus it finds **2,773 entries**, **1,192 static
player-choice candidates**, **1,354 states**, and **11 elder-choice candidates**
across `village_elder_talk` / `village_elder_trade_talk`. Generated runtime catalog
metadata omits raw operation blocks and labels candidates honestly: their original
conditions have not yet been evaluated in the live dialogue context.

Revision 16 now appends a register-restoring evidence suffix to every original
Native dialogue consequence without changing its condition, original consequence,
speaker, states, text or voiceover. When the engine commits an NPC line or player
choice, the suffix reports its exact catalog entry/state tuple to a dedicated
loopback endpoint. The bridge validates that tuple against the generated catalog,
persists it in an ordered SQLite event stream and exposes cursor-based reads through
`warband_native_dialogue_events`. These events are evidence of committed entries;
they are deliberately not presented as available choices or remote selection.

The installed Native corpus builds and reparses as **2,775 output entries** (2,773
original plus the two existing MCP speech entries). The instrumented conversation
is 4,311,007 bytes and its safe catalog is 1,698,976 bytes. Live revision-16 proof
then recorded original elder greeting entry 2469 and visible `[Leave]` entry 2515
as ordered sequences 1 and 2 in scene376/session3. Both events survived a real
bridge restart. `evidence/native-dialogue/mcp-r16-dialogue-events.json` preserves
the facts and limitations; the Leave click was isolated CUA, not remote selection.

Static operation review finds conversation start, speaker getters/setters and the
mission-trigger-only active-screen predicate, but no documented operation that
selects a displayed player dialogue option. This is not an impossibility claim.
The current investigation must determine whether the original player-choice
condition/consequence can be executed with the exact live conversation register
context and whether the engine can safely advance, close or re-enter the resulting
state without desktop input. Do not dispatch copied consequences until both the
state-transition mechanism and required register/global preservation are proven.
The expanded active suite passes **134 tests**; maintained source and harnesses are
Ruff-clean. Legacy prototype files remain outside the active lint boundary.

## Provider-neutral semantic contracts (`warband.agentic/v1`)

The first runtime-kernel package now lives in `warband_agentic/` and imports no
bridge, MCP or model-provider code. Frozen Python 3.11 contracts define actor and
context identity, source-labelled facts, role-filtered observation envelopes,
expiring affordances, optimistic action submissions, outcomes, durable semantic
events, evidence levels, role grants and control leases. Nested payloads are
recursively copied/frozen, reject non-JSON values and serialize through `to_wire`.

The manifest exposes stable role, authority, context, fact-source, evidence and
action-state vocabularies to future adapters. Tests explicitly preserve the
distinction between engine acknowledgement and independently observed outcomes,
and verify that transport terms such as MCP/HTTP do not leak into discovery.
Seven new contract tests bring the expanded active suite to **141 tests**; the
maintained source remains Ruff-clean. Capability registration, policy filtering,
affordance issuance/consumption and persistent semantic-event migration are the
next kernel layers, not implied by these type definitions.

## Role-scoped capability and affordance registry

`warband_agentic.capabilities` now registers semantic capability definitions with
public name/description, authority, domain, valid contexts, bounded parameter
schema, risk, reversibility, warning, lease requirement and required evidence.
Agent discovery filters definitions through the active role grant, context,
authority and domain while withholding internal handler IDs and transport details.

Issuance creates opaque, actor/target/context/revision-bound affordances that cannot
outlive their role grant. Consumption validates the current grant, exact context,
submission timestamp, expiry, optimistic revision, JSON-schema subset, and optional
control lease before resolving the private handler binding. Tokens are single-use
and action IDs cannot be replayed. This layer validates and resolves; it does not
execute game mutations or treat validation as an outcome. Eight registry tests
bring the active suite to **149 tests**.

## Control arbitration and perception filtering

`warband_agentic.authority` adds a trusted in-process `LeaseBook`: exclusive and
shared leases arbitrate overlapping target/domain control, wildcard domains
conflict correctly, generations remain monotonic across release/expiry, and only
the controller may release. Capability consumption now resolves submitted lease
IDs through that book; constructing a plausible `ControlLease` object cannot forge
authority. The first implementation is intentionally in-memory, so persistent
lease recovery and native-AI resumption hooks remain future work.

Named `PerceptionPolicy` definitions filter canonical observation facts by role,
context, key namespace and fact source. Restricted output retains source labels and
reports coarse omitted categories without exposing hidden keys or values. Initial
conservative policies cover readonly observer, strategic player, NPC self, party
commander, faction sovereign, test director and full operator roles. Nine new
authority/lease tests bring the active suite to **158 tests**.

## First semantic adapters over proven game paths

`warband_agentic.adapters` maps connected protocol-2 telemetry into canonical
operator observations with a runtime-assigned optimistic revision. Engine facts,
definition metadata and omitted bridge bookkeeping remain distinct; the adapter
does not confuse telemetry age with a game revision. Catalog-validated Native
dialogue rows also map to semantic events with a runtime-global sequence while
retaining their source-stream sequence in the payload.

The first action adapter registers `menu.try-select` over the already proven Native
menu seam. It converts safe current-menu candidate metadata into one exact-session,
single-action affordance per candidate, with Native-condition recheck and possible
rejection stated in the contract. Validated actions resolve to the existing
allowlisted `select_menu` operation; raw condition/consequence script fields are
rejected at the adapter boundary. Dialogue choice execution remains unimplemented.
Six adapter tests bring the active suite to **164 tests**.

## Pluggable host voice service

`warband_agentic.voice` now provides a provider-neutral voice boundary separate
from dialogue and game truth. Named public profiles hide provider voice IDs and
adapter configuration. Idempotent speech requests choose synthesis-only or host
playback delivery; bounded in-memory WAV artifacts, outcomes and ordered lifecycle
events remain queryable. Synthesis and playback failures become explicit outcomes
and cannot advance, roll back or falsify the correlated game event. The service
serializes shared state so concurrent duplicate request IDs synthesize exactly once.

The first concrete adapter targets the existing loopback OpenAI-compatible Kokoro
service at `/v1/audio/speech`; optional host playback uses `pw-play` with audio on
stdin and no shell. An authenticated loopback HTTP facade exposes profiles, speech,
request outcomes, cursor-based events and audio retrieval. Configuration and token
files remain outside the game module. `docs/voice.md` contains the runnable setup;
in-game sound injection, dialogue-event wiring, interruption/priority and durable
artifact recovery remain deliberately deferred.

A live synthesis-only HTTP round trip using profile `elder.calm` / local voice
`bm_george` produced an **87,644-byte valid RIFF/WAVE**, then recovered the ready
outcome, three lifecycle events and audio through separate authenticated requests.
Nothing was played through host speakers during proof. Sixteen voice tests bring
the active suite to **180 tests**; targeted Ruff is clean.

## Durable semantic event log

`warband_agentic.events` adds a versioned SQLite store for `GameEvent` history.
The store assigns monotonic sequences and matching evidence cursors, validates
strict persisted JSON on read, exposes bounded cursor pages and high-water marks,
survives restart, serializes concurrent writers, and makes ingestion idempotent by
stable source key plus canonical input hash. Reusing a source key for different
content is rejected instead of silently overwriting history. Future schema versions
are refused rather than guessed.

The migration adapter imports committed `native_dialogue_events` and terminal
legacy `commands` records. It does not claim that a historical acknowledgement is
an independently observed outcome, and it labels unavailable scene/revision scope
instead of manufacturing context. Against a backup—not the live database—of the
active isolated revision-16 runtime, it imported **421 events**: 403 acknowledged,
15 rejected and one expired legacy command plus both committed Native dialogue
events. A second migration inserted zero duplicates; all 421 events read back to
the high-water mark. Evidence is retained under `evidence/semantic-events/`.
Eight event-store tests bring the active suite to **188 tests**.

## Restricted-agent usability fixture

`warband_agentic.usability` builds a deterministic faction-sovereign scenario from
the real contract, observation-policy, capability, affordance and lease layers. A
role-filtered briefing reports an imminent threat to Praven while omitting an
operator-only exact-strength fact. Two bounded party-order affordances are visible;
private handler IDs and provider/transport details are not. The response surface
accepts only an affordance token, arguments and expected revision, while trusted
actor and lease identity remain runtime-owned.

The evaluator runs submissions through the normal registry and distinguishes a
valid but task-wrong raid from the requested defense. It rejects raw operation
fields, stale revisions and argument attempts outside issued constants. A JSON CLI
exports and evaluates the same fixture for future providers; its current export
hash and run instructions are in `docs/agent-usability.md`. Five tests bring the
active suite to **193 tests**. This is fixture readiness, not `agent-usable`
evidence on its own; external results and their narrower claim follow below.

After explicit advance notice, the exact fixture was tested once each by GPT-6
Luna through Codex/OpenAI, Muse Spark 1.3 Contributor through OpenCode v2, and
Grok 4.6 through Cursor. All three selected `aff:defend-praven` with exact bounded
arguments and revision 7; the real evaluator scored each response 100/100. Luna
and Grok independently flagged the implicit source of `expected_revision`, which
is retained as interface feedback. Requested DeepSeek 4.1 was absent from the
provider catalog and was not substituted. This earns `agent-usable` evidence for
the fixture interface only, not the unwired simulated party-order backend. Raw
results and run metadata are in `evidence/agent-usability/`.

## Constrained semantic agent API

`warband_agentic.agent_api` binds one role grant to its perception policy,
capability registry, current context, server-issued affordances, private control
lease selection and validated dispatcher. Agents receive only filtered turns and
submit request ID, affordance token, bounded arguments and expected revision.
Action/actor/grant/lease/handler identity remains server-owned. Repeated turn reads
do not mint duplicate tokens for an unchanged context; request IDs are idempotent,
while conflicting reuse, stale context, consumed tokens and forged extra fields
are rejected before dispatch.

Validated backend exceptions become explicit interrupted outcomes. Returned
outcomes must match the action and originating context and cannot regress the
runtime revision. With `SemanticEventLog`, session action events are durable and
retain the strongest actual evidence supplied by the backend. The restricted
event cursor filters by session and never returns another session's payload.

`warband_agentic.agent_http` adds a Bearer-authenticated IPv4-loopback adapter for
manifest, turn, action submission/outcome lookup and cursor events. Nine tests
cover policy omission, private-binding secrecy, context/lease injection, replay,
conflict and stale rejection, backend interruption, cross-session event isolation,
concurrent deduplication, HTTP auth and loopback refusal. The active suite is now
**202 tests**. Production bridge wiring, durable outcome reconstruction and broader
role-filtered game-event audiences remain explicit follow-up work.

## Native menu and faction application compositions

The constrained API's first two real `Store` compositions cover Native menus and
faction orders. The Native-menu
application derives exact-session options from current menu telemetry, queues the
existing allowlisted operation and reconciles dispatch/acknowledgement without
exposing command IDs. A trusted outcome refresher in `ConstrainedAgentSession`
enforces legal lifecycle transitions and records each changed state separately.

The faction-sovereign application requires a host-reviewed faction, controlled
party set and exact strategic options. Each decision view is refreshed through
real campaign party getters. Engine-observed faction ownership must match the
grant before affordances are issued; one private exclusive lease binds each
controlled party. The agent never receives `world_control`, operation names or
arbitrary IDs. Movement and attack risks are distinct, and an action reaches
`observed` only when `/world-result` reads back the party AI behavior/object.

These compositions are covered by root integration tests over the production
Store. The underlying menu and campaign mechanics retain their existing live
evidence, but the new faction composition itself remains bridge-simulated until
an isolated hardware-rendered run is available. Durable session reconstruction,
diplomacy, automatic option generation, synchronized faction epochs and
persistent NPC/dialogue applications remain open.

Current separated discovery passes **226 tests**: 92 root agentic/runtime tests,
86 bridge tests and 48 module-system tests. Focused maintained-code Ruff and
whitespace checks pass.

## Constrained NPC speech and observed voice handoff

`NativeNpcSpeechApplication` composes the `npc.self` role over the existing scene
census and one-turn `npc_say` path. A fresh census must prove that the configured
agent is present, alive and not the player in the current scene/session before a
speech affordance appears. The agent controls bounded text only; target identity,
lease, operation and mission scope remain private. Warband's matching dialogue
open/close event—not queueing or acknowledgement—raises the action to observed.

After observation, `voice_request()` builds a deterministic provider-neutral
`SpeechRequest` carrying the utterance and action correlation. A host may send it
to synthesis-only or PipeWire playback through the existing voice service. Voice
remains separate from game truth and cannot affect the dialogue outcome. This
composition is bridge-simulated; the underlying one-turn dialogue UI has prior
visual evidence, while integrated NPC-agent and voice playback evidence remains
pending. Arbitrary player replies, original-choice execution, persistent dialogue,
NPC-to-NPC conversation, memory and mechanical proposals remain open.

## Synchronized faction decision epochs

`SynchronizedFactionEpoch` adds the provider-neutral coordination core for
multi-faction experiments. It rejects overlapping controlled-party ownership,
queues observation refreshes in faction-ID order, requires all filtered turns to
share one campaign scope and exact game time, freezes and hashes the public turn
set, and commits exactly one submitted response per faction in deterministic
order. Accepted outcomes and invalid-decision errors are both retained; an
invalid model response cannot disappear from the benchmark record.

The transcript also carries caller-supplied JSON run metadata for module/save
hashes, seed, model settings, budgets and costs. The coordinator does not invoke
providers, expose private application objects or let response latency advance
game time. At that slice, fixed-time campaign driving, safe rest stop, checkpoint
persistence, resume, metrics/scoring and announced external-model runs remained
separate future layers. Three coordinator tests bring separated discovery to **229 tests**: 95
root, 86 bridge and 48 module-system.

`CampaignEpochDriver` now provides the bounded time-advance half of that contract
over the production Store. It starts Native attackable rest, refuses to equate
acknowledgement with elapsed time, compares fresh engine clock to the exact target,
queues an explicit zero-hour stop, and requires the stop acknowledgement before
completion. The coordinator only accepts a matching completed advance after all
faction actions resolve, validates its clock arithmetic and stop proof, and can
then atomically persist canonical transcript JSON. The bridge-simulated driver
test raises separated discovery to **230 tests**: 96 root, 86 bridge and 48
module-system. At that slice, live multi-faction orchestration, save/checkpoint
recovery and strategic scoring remained open.

## Installable Python distribution

The project now builds as `warband-agentic-kit` 0.2.0 with locked metadata and
installed commands for the bridge, isolated Native module builder, MCP server,
voice service and restricted-agent usability harness. The packaging regression
builds a source distribution, builds the wheel from that clean source artifact,
checks that runtime/bridge/builder/MCP files and entrypoints are present while
private runtime/evidence artifacts are absent, installs the wheel outside the
checkout, imports the core modules and exercises every non-MCP command's help
path. This raises separated discovery to **232 tests**: 98 root, 86 bridge and 48
module-system tests.

This is structural installability, not public-release acceptance. A project
license is still unselected; dependency/source licensing verdicts, guided client
registration, packaged application discovery, fresh-Native end-to-end acceptance
and final hardware-rendered video evidence remain open. See `docs/packaging.md`.

## Constrained action restart recovery

New constrained-session action events now carry a private recovery envelope with
the exact request fingerprint, complete public outcome and application-owned
correlation state. Session construction strictly decodes the history and rebuilds
lookup/idempotency state without invoking a dispatcher. The public event cursor
strips the private envelope. Contradictory records fail closed; older records that
predate the envelope quarantine their request IDs instead of risking replay.

Native menu, faction-order and NPC-speech applications persist and restore their
action-to-bridge-command mapping. Restart tests continue queued command lifecycle,
promote later game evidence, and preserve NPC voice handoff text while asserting
that no duplicate command is inserted. This raises separated discovery to **237
tests**: 103 root, 86 bridge and 48 module-system. Recovery is bridge-simulated;
live process-restart acceptance and multi-session hosting remain open.

## Benchmark coordinator checkpoints

Committed and resolved faction epochs now write atomic checksummed coordinator
checkpoints and strictly reload only when the epoch schema, faction set and frozen
turn hash match. Reloading reconstructs decisions and records but never calls
`submit`; recovered constrained sessions remain the source of action outcomes.
Refreshing/collecting phases are intentionally non-resumable because their jobs
and affordance tokens are time-sensitive.

`CampaignEpochDriver` separately checkpoints the original Native wait and stop
command IDs plus clock bounds. Restore validates command kind and exact arguments
against the durable Store, then continues status/stop handling without queuing a
second wait or stop. Two regression tests raise separated discovery to **239
tests**: 105 root, 86 bridge and 48 module-system. Live game-process/save recovery,
scenario metrics and external-provider scheduling remain open.

## Packaged built-in application host

`warband-agent-host` now validates a versioned JSON plan for one game bridge,
one operator control listener and up to 32 separately authenticated constrained
sessions. Check mode verifies protocol 2/revision 16 manifests, catalog JSON,
private 0600 tokens, database parents, unique loopback ports/session IDs and
disjoint player, party and NPC ownership without binding sockets or creating
databases. Diagnostics omit paths, credentials, handlers and command IDs.

Runtime starts the bridge/control listeners, waits for actual protocol telemetry,
then constructs only the menu, faction and NPC-speech reference applications and
binds their per-session servers. The operator control interface exposes safe
diagnostics and explicit faction/NPC observation refresh counts; it never grants
that authority to session agents. A loopback integration test proves waiting,
activation, authenticated NPC manifest/refresh and complete listener teardown.
The wheel installs the host command and both host/voice examples. Two host tests
raise separated discovery to **241 tests**: 107 root, 86 bridge and 48
module-system. Third-party discovery, hot reload, client registration and live
multi-session acceptance remain open.
