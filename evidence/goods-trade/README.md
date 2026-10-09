# Actual full-stack Native goods transactions — 2026-10-09

Real stdio MCP, isolated Native-derived WarbandMCP revision 10, engine facts,
and independent CUA captures. CUA navigated normally to Praven and opened the UI
only for separate verification; it did **not** implement buying or selling.
No save edit/write, inventory injection, memory patch or generic editor.

## Actual bread purchase

`mcp-goods-bread-buy-proof.json` retains quote, wrong-price rejection, unchanged
repeat quote, then actual successful purchase:

- Goods merchant troop 627 at Praven party 26, source inventory slot 37.
- Item 121 Bread, unmodified, full **50/50**, independently established price 46.
- Quote returned next free player slot 10; it did not reserve or mutate it.
- Execute with 47 rejected with result −6; exact quote/stock/gold unchanged.
- Execute with 46 succeeded: player **355→309**, merchant **703→749**.
- Source emptied, player slot 10 now Bread **50/50**; total gold conserved.
- [Actual Native UI after purchase](mcp-goods-bread-buy-proof.png) confirms gold
  and new bread. The tutorial modal obscures some inventory, so the following
  [full stack / actual sell tooltip](mcp-goods-bread-sale-price.png) is clearer.

## Actual sale and economic consequences

`mcp-goods-bread-sell-proof.json` records quote **41** (original sell factor 83),
matching the independent 50/50 bread sell tooltip, wrong-price rejection, unchanged
repeat quote, and actual sale of player slot 10:

- Player **309→350**, merchant **749→708**; total gold conserved.
- Player source empty; same full Bread **50/50** returned to merchant slot 37.
- [Actual Native UI after sale](mcp-goods-bread-sell-proof.png) confirms money,
  bread removal, and Native's "You got 41 denars" message. No pending barter cost.

Original `game_event_buy_item`/`game_event_sell_item` scripts update the market:
Bread factors initially **buy93/sell81**, after purchase **sell83**, after sale
**buy92/sell80**. `mcp-goods-after-roundtrip-stock.json` records all four merchant
inventories after the roundtrip. This is **not rollback**: player spent net 5,
merchant gained 5, and the town's market pricing changed.

## Engine guards and durable recovery

- `mcp-goods-engine-guards.json`: Oil quote 454, funds insufficient, execution
  rejected with −4; mismatched expected item rejected too. Exact Oil quote facts
  (stock/gold/factors) unchanged before/after. No artificial gold grant.
- Wrong-price guards tested live separately for buy and sell.
- `mcp-goods-restart-proof.json`: actual bridge restart, fresh MCP client,
  exact acknowledged executed buy/sell facts recovered. **No mutation retried.**
- Current live main party remains normally at Praven, 350 gold, clock103.
  No campaign save written; normal Native/Pendor and existing saves untouched.

## Limits and checks

Available only from actual town marketplace and exact entry session, not while
trade UI is open/captive/in dialogue. Item/slot must still match; execution
recomputes the exact agreed price, checks buyer funds/free non-equipped destination
before the first mutation, transfers the whole unmodified goods stack, and invokes
original economic event scripts. Unique goods, gear, modifiers and partial stacks
are rejected. Live transaction acceptance is **Bread only**; pricing UI legwork
also covers Oil and Tools. Broader item coverage remains further acceptance.

108 active-suite tests; targeted Ruff clean; Pyright zero errors; 121 official
opcode IDs checked. The focused control-flow test interpreter verifies quote
read-only behavior, gold/stack conservation and rejection-before-mutation paths;
it is explicitly a model, not proof of actual engine behavior. Actual JSON/UI
above provides the separate engine evidence.
