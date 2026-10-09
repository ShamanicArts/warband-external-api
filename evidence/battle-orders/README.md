# Actual Native battle-order MCP proof — 2026-10-09

Original JSON and CUA captures from isolated WarbandMCP revision 6, Native Custom
Battle, mission `quick_battle_battle`, scene 524. Setup used CUA. **Orders used
actual stdio MCP → authenticated bridge → Warband game-script operations.**

| MCP order | All nine formations' engine read-back |
|---|---|
| Hold fire | fire = 1 |
| Fire at will | fire = 0 |
| Follow | movement = 1 |
| Hold position | movement = 0 |

Every command was acknowledged with result 0. Team 0 was derived from the player
agent, not supplied by the caller. Read-back uses Native `team_get_*_order`.
Fire getters return `aordr` values, not the `mordr` command IDs.

- [Actual MCP commands, acknowledgements and read-backs](mcp-battle-orders-proof.json)
- [Independent CUA capture showing all four Native order messages](mcp-battle-orders-final-proof.png)
- [First hold-fire capture](mcp-battle-orders-proof.png)
- [Native Custom Battle setup](battle-setup.png)

This proves these four orders and resulting engine order state. It does not
prove every allowlisted order, troop obedience, combat victory, campaign battle
integration, individual agent combat AI or player attack input. Hold uses the
engine's existing order position; custom placement remains unimplemented.

Reproduction: `bridge/smoke_battle_mcp.py`. Read-backs are durable in the private
bridge SQLite database. No token, compiled assets or private database is included.

Live bridge-restart check also passed: after stopping/restarting the bridge
process, new real stdio MCP calls recovered all four acknowledged commands and
their exact nine-formation rows. See `restart_verification` in the JSON. This
proves durable results, not recovery of a stalled paused HTTP callback loop.
