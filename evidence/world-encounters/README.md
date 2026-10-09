# Native world center entry and Praven tavern — 2026-10-09

Actual stdio MCP on isolated WarbandMCP revision 11, original Native encounter
flow, engine results and separate CUA screenshots. This is an **explicit world
intervention**, not legitimate player travel/arrival, and it does not teleport.
Native/Pendor and existing saves were untouched; no campaign save was written.

## Failed direct-entry guard, not swept away

- `mcp-world-town-encounter.json` and `...-repeat.json`: same Praven request
  consistently engine-rejected before entry; position/gold unchanged.
- `...-gate-probe.json`: targeted guard markers identify **map_free** as the
  failing condition (−10) inside HTTP callback, despite visibly free map.
- Original Native `module_simple_triggers.py` auto-entry checks map_free before
  `start_encounter`. Final adapter schedules `auto_enter_town` instead of removing
  Native's guard or jumping directly to the town menu. It refuses pending Native
  auto-entry/siege/menu/camp tasks, captive/non-campaign state and non-centers.
- Probe instrumentation removed from current source; retained compiled probe
  build is private outside served dev content, never in this repository.

## Actual successful Native flow

`mcp-world-town-encounter-final-proof.json`:

- Default/no world authority rejected through actual MCP.
- Explicit world request scheduled target **26 Praven**.
- Engine target facts complete; Native moved through the intermediate
  `castle_outside` gate into final **town** menu for encountered party26.
- Player map position stayed **(−97.3,35.87,1.22)**; clock **101**; gold **355**.
- No wait/time command needed in the successful run.
- [Independent real Praven menu](mcp-world-town-encounter-final-proof.png).

`...-native-trigger.json/png` retains the first scheduler run: actual entry
happened, but harness attempted a now-invalid wait as menu appeared.
`...-proof.json/png` retains the next harness failure: stopped at transient gate
before town redirect finished. Neither is counted as a passing acceptance run.
Final harness waits for its **expected final menu**, not the first menu event.

Scheduling acknowledgement/target facts are **not** menu or scene arrival proof.
Native may intervene through quest, permission, siege and other encounter rules;
the adapter does not override them or force every target to the same menu.

## Original Native tavern action and actual census

`mcp-world-praven-tavern-proof.json`: MCP chose reviewed Native `town_tavern`,
engine acknowledged, entered **scene103**, **town_default** mission, flags0.

`mcp-world-praven-tavern-census.json` contains **7 living agents**: player,
Merchant of Praven, Wandering Minstrel, Traveller, Jeremus, Mercenary Horseman,
Tavern Keeper. Character names are module definitions, not claimed live rename data.

[Fresh independent tavern screenshot](mcp-world-praven-tavern-ready.png) confirms
the actual scene. Initial `...-tavern-proof.png` still shows loading/menu remnants
and is deliberately retained, not misrepresented as scene confirmation.

## Remaining / checks

Castles/villages, mobile parties, pending-entry cancellation and additional quest
paths still need work/acceptance. CUA Tab exit attempt did not leave this tavern;
leave-scene control is not established. Current isolated game remains in tavern.
111 active-suite tests, targeted Ruff clean, Pyright zero errors, 123 official
opcode IDs checked. Native auto-menu trigger remains unchanged in the build.
