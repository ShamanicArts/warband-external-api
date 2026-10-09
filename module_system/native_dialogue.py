"""Original Native conversation entry; not injected speech or dialogue choices.

Revision15 entry live-accepted at Azgad elder; choices remain unimplemented.
The screen predicate is documented ONLY for mission template triggers, so the
sampler must never run inside game_receive_url_response.
"""

from module_system.scene_ops import LOCAL, TROOP, living_player


def dialogue_sampler(dialogue_slot):
    """Mission-trigger-only engine screen state; no register mutation."""
    return [
        ("try_begin",),
        ("conversation_screen_is_active",),
        ("troop_set_slot", TROOP, dialogue_slot, 1),
        ("else_try",),
        ("troop_set_slot", TROOP, dialogue_slot, 0),
        ("try_end",),
    ]


def native_entry(dialogue_slot, ready_slot, flags_slot, troop_count):
    """Caller must guard exact Native town/village mission and scene/session.

    Scripted start uses troop, not agent. Refuse ambiguous troop instances instead
    of claiming that a requested agent is necessarily selected by the engine.
    Engine entry acknowledgement is NOT proof of conversation or choice success.
    """
    target, speaker, count, candidate = [LOCAL + i for i in (30, 26, 27, 28)]
    return [
        *living_player(dialogue_slot),
        ("troop_get_slot", LOCAL + 29, TROOP, flags_slot),
        ("val_and", LOCAL + 29, 2),
        ("eq", LOCAL + 29, 0),
        ("troop_get_slot", LOCAL + 29, TROOP, ready_slot),
        ("eq", LOCAL + 29, 0),
        ("assign", target, LOCAL + 5),
        ("ge", target, 0),
        ("lt", target, 10000),
        ("neq", target, LOCAL + 25),
        ("agent_is_active", target),
        ("agent_is_alive", target),
        ("agent_is_human", target),
        ("agent_get_troop_id", speaker, target),
        ("ge", speaker, 0),
        ("lt", speaker, troop_count),
        ("assign", count, 0),
        ("try_for_agents", candidate),
        ("agent_is_active", candidate),
        ("agent_get_troop_id", LOCAL + 29, candidate),
        ("eq", LOCAL + 29, speaker),
        ("val_add", count, 1),
        ("try_end",),
        ("eq", count, 1),
        ("agent_get_position", 45, LOCAL + 25),
        ("agent_get_position", 46, target),
        ("get_distance_between_positions", LOCAL + 29, 45, 46),
        ("le", LOCAL + 29, 400),  # actual engine centimeters, no teleport
        ("troop_set_slot", TROOP, dialogue_slot, 1),
        ("assign", LOCAL + 10, 0),
        ("start_mission_conversation", speaker),
    ]
