# Actual Native campaign-world evidence — 2026-10-09

Real stdio MCP calls to isolated Native-derived WarbandMCP revision 8, actual
engine results, and independent CUA captures. Original JSON contains no token.
Normal Native/Pendor modules and existing saves were not changed. These tests
mutated only the isolated running campaign; no save was written.

## Kingdom control

- `mcp-world-faction-query.json`: Swadia 15, Vaegirs 16, relation 0; leaders
  210/211 and active faction states read from the engine while in village menu.
- `mcp-world-ruler-guard.json`: normal war request rejected with engine result −1
  because this player is not the faction ruler. No world override implied.
- `mcp-world-war-proof.json`: explicit world intervention called Native
  `diplomacy_start_war_between_kingdoms`; relation **0 → −40**.
  [Actual Declaration of War screen](mcp-world-war-proof.png).
- `mcp-world-peace-proof.json`: Native peace script, relation **−40 → 0**.
  [Actual Peace Agreement screen](mcp-world-peace-proof.png).

Native scripts include logs, notifications, diplomatic consequences and possible
prisoner/quest/siege changes. Peace is **not** rollback of the war's consequences.
These are not generic relation setters or fake notifications. Normal ruler
authority success remains untested; explicit world override and rejection pass.

## Real time and target-directed NPC campaign travel

`mcp-npc-party-travel-proof.json`:

- Authenticated current campaign census identified party 386, Forest Bandits.
- Before: behavior 3/patrol, object 229, position **(−54.94, 4.32)**.
- Explicit world control set travel to party 26; read-back behavior 1/object 26.
- MCP started Native attackable interactive rest (1 hour, speed 5).
- Real clock **102 → 103**, NPC position **(−58.42, 6.09)**.
- Movement **3.9043 map units**, distance to target improved **3.9032** units.
- MCP stopped resting with Native `rest_for_hours(0,0,0)`; acknowledged.
- `mcp-world-npc-candidates.json` retains fresh engine census provenance.
- [Independent campaign screenshot](mcp-npc-party-travel-proof.png) does not
  visually identify the remote bandit party; its exact motion comes from the
  engine getter evidence. No claim of visual trajectory confirmation.

No party teleport, clock assignment, save editing, or CUA implementation.
Native AI can later replace the requested behavior; no permanent AI override.

## Player travel investigation — not established

`mcp-world-player-ai-proof.json`: main-party AI setting read back travel/object
26 successfully, but that alone establishes only an AI setting.

`mcp-player-travel-time-test.json`: real time advanced during resting, while
main-party motion measured **0**. **Resting holds the player stationary**, so this
does not prove the player controller cannot travel with an AI destination when
time runs outside rest. It does prove this combination is not player travel.
`smoke_campaign_time_mcp.py` fails acceptance instead of silently passing zero
movement. Player travel, destination arrival, encounters, NPC patrol/attack/
avoid/escort and normal ruler diplomacy remain further acceptance work.

## Regression / reproduction

95 active-suite tests, targeted Ruff clean, Pyright zero errors, 108 opcode IDs
checked against pinned official headers. Faction catalog now accounts for
Native's `0 fac_next ...` note-count seam: all 34 IDs and seven kingdom IDs
preserved. World results are persisted separately from acknowledgements and
validate that returned entity IDs match the command. `mcp-world-restart-proof.json`
records an actual bridge restart and a fresh stdio MCP client: exact war/peace/
NPC facts recovered with acknowledged command statuses. This is durable-result
recovery, not proof of recovery of an interrupted paused HTTP polling loop.
