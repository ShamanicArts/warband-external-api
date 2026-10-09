# Actual scene-control evidence — 2026-10-09

Original real stdio MCP results and CUA captures, isolated Native-derived
WarbandMCP revision 7. No desktop input implements these tools. CUA sets up
Custom Battle and independently captures the rendered game.

## Verified positive results

[`mcp-scene-melee-final-proof.json`](mcp-scene-melee-final-proof.json):

- Player weapon selection changed Throwing Daggers to the actually equipped
  Long Hafted Knobbed Mace (item 456). No item was spawned or added.
- All nine formations read back hold state and the requested hold-point x/y.
- An allied Swadian Footman walked **1.75m closer** to a destination 5m away;
  destination and actual position were read from the engine. Not teleport.
- Equipped NPC Sword (item 434), readied an upward attack: **attack=1, direction=3**.
- Requested NPC block: **defend=2, direction=5** (shield block, not a four-way
  weapon parry). Attack/block clearing and AI release commands acknowledged.
- [Independent rendered scene/held weapon/Footman label capture](mcp-scene-melee-final-proof.png).
  This capture does not alone identify the exact agent ID or prove its trajectory;
  the exact movement/combat evidence comes from engine before/after read-backs.
- [Native Custom Battle setup](sword-safe-setup.png): 25 allies versus 6 enemies.
  Reduced enemy count avoids target deaths during acceptance; no campaign save
  or character stats were altered by this test.

## Failures retained, not called successes

**Player held attack remains ineffective** in these live tests, even after
selecting the equipped melee weapon: attack=0, direction=-1. Acknowledgement
only means the opcode was dispatched, not proof of player combat input.

- `mcp-player-ranged-attack-failed.json`: initial throwing-weapon attempt.
- `mcp-scene-wield-proof.json`: melee selection worked, player attack did not.
- `mcp-scene-movement-proof.json`: initial formation placement failed because
  giving hold reset the previously assigned point to the player's position.
  Set the point **after** issuing hold; fresh checks then passed.
- `mcp-scene-orders-proof.json`: walking and ranged NPC ready state passed;
  that does not establish an upward melee direction.
- `mcp-scene-lifecycle-proof.json`: NPC Spear could not ready an upward attack;
  shield block passed. Retest with an equipped Sword passed direction 3.

These distinguish weapon limitations, ordering bugs and the player-controller gap.

## Main-menu callback lifecycle

An outstanding poll previously read troop slots after Custom Battle unloaded
troops. The fix appends one lifecycle global without renumbering Native globals.
Menu quit clears it before engine shutdown; callbacks test it before accessing
troops. Mission/menu entry reactivates polling.

- [Live exit JSON](mcp-lifecycle-exit-proof.json): **0 SCRIPT ERROR** before and
  after exit; heartbeat stopped; a new stdio MCP read after the stale window
  correctly reported disconnected.
- [Clean main-menu CUA capture](mcp-lifecycle-exit-proof.png).

## Reproduce / scope

`bridge/smoke_scene_control_mcp.py --catalog <private mcp-catalog.json>
--evidence <proof.json> --npc-acceptance` checks NPC/formation acceptance while
still recording the failed player test. Without `--npc-acceptance`, the known
player failure makes the overall run fail after independent checks are recorded.

Default actor control is own-team-only. `world_control=True` explicitly allows
other teams; that override has **not yet been live-verified**. AI release is
acknowledged, not claimed to undo every prior consequence. Movement/attack
collision, targeting, enemy control, player input and damage need further work.
