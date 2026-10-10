"""Reviewed built-in application declarations for the extension SDK."""

from bridge.native_faction_agent_app import (
    NativeFactionAgentApplication,
    PartyOrderOption,
)
from bridge.native_menu_agent_app import NativeMenuAgentApplication
from bridge.native_npc_speech_app import NativeNpcSpeechApplication
from warband_agentic import (
    AgenticExtension,
    ApplicationKind,
    ExtensionRegistry,
    OwnershipRule,
    RoleId,
)


def _object_schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": tuple(required),
        "additionalProperties": False,
    }


def _validate_faction_settings(settings):
    parties = tuple(settings["controlled_party_ids"])
    if not parties:
        raise ValueError("controlled_party_ids must be a non-empty list")
    if len(parties) != len(set(parties)):
        raise ValueError("controlled_party_ids must be unique")
    options = tuple(
        PartyOrderOption(**dict(item)) for item in settings["order_options"]
    )
    if not options:
        raise ValueError("order_options must be a non-empty list")
    if any(option.party_id not in parties for option in options):
        raise ValueError("party order option uses an uncontrolled party")
    keys = {
        (option.party_id, option.order, option.target_party_id) for option in options
    }
    if len(keys) != len(options):
        raise ValueError("order_options contain duplicate choices")


def _faction_factory(backend, session_id, *, event_log, **settings):
    return NativeFactionAgentApplication(
        backend,
        session_id,
        event_log=event_log,
        faction_id=settings["faction_id"],
        controlled_party_ids=settings["controlled_party_ids"],
        order_options=tuple(
            PartyOrderOption(**option) for option in settings["order_options"]
        ),
    )


def _dialogue_factory(backend, session_id, *, event_log, **settings):
    return NativeNpcSpeechApplication(
        backend,
        session_id,
        event_log=event_log,
        conversation_mode=True,
        **settings,
    )


def built_in_extension_registry():
    """Return a fresh registry containing only the reviewed Native applications."""
    entity_id = {"type": "integer", "minimum": 0, "maximum": 999_999}
    extension = AgenticExtension(
        "warband.native",
        "0.2.0",
        "Reviewed applications over the Warband Native-safe bridge backend",
        2,
        16,
        16,
        (
            ApplicationKind(
                "native-menu",
                "Current-session Native menu choices for the strategic player",
                _object_schema({}, ()),
                (RoleId.PLAYER_STRATEGIC,),
                ("menu.try-select",),
                ("select_menu",),
                (OwnershipRule("player", constant="player"),),
                False,
            ),
            ApplicationKind(
                "native-faction",
                "Reviewed strategic orders for one faction's controlled parties",
                _object_schema(
                    {
                        "faction_id": entity_id,
                        "controlled_party_ids": {
                            "type": "array",
                            "items": entity_id,
                            "minItems": 1,
                            "maxItems": 32,
                            "uniqueItems": True,
                        },
                        "order_options": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 64,
                            "items": _object_schema(
                                {
                                    "party_id": entity_id,
                                    "order": {
                                        "type": "string",
                                        "enum": ("travel", "patrol", "attack"),
                                    },
                                    "target_party_id": entity_id,
                                    "title": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 200,
                                    },
                                },
                                ("party_id", "order", "target_party_id", "title"),
                            ),
                        },
                    },
                    ("faction_id", "controlled_party_ids", "order_options"),
                ),
                (RoleId.FACTION_SOVEREIGN,),
                ("party.issue-order", "party.issue-attack-order"),
                ("world_query", "party_order"),
                (OwnershipRule("party", setting="controlled_party_ids", many=True),),
                True,
            ),
            ApplicationKind(
                "native-npc-speech",
                "One-turn bounded speech for one live scene NPC",
                _object_schema(
                    {"agent_id": {"type": "integer", "minimum": 0, "maximum": 9_999}},
                    ("agent_id",),
                ),
                (RoleId.NPC_SELF,),
                ("dialogue.speak",),
                ("scan_agents", "npc_say"),
                (OwnershipRule("agent", setting="agent_id"),),
                True,
            ),
            ApplicationKind(
                "native-npc-dialogue",
                "Persistent bounded player-to-NPC conversation over one-turn speech",
                _object_schema(
                    {"agent_id": {"type": "integer", "minimum": 0, "maximum": 9_999}},
                    ("agent_id",),
                ),
                (RoleId.NPC_SELF,),
                ("dialogue.speak",),
                ("scan_agents", "npc_say"),
                (OwnershipRule("agent", setting="agent_id"),),
                True,
            ),
        ),
        module_required=True,
    )
    registry = ExtensionRegistry(protocol=2, integration_revision=16)
    registry.register(
        extension,
        {
            "native-menu": NativeMenuAgentApplication,
            "native-faction": _faction_factory,
            "native-npc-speech": NativeNpcSpeechApplication,
            "native-npc-dialogue": _dialogue_factory,
        },
        {"native-faction": _validate_faction_settings},
    )
    return registry
