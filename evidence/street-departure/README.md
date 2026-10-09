# Reviewed Native street departure — revision13, 2026-10-09

Actual stdio MCP, real installed Native-derived game code and separate CUA images.
No desktop exit input. Build recognition compares the full original town_center
Tab handler, refusing unreviewed changes or missing definitions. Adapter retains
Native escape/prison-break refusal, default/disguised mode permission, and
mission_enable_talk effect. Also requires living player, no dialogue/battle,
exact scene/session, recognized runtime catalog and no siege defense.

`mcp-street-departure-enter-streets.json`: actual Native town_center action entered
scene59, mission town_center, session2. Initial `...-before.png` still shows the
loading/menu remnants; **not** claimed as scene verification.
[Fresh actual street scene](mcp-street-departure-ready.png).

`mcp-street-departure-proof.json`: actual MCP leave_scene acknowledged and returned
to Native Praven town menu. Gold355 unchanged, encountered party26 unchanged.
[Independent returned town menu](mcp-street-departure-proof.png).

`mcp-r13-tavern-departure-regression.json`: same installed build subsequently
entered tavern scene103/session3 and departed successfully too. Original Native
mission triggers stay installed. No campaign save written; Native/Pendor untouched.

121 active-suite tests, targeted Ruff clean, Pyright zero errors, 125 official
opcode IDs. Condition-mode simulation is a model, not engine acceptance.
Live disguised/escape/prison-break/siege/brawl/death rejection acceptance pending.
Village exits still excluded: Native fugitive quest consequences need adaptation.
