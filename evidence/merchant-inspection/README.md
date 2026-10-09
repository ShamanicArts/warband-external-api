# Actual Native merchant inspection — 2026-10-09

Real stdio MCP, original Native inventory/price-factor scripts, independent CUA
captures, isolated WarbandMCP revision 9. No token in these artifacts. CUA alone
navigated the player normally to Praven for test setup; that is **not** evidence
of MCP player travel. No save, teleport, inventory or gold edit in these tests.

## Full stock, actual gold, original pricing factors

`mcp-market-context-inventories.json` records **24 acknowledged pages / 384 slots**:

| Merchant | Slots inspected | Stocked slots | Gold |
|---|---:|---:|---:|
| Arms | 96 | 37 | 345 |
| Armor | 96 | 44 | 474 |
| Goods | 96 | 32 | 703 |
| Horses | 96 | 5 | 318 |

Slots 10 onward are non-equipped inventory; empty slots remain explicit. Actual
item ID/modifier/amount/max amount/base value and original Native buy/sell factors
are exported. Player gold stayed **355**. Previous full export is retained as
`mcp-market-inventories-proof.json`, not substituted with the newer one.

[Independent goods stock/gold capture](mcp-market-trade-context-clear.png):
merchant **703**, player **355**, rendered goods correspond to engine stock.

## Real UI context and guarded transitions

`mcp-market-trade-context.json`: with the actual inventory UI visibly open,
fresh MCP reads report **trade**, no underlying menu, continuing heartbeats.
Merchant query is rejected. Native trade entry is instrumented; menu commands
cannot target the hidden marketplace. Context returns normally after closing UI.

- `mcp-market-context-enter.json`: MCP town→marketplace.
- `mcp-market-return-town.json`: new reviewed MCP marketplace→town action.
- `mcp-market-return-map.json`: MCP town→campaign map.
- `mcp-notification-war-continue.json`, `mcp-notification-peace-continue.json`:
  actual Native notification continue actions through MCP, no CUA clicks.
  Corresponding war/peace commands and relation changes are retained too.

## Price legwork — limited, not invented final quotes

`native-unmodified-price-comparison.json` compares actual engine rows with
independent original UI tooltips:

- [Oil](mcp-native-oil-price.png): full 50/50, modifier 0, base 450, factor 101,
  actual buying price **454** (integer truncation, not rounding to 455).
- [Tools](mcp-native-tools-price.png): base 410, factor 97, actual **397**.
- [Bread](mcp-native-bread-price.png): full 50/50, base 50, factor 93, actual **46**.

Those cases match truncating `base*buy_factor/100`. They do **not** establish all
modified/partial-stack prices or sale prices. Inspection tools explicitly return
`transaction_support=false`; no claim of buying/selling through MCP yet.

## Durable results and limits

`mcp-market-restart-proof.json`: actual bridge restart, fresh stdio MCP client,
**all 24 exact merchant pages / 384 slots** recovered with acknowledged statuses.
Camp entry via CUA followed by MCP resume restarted paused polling; retained in
`mcp-market-reconnect-camp.json`. Not automatic paused-outage recovery.

101 active-suite tests, targeted Ruff clean, Pyright zero errors, 110 official
opcode IDs checked. Commands are marketplace/session scoped, bounded 16-slot
pages, out-of-order completion aware and entity checked. Pages are not one
atomic snapshot across merchants; price factors aren't final transaction quotes.
