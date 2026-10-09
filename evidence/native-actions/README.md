# Actual Native-action MCP evidence — 2026-10-09

These are retained **original game captures and actual stdio MCP call results**,
not mocked data or screenshots of a prototype. Integration revision 5, isolated
WarbandMCP module derived from Native, copied Proton prefix. Pendor untouched.
CUA performed setup/travel and independent visual inspection. It did **not**
execute the menu choices under test; those came through the stdio MCP/game scripts.

## Paid recruitment

- Before: one player, **365 denars**.
- Native offer at Azgad: **one Swadian Recruit, 10 denars**.
- `warband_select_menu` ran Native `recruit_them`, acknowledged by the game.
- After: **two party members, 355 denars**, including one Swadian Recruit.
- [Actual MCP calls/state/party snapshots](mcp-paid-recruitment-proof.json)
- [Native offer screen](mcp-azgad-recruit-offer-proof.png)
- [Independent Native Party-screen confirmation](mcp-paid-recruitment-party-proof.png)

## Native conditions really apply

Iyindah had no volunteers. Attempting `recruit_them` was rejected by the actual
Native condition block with **result -3**, money unchanged at 365 denars.

- [Actual rejected command and state](mcp-no-volunteers-rejection-proof.json)
- [Native no-volunteers screen](mcp-recruit-offer-proof.png)

## Menu control and real scene entry

- [Camp→actions-menu command/state](mcp-camp-action-proof.json)
- [Independent actions-menu screenshot](mcp-camp-action-proof.png)
- [Camp→map command/state](mcp-camp-return-proof.json)
- [MCP Native village entry command/state](mcp-native-village-entry-proof.json)
- [Independent rendered Azgad scene screenshot](mcp-native-village-entry-proof.png)

Azgad entry reported scene 376, `village_center` mission template 3, player agent
15 and HP 49. The transition was the original Native consequence, not teleport.

## Scope of this proof

This proves the listed actions, not full game control. Travel was still CUA-driven.
Combat orders, transaction-level trade, broader political/quest controls and
multi-turn free-text NPC interaction are unfinished. Screenshots prove visible
results; JSON records MCP transport, game acknowledgements and engine-state deltas.

Reproduction harness: `bridge/smoke_native_menu_mcp.py`. Do not run a mutating
acceptance command against a valued campaign save. Credentials, compiled token-
bearing files, game assets and runtime databases are not included here.
