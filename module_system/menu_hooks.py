"""Prefix Native menu-entry operations without changing IDs or option behaviour."""


def operation_end(fields, start):
    count = int(fields[start])
    if count < 0:
        raise ValueError("Negative operation count")
    cursor = start + 1
    for _ in range(count):
        int(fields[cursor])
        arity = int(fields[cursor + 1])
        if not 0 <= arity <= 16:
            raise ValueError("Invalid operation arity")
        for argument in fields[cursor + 2 : cursor + 2 + arity]:
            int(argument)
        cursor += 2 + arity
    return cursor


def instrument_menus(
    lines,
    make_prefix,
    on_return=None,
    make_suffix=None,
    on_shutdown=None,
    on_trade=None,
):
    result = list(lines)
    names = []
    for index, line in enumerate(lines):
        if not line.startswith("menu_"):
            continue
        fields = line.split()
        try:
            count = int(fields[4])
            cursor = operation_end(fields, 4)
            if cursor != len(fields) - 1 or int(fields[cursor]) < 0:
                raise ValueError("Invalid option count seam")
            prefix = make_prefix(len(names)).split()
            suffix = make_suffix(len(names)).split() if make_suffix else ["0"]
            fields[4] = str(count + int(prefix[0]) + int(suffix[0]))
            result[index] = " ".join(
                [
                    *fields[:5],
                    *prefix[1:],
                    *fields[5:-1],
                    *suffix[1:],
                    fields[-1],
                ]
            )
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Invalid Native menu seam: {fields[0]}") from exc
        names.append(fields[0][5:])
    if not names:
        raise ValueError("No Native menus found")
    if on_return or on_shutdown or on_trade:
        return_prefix = on_return.split() if on_return else ["0"]
        shutdown_prefix = on_shutdown.split() if on_shutdown else ["0"]
        trade_prefix = on_trade.split() if on_trade else ["0"]
        for index, line in enumerate(result):
            if not line.lstrip().startswith("mno_"):
                continue
            fields = line.split()
            output = []
            cursor = 0
            try:
                while cursor < len(fields):
                    start = cursor
                    if not fields[cursor].startswith("mno_"):
                        raise ValueError("Expected Native menu option")
                    cursor = operation_end(fields, cursor + 1) + 1  # skip text
                    count = int(fields[cursor])
                    output.extend(fields[start:cursor])
                    cursor += 1
                    consequences = []
                    added = 0
                    for _ in range(count):
                        opcode, arity = int(fields[cursor]), int(fields[cursor + 1])
                        if opcode in (2040, 2052):  # return / map screen
                            prefix = return_prefix
                            consequences.extend(prefix[1:])
                            added += int(prefix[0])
                        if opcode == 2055:  # quit to main menu: runtime troops unload
                            consequences.extend(shutdown_prefix[1:])
                            added += int(shutdown_prefix[0])
                        if opcode == 2042:  # trade UI, NOT the underlying menu
                            consequences.extend(trade_prefix[1:])
                            added += int(trade_prefix[0])
                        consequences.extend(fields[cursor : cursor + 2 + arity])
                        cursor += 2 + arity
                    if fields[cursor].startswith("mno_"):
                        raise ValueError("Missing option tooltip")
                    output.extend([str(count + added), *consequences, fields[cursor]])
                    cursor += 1
            except (ValueError, IndexError) as exc:
                raise ValueError(
                    f"Invalid Native menu option seam at line {index + 1}"
                ) from exc
            result[index] = " " + " ".join(output)
    return result, names
