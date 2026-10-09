# Guarded Native tavern departure — 2026-10-09

Actual stdio MCP on isolated WarbandMCP revision12. No CUA exit shortcut:
`warband_leave_town_scene` evaluates recognized Native town_default departure
permission (no main tavern attacker), plus living-player/dialogue/battle and exact
mission/session guards, and calls engine `finish_mission` with player confirmation
provided by the explicit request. Original Native mission triggers remain intact.

`mcp-town-departure-catalog-fixed.json` records actual tavern **scene103/session2**
→ Native **town** menu at Praven26. Gold **355→355**; encountered party unchanged.
[Independent returned-menu screenshot](mcp-town-departure-catalog-fixed.png).
The earlier build catalog lacked the recognized-handler list even though the build
manifest had it; bridge correctly refused the first request. All installed game
code was byte-compared to a corrected build before replacing just runtime catalog.
Regression now checks catalog and manifest both carry the recognized mission IDs.

`mcp-town-center-departure-rejected.json` retains an attempted streets departure,
correctly refused because actual streets use **town_center**, not **town_default**.
[Independent streets screenshot](departure-streets-current.png). That additional
acceptance attempt had the wrong expected mission and timed out; it is not a pass.
Streets use separate escape/prison-break/mode guards; villages have fugitive quest
consequences. Neither is silently adapted as generic mission finish.

Live brawl/dead-player rejection acceptance remains pending. Automated tests cover
changed/unreviewed Native handlers, scope/session changes, dialogue/death/battle
validation, enabled callback compilation, and runtime catalog recognition.
118 active-suite tests; Ruff clean; Pyright zero errors; 124 official opcode IDs.
Normal Native/Pendor and saves untouched. Isolated campaign save was not written.
