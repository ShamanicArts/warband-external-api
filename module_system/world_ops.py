"""Native campaign party/diplomacy adapters; no client-supplied scripts/slots."""

REG, LOCAL, TROOP, PARTY, SCRIPT = 1 << 56, 17 << 56, 5 << 56, 9 << 56, 13 << 56


def active_party(party):
    # Validate membership before passing a supplied ID to engine party getters.
    return [
        ("assign", LOCAL + 28, 0),
        ("try_for_parties", LOCAL + 27),
        ("eq", LOCAL + 27, party),
        ("party_is_active", LOCAL + 27),
        ("assign", LOCAL + 28, 1),
        ("try_end",),
        ("eq", LOCAL + 28, 1),
    ]


def report(url, entity_kind, entity, other, fields):
    return [
        ("assign", REG + 20, LOCAL + 3),
        ("assign", REG + 21, entity_kind),
        ("assign", REG + 22, entity),
        ("assign", REG + 23, other),
        *fields,
        ("str_store_string", 127, url),
        ("send_message_to_url", 127, 0),
        ("assign", LOCAL + 10, 0),
    ]


def faction_report(url, left, right):
    return report(
        url,
        1,
        left,
        right,
        [
            ("store_relation", REG + 24, left, right),
            ("faction_get_slot", REG + 25, left, 11),
            ("faction_get_slot", REG + 26, left, 21),
            ("faction_get_color", REG + 27, left),
            ("faction_get_slot", REG + 28, right, 11),
            ("faction_get_slot", REG + 29, right, 21),
        ],
    )


def party_report(url, party):
    return report(
        url,
        2,
        party,
        -1,
        [
            ("get_party_ai_behavior", REG + 24, party),
            ("get_party_ai_object", REG + 25, party),
            ("party_get_ai_initiative", REG + 26, party),
            ("store_faction_of_party", REG + 27, party),
            ("party_get_position", 2, party),
            ("position_get_x", REG + 28, 2),
            ("position_get_y", REG + 29, 2),
        ],
    )


def query(url, faction_count):
    kind, entity, other = LOCAL + 5, LOCAL + 6, LOCAL + 16
    return [
        ("try_begin",),
        ("eq", kind, 1),
        ("ge", entity, 0),
        ("lt", entity, faction_count),
        ("ge", other, 0),
        ("lt", other, faction_count),
        *faction_report(url, entity, other),
        ("else_try",),
        ("eq", kind, 2),
        *active_party(entity),
        *party_report(url, entity),
        ("try_end",),
    ]


def diplomacy(url, kingdom_ids, scripts, globals_):
    left, right, action = LOCAL + 5, LOCAL + 6, LOCAL + 16
    if not kingdom_ids or any(
        name not in scripts
        for name in (
            "diplomacy_start_war_between_kingdoms",
            "diplomacy_start_peace_between_kingdoms",
        )
    ):
        return [("eq", 0, 1)]

    def valid_kingdom(value):
        # this_or_next|eq on every item except the final one.
        return [
            ("or_eq" if i + 1 < len(kingdom_ids) else "eq", value, faction)
            for i, faction in enumerate(kingdom_ids)
        ]

    return [
        *valid_kingdom(left),
        *valid_kingdom(right),
        ("neq", left, right),
        ("faction_slot_eq", left, 21, 0),
        ("faction_slot_eq", right, 21, 0),
        ("assign", LOCAL + 25, 0),
        ("try_begin",),
        ("ge", action, 100),
        ("le", action, 102),
        ("val_sub", action, 100),
        ("assign", LOCAL + 25, 1),
        ("else_try",),
        ("eq", left, globals_.get("players_kingdom", -1)),
        ("faction_slot_eq", left, 11, TROOP),
        ("assign", LOCAL + 25, 1),
        ("try_end",),
        ("eq", LOCAL + 25, 1),
        ("try_begin",),
        ("eq", action, 1),
        (
            "call_script",
            SCRIPT + scripts["diplomacy_start_war_between_kingdoms"],
            left,
            right,
            1,
        ),
        *faction_report(url, left, right),
        ("else_try",),
        ("eq", action, 2),
        (
            "call_script",
            SCRIPT + scripts["diplomacy_start_peace_between_kingdoms"],
            left,
            right,
            1,
        ),
        *faction_report(url, left, right),
        ("try_end",),
    ]


def party_order(url):
    encoded, behavior, target = LOCAL + 5, LOCAL + 6, LOCAL + 16
    actor = LOCAL + 25
    return [
        ("assign", actor, encoded),
        ("assign", LOCAL + 26, 0),
        ("try_begin",),
        ("ge", actor, 1000000),
        ("val_sub", actor, 1000000),
        ("assign", LOCAL + 26, 1),
        ("else_try",),
        ("eq", actor, PARTY),
        ("assign", LOCAL + 26, 1),
        ("try_end",),
        ("eq", LOCAL + 26, 1),
        *active_party(actor),
        ("party_get_slot", LOCAL + 29, actor, 0),
        ("neq", LOCAL + 29, 2),
        ("neq", LOCAL + 29, 3),
        ("neq", LOCAL + 29, 4),
        ("neq", LOCAL + 29, 18),
        ("try_begin",),
        ("eq", behavior, 0),
        ("party_set_ai_behavior", actor, 0),
        *party_report(url, actor),
        ("else_try",),
        *active_party(target),
        ("neq", actor, target),
        ("or_eq", behavior, 1),
        ("or_eq", behavior, 3),
        ("or_eq", behavior, 4),
        ("or_eq", behavior, 5),
        ("eq", behavior, 10),
        ("party_set_ai_object", actor, target),
        ("party_set_ai_behavior", actor, behavior),
        *party_report(url, actor),
        ("try_end",),
    ]
