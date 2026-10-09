"""Native campaign export operations, consumed by the additive bytecode builder.

No changing gold, troop counts, quest state or inventory. A page is at most 16
rows; completion records carry the full count so clients can request next pages.
"""

REG, LOCAL, TROOP, PARTY = 1 << 56, 17 << 56, 5 << 56, 9 << 56


def campaign_export(row_url, end_url, quest_count, skill_count):
    # Callback's command ID and wire arguments are already saved in local vars.
    job, dataset, offset, limit = LOCAL + 3, LOCAL + 5, LOCAL + 6, LOCAL + 16
    index, total, emitted, size = LOCAL + 17, LOCAL + 18, LOCAL + 19, LOCAL + 20
    row = [
        ("assign", REG + 20, job),
        ("assign", REG + 21, dataset),
        ("assign", REG + 22, index),
    ]

    # Six integer fields, interpretation defined by the selected dataset.
    def emit(fields):
        return [
            ("try_begin",),
            ("ge", total, offset),
            ("lt", emitted, limit),
            *row,
            *[("assign", REG + n, 0) for n in range(23, 29)],
            *fields,
            ("str_store_string", 127, row_url),
            ("send_message_to_url", 127, 0),
            ("val_add", emitted, 1),
            ("try_end",),
            ("val_add", total, 1),
        ]

    return [
        ("assign", total, 0),
        ("assign", emitted, 0),
        ("try_begin",),
        ("eq", dataset, 1),
        ("party_get_num_companion_stacks", size, PARTY),
        ("try_for_range", index, 0, size),
        *emit(
            [
                ("party_stack_get_troop_id", REG + 23, PARTY, index),
                ("party_stack_get_size", REG + 24, PARTY, index),
                ("party_stack_get_num_wounded", REG + 25, PARTY, index),
            ]
        ),
        ("try_end",),
        ("else_try",),
        ("eq", dataset, 2),
        ("party_get_num_prisoner_stacks", size, PARTY),
        ("try_for_range", index, 0, size),
        *emit(
            [
                ("party_prisoner_stack_get_troop_id", REG + 23, PARTY, index),
                ("party_prisoner_stack_get_size", REG + 24, PARTY, index),
            ]
        ),
        ("try_end",),
        ("else_try",),
        ("eq", dataset, 3),
        ("troop_get_inventory_capacity", size, TROOP),
        ("try_for_range", index, 0, size),
        *emit(
            [
                ("troop_get_inventory_slot", REG + 23, TROOP, index),
                ("try_begin",),
                ("ge", REG + 23, 0),
                ("troop_get_inventory_slot_modifier", REG + 24, TROOP, index),
                ("troop_inventory_slot_get_item_amount", REG + 25, TROOP, index),
                ("try_end",),
            ]
        ),
        ("try_end",),
        ("else_try",),
        ("eq", dataset, 4),
        ("assign", index, 0),
        *emit([("store_character_level", REG + 23, TROOP)]),
        ("try_for_range", index, 1, 5),
        ("store_sub", LOCAL + 21, index, 1),
        *emit([("store_attribute_level", REG + 23, TROOP, LOCAL + 21)]),
        ("try_end",),
        ("try_for_range", index, 5, 5 + skill_count),
        ("store_sub", LOCAL + 21, index, 5),
        *emit([("store_skill_level", REG + 23, LOCAL + 21, TROOP)]),
        ("try_end",),
        ("else_try",),
        ("eq", dataset, 5),
        ("try_for_parties", index),
        ("party_is_active", index),
        *emit(
            [
                ("store_faction_of_party", REG + 23, index),
                ("party_get_template_id", REG + 24, index),
                ("party_get_slot", REG + 25, index, 0),
                ("party_get_num_companions", REG + 26, index),
                ("party_get_position", 2, index),
                ("position_get_x", REG + 27, 2),
                ("position_get_y", REG + 28, 2),
            ]
        ),
        ("try_end",),
        ("else_try",),
        ("eq", dataset, 6),
        ("try_for_range", index, 0, quest_count),
        ("check_quest_active", index),
        *emit(
            [
                ("quest_get_slot", REG + 23, index, 6),
                ("quest_get_slot", REG + 24, index, 2),
                ("quest_get_slot", REG + 25, index, 1),
                ("quest_get_slot", REG + 26, index, 11),
                ("quest_get_slot", REG + 27, index, 23),
            ]
        ),
        ("try_end",),
        ("try_end",),
        ("assign", REG + 20, job),
        ("assign", REG + 21, dataset),
        ("assign", REG + 29, emitted),
        ("assign", REG + 30, total),
        ("str_store_string", 127, end_url),
        ("send_message_to_url", 127, 0),
        ("assign", LOCAL + 10, 0),
    ]
