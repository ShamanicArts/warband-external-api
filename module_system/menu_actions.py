"""Compile a reviewed allowlist of actual Native conditions and consequences.

Native compiler gives each block its own local-variable namespace. Conditions
and consequences must remain separate scripts; joining their raw blocks would
alias locals. IDs are additive, and clients cannot supply scripts/bytecode.
"""

from module_system.menu_hooks import operation_end

ALLOWLIST = {
    "camp": {"camp_action", "resume_travelling"},
    "village": {"recruit_volunteers", "village_center", "village_leave"},
    "recruit_volunteers": {
        "recruit_them",
        "forget_it",
        "continue",
        "continue_not_enough_gold",
    },
    "town": {
        "town_center",
        "town_tavern",
        "town_arena",
        "town_castle",
        "town_leave",
        "trade_with_merchants",
    },
}


def parse_menus(lines):
    menus = []
    for line in lines:
        if line.startswith("menu_"):
            f = line.split()
            end = operation_end(f, 4)
            menus.append(
                {
                    "id": len(menus),
                    "name": f[0][5:],
                    "initializer": f[4:end],
                    "options": [],
                }
            )
        elif line.lstrip().startswith("mno_"):
            f = line.split()
            cursor = 0
            while cursor < len(f):
                end = operation_end(f, cursor + 1)
                end2 = operation_end(f, end + 1)
                menus[-1]["options"].append(
                    {
                        "name": f[cursor][4:],
                        "text_template": f[end].replace("_", " "),
                        "condition": f[cursor + 1 : end],
                        "consequence": f[end + 1 : end2],
                    }
                )
                cursor = end2 + 1
    return menus


def combine(*blocks):
    return " ".join(
        [
            str(sum(int(b[0]) for b in blocks)),
            *[token for b in blocks for token in b[1:]],
        ]
    )


def append_actions(lines, first_script, compile_ops, result_slot):
    actions, scripts = [], []
    for menu in parse_menus(lines):
        for option in menu["options"]:
            if option["name"] not in ALLOWLIST.get(menu["name"], set()):
                continue
            action_id = len(actions)
            condition_script = first_script + len(scripts) // 2
            condition = combine(
                compile_ops(
                    [("troop_set_slot", 5 << 56, result_slot, -3), ("try_begin",)]
                ).split(),
                option["condition"],
                compile_ops(
                    [("troop_set_slot", 5 << 56, result_slot, 0), ("try_end",)]
                ).split(),
            )
            scripts.extend([f"mcp_menu_condition_{action_id} -1", condition])
            consequence_script = first_script + len(scripts) // 2
            scripts.extend(
                [f"mcp_menu_action_{action_id} -1", " ".join(option["consequence"])]
            )
            actions.append(
                {
                    "id": action_id,
                    "menu_id": menu["id"],
                    "menu": menu["name"],
                    "option": option["name"],
                    "text_template": option["text_template"],
                    "condition_script": condition_script,
                    "consequence_script": consequence_script,
                }
            )
    return scripts, actions
