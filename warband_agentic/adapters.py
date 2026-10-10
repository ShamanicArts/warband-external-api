"""Pure adapters from proven bridge-shaped data into semantic runtime contracts.

No bridge or MCP modules are imported here.  Callers own transport, persistence,
runtime revision assignment and actual dispatch.
"""

from warband_agentic.capabilities import CapabilityDefinition, CapabilityRegistry
from warband_agentic.contracts import (
    ActionSubmission,
    ActorKind,
    ActorRef,
    AuthorityClass,
    ContextKind,
    ContextRef,
    Evidence,
    EvidenceLevel,
    Fact,
    FactSource,
    GameEvent,
    ObservationEnvelope,
    RiskClass,
    RoleId,
)

PARTY_STRATEGIC_ORDERS = ("hold", "travel", "patrol", "attack", "avoid", "escort")


def _integer(name, value, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(f"{name} must be an integer")
    return value


def context_from_snapshot(snapshot, runtime_revision):
    """Create a semantic context without treating bridge freshness as a revision."""
    if not isinstance(snapshot, dict) or not snapshot.get("connected"):
        raise ValueError("Cannot adapt disconnected or stale telemetry")
    if snapshot.get("protocol") != 2:
        raise ValueError("Semantic adapter requires protocol-2 telemetry")
    _integer("runtime_revision", runtime_revision, 0)
    try:
        kind = ContextKind(snapshot["context"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Unsupported telemetry context") from exc
    if kind is ContextKind.MISSION:
        scene = _integer("scene_id", snapshot.get("scene_id"), 0)
        scope_id = f"scene:{scene}"
        session_id = _integer("mission_session", snapshot.get("mission_session"), 0)
    elif kind is ContextKind.MENU:
        menu = _integer("menu_id", snapshot.get("menu_id"), 0)
        scope_id = f"menu:{menu}"
        session_id = _integer("menu_session", snapshot.get("menu_session"), 1)
    elif kind is ContextKind.TRADE:
        town = _integer(
            "last_town_id",
            (snapshot.get("native_context") or {}).get("last_town_id"),
            0,
        )
        scope_id = f"trade:town:{town}"
        session_id = _integer("menu_session", snapshot.get("menu_session"), 1)
    else:
        scope_id = "campaign:world"
        session_id = None
    return ContextRef(
        kind,
        scope_id,
        runtime_revision,
        session_id,
        snapshot.get("clock"),
    )


def canonical_observation_from_snapshot(
    snapshot, runtime_revision, observation_id, issued_at_ms
):
    """Map current engine telemetry to a full canonical observation envelope."""
    context = context_from_snapshot(snapshot, runtime_revision)
    troop_id = _integer("player_troop_id", snapshot.get("player_troop_id"), 0)
    actor = ActorRef(f"player:troop:{troop_id}", ActorKind.PLAYER, troop_id)
    facts = []

    def fact(key, value, source=FactSource.ENGINE_OBSERVED):
        if value is not None:
            facts.append(Fact(key, value, source, runtime_revision))

    fact("player.gold", snapshot.get("player_gold"))
    fact("player.troop_id", troop_id)
    fact("player.agent_id", snapshot.get("player_agent_id"))
    fact("player.hit_points", snapshot.get("player_hit_points"))
    fact("player.position", snapshot.get("position"))
    fact("player.captive", snapshot.get("player_is_captive"))
    fact("campaign.clock", snapshot.get("clock"))
    fact("scene.id", snapshot.get("scene_id"))
    fact("mission.flags", snapshot.get("mission_flags"))
    fact("dialogue.active", snapshot.get("dialogue_active"))
    fact("menu.id", snapshot.get("menu_id"))
    fact("menu.session", snapshot.get("menu_session"))
    fact(
        "mission.template",
        snapshot.get("mission_template"),
        FactSource.DEFINITION_METADATA,
    )
    fact("menu.name", snapshot.get("menu_name"), FactSource.DEFINITION_METADATA)
    native = snapshot.get("native_context") or {}
    fact("campaign.last_town_id", native.get("last_town_id"))
    fact("campaign.last_encounter_party_id", native.get("last_encounter_party_id"))
    return ObservationEnvelope(
        observation_id,
        actor,
        RoleId.OPERATOR_FULL,
        context,
        tuple(facts),
        (),
        issued_at_ms,
    )


def dialogue_event_from_bridge(row, scene_id, runtime_revision, event_sequence):
    """Translate a catalog-validated committed Native entry to a semantic event."""
    if not isinstance(row, dict) or row.get("event") not in (
        "npc_line",
        "player_choice",
    ):
        raise ValueError("Expected a committed Native dialogue event")
    source_sequence = _integer("source sequence", row.get("sequence"), 1)
    event_sequence = _integer("event_sequence", event_sequence, 1)
    scene_id = _integer("scene_id", scene_id, 0)
    session = _integer("mission_session", row.get("mission_session"), 0)
    context = ContextRef(
        ContextKind.DIALOGUE,
        f"scene:{scene_id}",
        runtime_revision,
        session,
    )
    subjects = []
    if row.get("conversation_agent_id", -1) >= 0:
        agent_id = _integer("conversation_agent_id", row["conversation_agent_id"], 0)
        subjects.append(ActorRef(f"agent:{agent_id}", ActorKind.AGENT, agent_id))
    if row.get("conversation_troop_id", -1) >= 0:
        troop_id = _integer("conversation_troop_id", row["conversation_troop_id"], 0)
        subjects.append(ActorRef(f"troop:{troop_id}", ActorKind.TROOP, troop_id))
    entry_id = _integer("entry_id", row.get("entry_id"), 0)
    occurred_at_ms = round(float(row["received_at"]) * 1000)
    return GameEvent(
        event_sequence,
        "dialogue.npc-line" if row["event"] == "npc_line" else "dialogue.player-choice",
        context,
        tuple(subjects),
        {
            "entry_id": entry_id,
            "source_sequence": source_sequence,
            "symbol": row["symbol"],
            "text_template": row["text_template"],
            "input_state_id": row["input_state_id"],
            "input_state": row.get("input_state"),
            "output_state_id": row["output_state_id"],
            "output_state": row.get("output_state"),
            "speaker": row["speaker"],
        },
        Evidence(
            EvidenceLevel.ENGINE_OBSERVED,
            row.get("source", "Warband conversation consequence"),
            f"Catalog-validated committed dialogue entry {entry_id}",
            event_sequence,
        ),
        occurred_at_ms,
    )


def register_menu_capability(registry):
    """Register the proven Native menu-selection adapter once per registry."""
    if not isinstance(registry, CapabilityRegistry):
        raise TypeError("registry must be a CapabilityRegistry")
    registry.register(
        CapabilityDefinition(
            "menu.try-select",
            "Attempt one reviewed Native menu candidate; its condition is rechecked",
            "player.menu",
            AuthorityClass.ACTOR_CONTROL,
            (ContextKind.MENU,),
            {
                "type": "object",
                "properties": {"action_id": {"type": "integer", "minimum": 0}},
                "required": ["action_id"],
                "additionalProperties": False,
            },
            RiskClass.CONSEQUENTIAL,
            False,
            "Native may reject the candidate or run irreversible consequences.",
            EvidenceLevel.ENGINE_ACKNOWLEDGED,
            "native-menu-select",
            True,
        )
    )


def register_party_order_capabilities(registry):
    """Register reversible movement and consequential attack capabilities."""
    if not isinstance(registry, CapabilityRegistry):
        raise TypeError("registry must be a CapabilityRegistry")
    common = {
        "type": "object",
        "properties": {
            "order": {"type": "string", "enum": PARTY_STRATEGIC_ORDERS},
            "target_id": {"type": "integer", "minimum": 0},
        },
        "required": ("order", "target_id"),
        "additionalProperties": False,
    }
    registry.register(
        CapabilityDefinition(
            "party.issue-order",
            "Issue one bounded strategic order to a controlled faction party",
            "party.strategy",
            AuthorityClass.PARTY_COMMAND,
            (ContextKind.CAMPAIGN,),
            common,
            RiskClass.REVERSIBLE,
            True,
            "The party will abandon its current strategic order.",
            EvidenceLevel.ENGINE_OBSERVED,
            "native-party-order",
            True,
        )
    )
    registry.register(
        CapabilityDefinition(
            "party.issue-attack-order",
            "Order one controlled faction party to attack an exact target",
            "party.strategy",
            AuthorityClass.PARTY_COMMAND,
            (ContextKind.CAMPAIGN,),
            common,
            RiskClass.CONSEQUENTIAL,
            False,
            "The order can lead to battle, casualties, capture or destruction.",
            EvidenceLevel.ENGINE_OBSERVED,
            "native-party-attack-order",
            True,
        )
    )


def _npc_speech_parameters(proposal_tokens=None):
    properties = {
        "text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": (
                "Printable dialogue text without pipes, braces, newlines or "
                "control characters."
            ),
        }
    }
    if proposal_tokens is not None:
        tokens = tuple(proposal_tokens)
        properties["proposal_token"] = {
            "type": "string",
            **({"enum": tokens} if tokens else {"minLength": 1, "maxLength": 512}),
            "description": (
                "Optional current mechanical proposal. It cannot execute until "
                "the line is observed and every required participant accepts."
            ),
        }
    return {
        "type": "object",
        "properties": properties,
        "required": ("text",),
        "additionalProperties": False,
    }


def register_npc_speech_capability(registry):
    """Register bounded generated speech for one controlled scene NPC."""
    if not isinstance(registry, CapabilityRegistry):
        raise TypeError("registry must be a CapabilityRegistry")
    registry.register(
        CapabilityDefinition(
            "dialogue.speak",
            "Speak one bounded utterance through the controlled NPC",
            "npc.dialogue",
            AuthorityClass.ACTOR_CONTROL,
            (ContextKind.MISSION,),
            _npc_speech_parameters(()),
            RiskClass.CONSEQUENTIAL,
            False,
            "The line is shown to the player and cannot be retracted.",
            EvidenceLevel.ENGINE_OBSERVED,
            "native-npc-speech",
            True,
        )
    )


def issue_npc_speech_affordance(
    registry,
    actor,
    npc,
    context,
    grant,
    issued_at_ms,
    expires_at_ms,
    proposal_tokens=(),
):
    """Issue one mission/session-bound free-text speech affordance."""
    if npc.kind is not ActorKind.AGENT or npc.game_id is None:
        raise ValueError("NPC speech requires a game-backed scene agent")
    return registry.issue(
        "dialogue.speak",
        actor,
        (npc,),
        context,
        grant,
        issued_at_ms,
        expires_at_ms,
        _npc_speech_parameters(proposal_tokens if proposal_tokens else None),
    )


def npc_speech_operation_from_validated(validated):
    """Resolve validated NPC speech without exposing the bridge operation."""
    if validated.capability.name != "dialogue.speak":
        raise ValueError("Validated action is not NPC speech")
    if len(validated.affordance.targets) != 1:
        raise ValueError("NPC speech affordance has invalid target bindings")
    npc = validated.affordance.targets[0]
    if npc.kind is not ActorKind.AGENT or npc.game_id is None:
        raise ValueError("NPC speech affordance has no scene agent")
    text = validated.submission.arguments["text"]
    if (
        not isinstance(text, str)
        or not 1 <= len(text) <= 200
        or any(character in text for character in "|\r\n\x00{}")
        or not text.isprintable()
    ):
        raise ValueError(
            "Speech needs 1-200 printable characters without delimiters or braces"
        )
    return {
        "operation": "npc_say",
        "arguments": {"agent_id": npc.game_id, "text": text},
    }


def issue_party_order_affordance(
    registry,
    actor,
    party,
    target,
    order,
    title,
    context,
    grant,
    issued_at_ms,
    expires_at_ms,
):
    """Issue one exact party/order/target choice from an application policy."""
    if order not in PARTY_STRATEGIC_ORDERS:
        raise ValueError("Unknown strategic party order")
    if party.kind is not ActorKind.PARTY or party.game_id is None:
        raise ValueError("Party order requires a game-backed party target")
    if target.game_id is None:
        raise ValueError("Party order target must have a game ID")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Party order title must be non-empty")
    return registry.issue(
        "party.issue-attack-order" if order == "attack" else "party.issue-order",
        actor,
        (party, target),
        context,
        grant,
        issued_at_ms,
        expires_at_ms,
        {
            "type": "object",
            "properties": {
                "order": {"type": "string", "const": order, "title": title},
                "target_id": {"type": "integer", "const": target.game_id},
            },
            "required": ("order", "target_id"),
            "additionalProperties": False,
        },
    )


def party_operation_from_validated(validated):
    """Resolve a validated semantic party affordance to the reviewed operation."""
    if validated.capability.name not in (
        "party.issue-order",
        "party.issue-attack-order",
    ):
        raise ValueError("Validated action is not a party order")
    if len(validated.affordance.targets) != 2:
        raise ValueError("Party order affordance has invalid target bindings")
    party, target = validated.affordance.targets
    if party.kind is not ActorKind.PARTY or party.game_id is None:
        raise ValueError("Party order affordance has no controlled party")
    if target.game_id is None:
        raise ValueError("Party order affordance has no game-backed target")
    arguments = validated.submission.arguments
    if (
        arguments["target_id"] != target.game_id
        or arguments["order"] not in PARTY_STRATEGIC_ORDERS
    ):
        raise ValueError("Party order arguments escaped their target binding")
    return {
        "operation": "party_order",
        "arguments": {
            "party_id": party.game_id,
            "order": arguments["order"],
            "target_party_id": target.game_id,
            "world_control": True,
        },
    }


def party_facts_from_world_result(result, revision):
    """Convert one complete engine party getter result into canonical facts."""
    _integer("revision", revision, 0)
    if not isinstance(result, dict) or not result.get("complete"):
        raise ValueError("Expected a complete campaign world result")
    values = result.get("facts")
    if not isinstance(values, dict) or values.get("entity") != "party":
        raise ValueError("Expected engine-observed party facts")
    party_id = _integer("party_id", values.get("party_id"), 0)
    facts = []
    for name in (
        "ai_behavior",
        "ai_object",
        "ai_initiative",
        "faction_id",
        "position",
    ):
        if name in values:
            facts.append(
                Fact(
                    f"parties.{party_id}.{name}",
                    values[name],
                    FactSource.ENGINE_OBSERVED,
                    revision,
                )
            )
    return tuple(facts)


def issue_menu_affordances(
    registry,
    menu_options,
    actor,
    player,
    context,
    grant,
    issued_at_ms,
    expires_at_ms,
):
    """Issue one exact-session attempt token per reviewed current-menu candidate."""
    if context.kind is not ContextKind.MENU:
        raise ValueError("Menu affordances require a menu context")
    state_context = context_from_snapshot(
        menu_options.get("state", {}), context.revision
    )
    if state_context != context:
        raise ValueError("Menu candidate state does not match semantic context")
    actions = menu_options.get("actions")
    if not isinstance(actions, list):
        raise ValueError("Menu candidates must be a list")
    normalized = []
    action_ids = set()
    for action in actions:
        if not isinstance(action, dict) or any(
            key.endswith("_script") for key in action
        ):
            raise ValueError("Menu candidates must contain safe catalog metadata")
        action_id = _integer("action_id", action.get("id"), 0)
        if action_id in action_ids:
            raise ValueError("Menu candidates contain a duplicate action ID")
        action_ids.add(action_id)
        if action.get("menu_id") != menu_options["state"].get("menu_id"):
            raise ValueError("Menu candidate belongs to a different menu")
        normalized.append((action_id, action))

    affordances = []
    for action_id, action in normalized:
        affordances.append(
            registry.issue(
                "menu.try-select",
                actor,
                (player,),
                context,
                grant,
                issued_at_ms,
                expires_at_ms,
                {
                    "type": "object",
                    "properties": {
                        "action_id": {
                            "type": "integer",
                            "const": action_id,
                            "title": action.get("text_template")
                            or action.get("option")
                            or f"Menu action {action_id}",
                        }
                    },
                    "required": ["action_id"],
                    "additionalProperties": False,
                },
            )
        )
    return tuple(affordances)


def menu_operation_from_validated(action):
    """Resolve a validated semantic menu action to the existing bridge operation."""
    if action.capability.handler_id != "native-menu-select":
        raise ValueError("Validated action is not a Native menu selection")
    if not isinstance(action.submission, ActionSubmission):
        raise TypeError("validated action has no ActionSubmission")
    return {
        "operation": "select_menu",
        "arguments": {"action_id": action.submission.arguments["action_id"]},
    }
