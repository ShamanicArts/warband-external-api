"""Control-flow safety model, NOT a substitute for real engine acceptance."""

import unittest

from module_system.goods_trade import LOCAL, REG, SCRIPT, TROOP, goods_trade


class TradeFlow:
    def __init__(self, mode=2, price=46):
        self.vars = {
            LOCAL + 3: 1,
            LOCAL + 5: mode,
            LOCAL + 6: 1210010,
            LOCAL + 9: 135,
            LOCAL + 10: -1,
            LOCAL + 16: price,
        }
        self.slots = {(300, 10): [121, 0, 50, 50]}
        self.gold = {300: 703, TROOP: 355}
        self.kind, self.unique = 11, False
        self.events, self.mutations = [], []
        self.globals = {
            "current_town": 26,
            "g_encountered_party": 26,
            "g_player_is_captive": 0,
        }
        self.scripts = {
            name: i
            for i, name in enumerate(
                (
                    "game_get_item_buy_price_factor",
                    "game_get_item_sell_price_factor",
                    "game_event_buy_item",
                    "game_event_sell_item",
                )
            )
        }

    def value(self, operand):
        return self.vars.get(operand, 0) if operand >> 56 in (1, 17) else operand

    def slot(self, troop, slot):
        return self.slots.get((troop, slot), [-1, 0, 0, 0])

    def operation(self, op):
        name, *raw = op
        args = [self.value(a) for a in raw]
        if name in ("eq", "ge", "le", "lt"):
            a, b = args
            return {"eq": a == b, "ge": a >= b, "le": a <= b, "lt": a < b}[name]
        if name == "party_is_active":
            return args[0] == 26
        if name == "not_item_has_property":
            return not self.unique
        if name == "assign":
            self.vars[raw[0]] = args[1]
        elif name in ("store_mod", "store_div"):
            self.vars[raw[0]] = (
                args[1] % args[2] if name == "store_mod" else args[1] // args[2]
            )
        elif name in ("val_mul", "val_div"):
            self.vars[raw[0]] = (
                args[0] * args[1] if name == "val_mul" else args[0] // args[1]
            )
        elif name == "party_get_slot":
            self.vars[raw[0]] = 300
        elif name == "troop_get_inventory_capacity":
            self.vars[raw[0]] = 12
        elif name in (
            "troop_get_inventory_slot",
            "troop_get_inventory_slot_modifier",
            "troop_inventory_slot_get_item_amount",
            "troop_inventory_slot_get_item_max_amount",
        ):
            index = {
                "troop_get_inventory_slot": 0,
                "troop_get_inventory_slot_modifier": 1,
                "troop_inventory_slot_get_item_amount": 2,
                "troop_inventory_slot_get_item_max_amount": 3,
            }[name]
            self.vars[raw[0]] = self.slot(args[1], args[2])[index]
        elif name == "item_get_type":
            self.vars[raw[0]] = self.kind
        elif name == "store_item_value":
            self.vars[raw[0]] = 50
        elif name == "store_troop_gold":
            self.vars[raw[0]] = self.gold[args[1]]
        elif name == "call_script":
            script = args[0] - SCRIPT
            if script < 2:
                self.vars[REG] = 93 if script == 0 else 81
            else:
                self.events.append((script, *args[1:]))
        elif name in (
            "troop_set_inventory_slot",
            "troop_set_inventory_slot_modifier",
            "troop_inventory_slot_set_item_amount",
        ):
            self.mutations.append(op)
            data = list(self.slot(args[0], args[1]))
            index = {
                "troop_set_inventory_slot": 0,
                "troop_set_inventory_slot_modifier": 1,
                "troop_inventory_slot_set_item_amount": 2,
            }[name]
            data[index] = args[2]
            if name == "troop_set_inventory_slot":
                data[2:] = [50, 50] if args[2] >= 0 else [0, 0]
            self.slots[args[0], args[1]] = data
        elif name in ("troop_add_gold", "troop_remove_gold"):
            self.mutations.append(op)
            self.gold[args[0]] += args[1] * (1 if name == "troop_add_gold" else -1)
        elif name not in ("str_store_string", "send_message_to_url"):
            raise AssertionError(name)
        return True

    def block(self, ops):
        i, alternative = 0, False
        while i < len(ops):
            op = ops[i]
            if op[0] in ("try_begin", "try_for_range"):
                depth, j, branches, start = 1, i + 1, [], i + 1
                while depth:
                    name = ops[j][0]
                    if name in ("try_begin", "try_for_range"):
                        depth += 1
                    elif name == "try_end":
                        depth -= 1
                    if depth == 1 and name == "else_try":
                        branches.append(ops[start:j])
                        start = j + 1
                    j += 1
                branches.append(ops[start : j - 1])
                if op[0] == "try_begin":
                    for branch in branches:
                        if self.block(branch):
                            break
                else:
                    for value in range(self.value(op[2]), self.value(op[3])):
                        self.vars[op[1]] = value
                        self.block(branches[0])
                i = j
                continue
            if op[0] == "or_eq":
                alternative |= self.value(op[1]) == self.value(op[2])
            else:
                passed = self.operation(op)
                if not (passed or alternative):
                    return False
                alternative = False
            i += 1
        return True

    def run(self):
        self.block(goods_trade(0, self.globals, self.scripts, 1000, 500, 135))
        return self.vars[LOCAL + 10]


