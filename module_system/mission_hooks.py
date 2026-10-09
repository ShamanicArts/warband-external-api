"""Validated additive trigger insertion for compiled single-player missions."""


def instrument_missions(lines, make_triggers):
    seams = []
    names = []
    headers = [i for i, line in enumerate(lines) if line.startswith("mst_")]
    for mission_id, start in enumerate(headers):
        header = lines[start].split()
        name = header[0][4:]
        if name.startswith("multiplayer"):
            continue
        boundary = (
            headers[mission_id + 1] if mission_id + 1 < len(headers) else len(lines)
        )
        spawn_line = start + 3
        try:
            spawn_fields = lines[spawn_line].split()
            spawn_count = int(spawn_fields[0])
            collapsed = spawn_count == 0 and len(spawn_fields) == 2
            trigger_line = spawn_line if collapsed else spawn_line + max(spawn_count, 1)
            count = int(spawn_fields[1] if collapsed else lines[trigger_line])
            if spawn_count < 0 or count < 0 or trigger_line + count >= boundary:
                raise ValueError("Invalid trigger/spawn bounds")
            for trigger in lines[trigger_line + 1 : trigger_line + 1 + count]:
                fields = trigger.split()
                if len(fields) < 5:
                    raise ValueError("Malformed Native trigger")
                for value in fields[:3]:
                    float(value)
            added = make_triggers(mission_id, int(header[2]))
        except (IndexError, ValueError) as exc:
            raise ValueError(f"Invalid mission template seam: {name}") from exc
        seams.append((trigger_line, count, added, collapsed))
        names.append(name)
    if not seams:
        raise ValueError("No single-player mission templates found")
    result = list(lines)
    for trigger_line, count, added, collapsed in reversed(seams):
        result[trigger_line] = ("0 " if collapsed else "") + str(count + len(added))
        result[trigger_line + 1 + count : trigger_line + 1 + count] = added
    return result, names
