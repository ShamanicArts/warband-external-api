# Native village departure — revision14, 2026-10-09

Actual stdio MCP, isolated Native-derived game, no desktop exit input.
Separate `warband_leave_village_scene` retains installed Native village_center
Tab quest consequences rather than offering a generic finish-mission shortcut.
Build recognition requires the complete reviewed handler with actual module
quest/troop/script IDs. It fails closed on missing/unreviewed definitions.

Native checks active, not succeeded, not failed, hunt state1; then calls original
cf_troop_agent_is_alive. Living fugitive calls original **fail_quest**; otherwise
original **succeed_quest**. Those original scripts also update journal notes.
No direct quest-flag edits. The explicit MCP request provides confirmation and
documents possible quest failure. Requires living player, no dialogue/battle,
exact mission/session and recognized runtime catalog.

`mcp-village-departure-enter.json`: real Azgad **scene376/session2**, village_center.
[Independent actual village scene](mcp-village-departure-before.png).
`mcp-village-departure-proof.json`: engine teardown reached **village** menu,
gold **355 unchanged**, encounter **93 unchanged**.
[Independent returned Azgad menu](mcp-village-departure-proof.png).

`mcp-village-departure-quests.json` exports one active quest, **Collect Five Men**
quest86. This peaceful run does **not** establish active fugitive-hunt outcomes.
The focused quest-branch interpreter is explicitly a model, not game acceptance.
Actual hunt fail/succeed, death/battle/dialogue refusal acceptance remains pending.

123 active-suite tests; targeted Ruff clean; Pyright zero errors;128 official
opcode IDs. Original mission triggers remain installed; Native/Pendor and saves
untouched. No campaign save written. Isolated live game returned to Azgad menu.