class GoodsTradeTests(unittest.TestCase):
    def test_complete_adapter_compiles_all_reviewed_opcodes(self):
        from module_system import test_build_mcp_module as build_tests
        from module_system.build_mcp_module import callback

        flow = TradeFlow()
        compiled = callback(
            native_globals=flow.globals,
            native_scripts=flow.scripts,
            item_count=500,
            troop_count=1000,
            market_menu_id=135,
        )
        build_tests.ModuleBuildTests.assert_balanced(self, compiled)

    def test_quote_is_read_only_even_with_no_funds(self):
        flow = TradeFlow(mode=0)
        flow.gold[TROOP] = 0
        self.assertEqual(flow.run(), 0)
        self.assertEqual(flow.vars[REG + 25], 46)
        self.assertEqual(flow.vars[REG + 35], 0)
        self.assertEqual(flow.mutations, [])
        self.assertEqual(flow.events, [])

    def test_buy_conserves_gold_and_full_stack_calls_original_event(self):
        flow = TradeFlow()
        self.assertEqual(flow.run(), 0)
        self.assertEqual(flow.gold, {TROOP: 309, 300: 749})
        self.assertEqual(flow.slot(TROOP, 10), [121, 0, 50, 50])
        self.assertEqual(flow.slot(300, 10)[0], -1)
        self.assertEqual(flow.events, [(2, 121, 0)])

    def test_sell_and_quote_use_sell_factor_not_buy_factor(self):
        flow = TradeFlow(mode=3, price=40)
        flow.slots = {(TROOP, 10): [121, 0, 50, 50]}
        self.assertEqual(flow.run(), 0)
        self.assertEqual(flow.gold, {TROOP: 395, 300: 663})
        self.assertEqual(flow.events, [(3, 121, 0)])

    def test_all_rejections_precede_first_mutation(self):
        cases = [
            "price",
            "funds",
            "full",
            "partial",
            "modifier",
            "gear",
            "unique",
            "item",
            "captive",
            "town",
        ]
        for case in cases:
            with self.subTest(case=case):
                flow = TradeFlow()
                if case == "price":
                    flow.vars[LOCAL + 16] = 47
                if case == "funds":
                    flow.gold[TROOP] = 45
                if case == "full":
                    flow.slots.update({(TROOP, n): [121, 0, 50, 50] for n in (10, 11)})
                if case == "partial":
                    flow.slots[300, 10][2] = 49
                if case == "modifier":
                    flow.slots[300, 10][1] = 1
                if case == "gear":
                    flow.kind = 1
                if case == "unique":
                    flow.unique = True
                if case == "item":
                    flow.slots[300, 10][0] = 120
                if case == "captive":
                    flow.globals["g_player_is_captive"] = 1
                if case == "town":
                    flow.globals["g_encountered_party"] = 27
                self.assertNotEqual(flow.run(), 0)
                self.assertEqual(flow.mutations, [])
                self.assertEqual(flow.events, [])
