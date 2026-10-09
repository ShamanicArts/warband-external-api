"""Read real town merchant inventory and Native price factors, not guessed quotes."""

REG, LOCAL, SCRIPT = 1 << 56, 17 << 56, 13 << 56


def market_export(row_url, end_url, globals_, scripts, troop_count, market_menu_id):
    required = ("game_get_item_buy_price_factor", "game_get_item_sell_price_factor")
    if "current_town" not in globals_ or any(name not in scripts for name in required):
        return [("eq", 0, 1)]
    town, merchant, size, emitted, slot, item = [LOCAL + i for i in range(25, 31)]
    return [
        ("eq", LOCAL + 9, market_menu_id),
        ("assign", town, globals_["current_town"]),
        ("eq", town, globals_.get("g_encountered_party", -1)),
        ("party_is_active", town),
        ("ge", LOCAL + 5, 0),
        ("le", LOCAL + 5, 3),
        ("ge", LOCAL + 6, 0),
        ("le", LOCAL + 6, 10000),
        ("ge", LOCAL + 16, 1),
        ("le", LOCAL + 16, 16),
        # Official Native slots: arms 21, armor 22, goods 23, horses 24.
        ("store_add", LOCAL + 31, LOCAL + 5, 21),
        ("party_get_slot", merchant, town, LOCAL + 31),
        ("ge", merchant, 1),
        ("lt", merchant, troop_count),
        ("troop_get_inventory_capacity", size, merchant),
        ("assign", emitted, 0),
        ("try_for_range", slot, LOCAL + 6, size),
        ("lt", emitted, LOCAL + 16),
        ("troop_get_inventory_slot", item, merchant, slot),
        ("assign", LOCAL + 32, 0),
        ("assign", LOCAL + 33, 0),
        ("assign", LOCAL + 34, 0),
        ("try_begin",),
        ("ge", item, 0),
        ("store_item_value", LOCAL + 32, item),
        ("call_script", SCRIPT + scripts[required[0]], item),
        ("assign", LOCAL + 33, REG),
        ("call_script", SCRIPT + scripts[required[1]], item),
        ("assign", LOCAL + 34, REG),
        ("try_end",),
        # Native price scripts use registers: read slot data AFTER calling them.
        ("troop_get_inventory_slot_modifier", REG + 23, merchant, slot),
        ("troop_inventory_slot_get_item_amount", REG + 24, merchant, slot),
        ("troop_inventory_slot_get_item_max_amount", REG + 25, merchant, slot),
        ("assign", REG + 20, LOCAL + 3),
        ("assign", REG + 21, slot),
        ("assign", REG + 22, item),
        ("assign", REG + 26, LOCAL + 32),
        ("assign", REG + 27, LOCAL + 33),
        ("assign", REG + 28, LOCAL + 34),
        ("assign", REG + 29, merchant),
        ("assign", REG + 30, town),
        ("str_store_string", 127, row_url),
        ("send_message_to_url", 127, 0),
        ("val_add", emitted, 1),
        ("try_end",),
        ("assign", REG + 20, LOCAL + 3),
        ("assign", REG + 21, size),
        ("assign", REG + 22, emitted),
        ("store_troop_gold", REG + 23, merchant),
        ("assign", REG + 24, merchant),
        ("assign", REG + 25, town),
        ("str_store_string", 127, end_url),
        ("send_message_to_url", 127, 0),
        ("assign", LOCAL + 10, 0),
    ]
