# Original Native elder dialogue — revision15, 2026-10-09

Actual stdio MCP entry, original Native conversation conditions/consequences,
independent CUA screenshot. **Not injected npc_say speech, MCP choice execution,
or complete multi-turn dialogue.** Original Native greeting at Azgad elder:

> Good day, sir, and welcome to Azgad. I am the elder of this village.

[Actual original greeting and task/supplies/scouting/Leave choices](mcp-native-elder-dialogue-approach-proof.png).
`mcp-native-elder-dialogue-approach-proof.json` retains actual dispatch and state.
Entry checks unique active troop instance (engine selects troop, not agent),
<=4m actual engine distance, living human NPC/player, exact known Native town/
village scene/session, no battle, no active dialogue/custom speech.

## Honest setup and retained failures

- `mcp-native-dialogue-village-census.json`: real elder13, player15, scene376.
- First far Native entry engine-rejected. Initial world relocation request >10m
  bridge-rejected; no player movement. `...distance-and-world-setup.json` retains
  partial experiment, not a completed setup pass.
- `...bounded-world-setup.json`: first <=10m relocation acknowledged but player
  did **not** remain at its requested destination; next step engine-rejected.
  The earlier script incorrectly treated ack as movement. Retained failure,
  not accepted player controller evidence. `...elder-dialogue-proof.json/png`
  and `...elder-dialogue-near-proof.json/png` are failed distant entry attempts.
- `mcp-native-dialogue-npc-approach.json`: explicit world NPC walking control,
  actual sequential scene getter scans measure elder distance **23.23→16.68→
  9.44→3.40m**. This is not normal player movement/arrival.
- `...elder-release.json`: NPC normal AI restored before Native entry.

## Real screen state / guards

`conversation_screen_is_active` is documented for mission template triggers only.
Sampler runs there, never in HTTP callback. Dispatch first sets a protective
pending dialogue slot; periodic actual predicate reports screen state afterward.
`mcp-native-dialogue-active-guards.json`: while actual Native greeting visible,
departure, repeated entry and player relocation all refused through real MCP.

CUA clicked original **Leave** for independent cleanup only. This is **not** an
MCP-controlled dialogue choice. `...screen-close-sampler.json` proves fresh
connected engine state then reports dialogue=false; [actual closed scene](mcp-native-dialogue-screen-closed.png).

## Not finished

MCP option export/selection, NPC reply/continuation, multi-turn memory and quest
acceptance remain unimplemented. Duplicate-target, battle and death rejection
paths have structural/model coverage, not comprehensive live acceptance.
126 active-suite tests; targeted Ruff clean; Pyright zero errors;130 official
opcode IDs. Original Native conversation lines remain unchanged and installed.
No campaign save write; Native/Pendor untouched. Current game returned to Azgad
scene376/session2 with elder nearby, player49hp/gold355 and no active dialogue.

## Revision 16 committed-entry evidence

[`mcp-r16-dialogue-events.json`](mcp-r16-dialogue-events.json) records an actual
revision-16 elder conversation in scene376/session3. The new consequence suffix
reported the original NPC greeting entry (`2469`, `start:village_elder_talk.3`)
as durable sequence 1. Isolated CUA then clicked Native's visible `[Leave]`; the
engine reported original player-choice entry `2515`
(`village_elder_talk:close_window`) as sequence 2 and visibly closed the screen.

Both catalog-validated events survived a real bridge process restart and were read
through the new MCP cursor tool. This proves committed NPC/player entries and the
durable transport. It still does **not** implement MCP choice selection or claim
that every static candidate shown in the generated catalog was live-available.
