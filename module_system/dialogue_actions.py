"""Parse compiled dialogue entries without claiming runtime availability.

Warband's conversation file is a graph of NPC lines and player choices.  Parsing
that graph is necessary for capability discovery, but a parsed player entry is
only a candidate: its condition block still has to succeed in the live dialogue
context before it can be offered or executed.
"""

from module_system.menu_hooks import operation_end

PLAYER_FLAG = 1 << 16


def parse_dialogue_states(lines):
    """Return the compiled state ID/name mapping, preserving file order."""
    names = [line.strip() for line in lines if line.strip()]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate Native dialogue state name")
    return {index: name for index, name in enumerate(names)}


def parse_dialogues(lines, state_names):
    """Parse a complete version-2 ``conversation.txt`` into reviewed records."""
    if len(lines) < 2 or lines[0].strip() != "dialogsfile version 2":
        raise ValueError("Expected Warband dialogsfile version 2")
    try:
        expected = int(lines[1])
    except ValueError as exc:
        raise ValueError("Invalid Native dialogue entry count") from exc
    source = [line for line in lines[2:] if line.strip()]
    if expected != len(source):
        raise ValueError("Native dialogue entry count mismatch")

    entries = []
    for index, line in enumerate(source):
        fields = line.split()
        try:
            symbol = fields[0]
            if not symbol.startswith("dlga_") or ":" not in symbol:
                raise ValueError("Invalid dialogue symbol")
            speaker = int(fields[1])
            input_state = int(fields[2])
            condition_end = operation_end(fields, 3)
            text = fields[condition_end]
            output_state = int(fields[condition_end + 1])
            consequence_start = condition_end + 2
            consequence_end = operation_end(fields, consequence_start)
            if consequence_end != len(fields) - 1:
                raise ValueError("Unexpected dialogue fields after consequence block")
            voiceover = fields[consequence_end]
        except (IndexError, ValueError) as exc:
            raise ValueError(
                f"Invalid Native dialogue entry at line {index + 3}"
            ) from exc

        source_symbol, target_symbol = symbol[5:].split(":", 1)
        entries.append(
            {
                "id": index,
                "symbol": symbol[5:],
                "source_symbol": source_symbol,
                "target_symbol": target_symbol,
                "speaker": speaker,
                "player_choice": bool(speaker & PLAYER_FLAG),
                "input_state_id": input_state,
                "input_state": state_names.get(input_state),
                "output_state_id": output_state,
                "output_state": state_names.get(output_state),
                "text_template": text.replace("_", " "),
                "condition": fields[3:condition_end],
                "consequence": fields[consequence_start:consequence_end],
                "voiceover": voiceover,
            }
        )
    return entries


def player_choice_catalog(entries):
    """Return static player-choice metadata without raw operation blocks."""
    return [
        {
            key: entry[key]
            for key in (
                "id",
                "symbol",
                "input_state_id",
                "input_state",
                "output_state_id",
                "output_state",
                "text_template",
            )
        }
        for entry in entries
        if entry["player_choice"]
    ]


def dialogue_catalog(entries):
    """Return safe static metadata for validating engine-emitted dialogue events."""
    return [
        {
            key: entry[key]
            for key in (
                "id",
                "symbol",
                "speaker",
                "player_choice",
                "input_state_id",
                "input_state",
                "output_state_id",
                "output_state",
                "text_template",
            )
        }
        for entry in entries
    ]


def instrument_dialogues(lines, entries, make_suffix):
    """Append evidence operations without changing Native conditions or operations.

    ``make_suffix`` receives the corresponding parsed entry and returns a compiled
    operation block.  Only the consequence count and appended operation tokens are
    changed; speaker, states, text, voiceover, conditions, and original consequence
    tokens retain their order and values.
    """
    result = list(lines)
    source_indexes = [i for i, line in enumerate(lines[2:], start=2) if line.strip()]
    if len(source_indexes) != len(entries):
        raise ValueError("Dialogue instrumentation entry mismatch")

    for source_index, entry in zip(source_indexes, entries, strict=True):
        fields = lines[source_index].split()
        try:
            condition_end = operation_end(fields, 3)
            consequence_start = condition_end + 2
            consequence_end = operation_end(fields, consequence_start)
            if consequence_end != len(fields) - 1:
                raise ValueError("Unexpected dialogue fields")
            suffix = make_suffix(entry).split()
            suffix_count = int(suffix[0])
            if operation_end(suffix, 0) != len(suffix):
                raise ValueError("Invalid instrumentation operation block")
            fields[consequence_start] = str(
                int(fields[consequence_start]) + suffix_count
            )
            result[source_index] = " ".join(
                [
                    *fields[: consequence_end],
                    *suffix[1:],
                    fields[consequence_end],
                ]
            )
        except (IndexError, ValueError) as exc:
            raise ValueError(
                f"Invalid dialogue instrumentation seam at line {source_index + 1}"
            ) from exc
    return result
