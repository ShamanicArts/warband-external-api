import unittest

from bridge.application_extensions import built_in_extension_registry
from warband_agentic import (
    CONTRACT_VERSION,
    AgenticExtension,
    ApplicationKind,
    CompiledContext,
    CompiledInstruction,
    CompiledIntegerArgument,
    CompiledOperation,
    ExtensionBundle,
    ExtensionRegistry,
    HandlerOperand,
    OwnershipRule,
    ResourceClaim,
    RoleId,
    ScopedGameBackend,
)


class FakeStore:
    def __init__(self):
        self.module_catalog = {"troops": {"7": "Trainer"}}
        self.commands = {
            40: {"id": 40, "kind": "scan_agents", "arguments": {}},
            41: {"id": 41, "kind": "party_order", "arguments": {}},
        }

    def snapshot(self):
        return {"connected": True, "protocol": 2, "context": "mission"}

    def menu_options(self):
        return {"actions": []}

    def enqueue_operation(self, kind, arguments):
        command = {"id": 42, "kind": kind, "arguments": dict(arguments)}
        self.commands[42] = command
        return command

    def command(self, command_id):
        return self.commands[command_id]

    def scan_result(self, command_id):
        return {"command": self.command(command_id), "complete": False}

    def dialogue_result(self, command_id):
        return {"command": self.command(command_id), "complete": False}

    def world_result(self, command_id):
        return {"command": self.command(command_id), "complete": False}


def example_extension(
    *,
    revision_min=16,
    resource="npc-dialogue-hook",
    module_required=False,
    backend_operations=("scan_agents", "npc_say"),
):
    return AgenticExtension(
        "example.dialogue",
        "1.2.3",
        "Example constrained dialogue application",
        2,
        revision_min,
        16,
        (
            ApplicationKind(
                "example-npc",
                "Example NPC application",
                {
                    "type": "object",
                    "properties": {"agent_id": {"type": "integer", "minimum": 0}},
                    "required": ("agent_id",),
                    "additionalProperties": False,
                },
                (RoleId.NPC_SELF,),
                ("dialogue.speak",),
                backend_operations,
                (OwnershipRule("agent", setting="agent_id"),),
                True,
            ),
        ),
        (ResourceClaim("patch-seam", resource),),
        module_required=module_required,
    )


def grant_gold_operation(name="example.dialogue.grant-gold", opcode=1001):
    return CompiledOperation(
        name,
        opcode,
        CompiledContext.CAMPAIGN,
        (CompiledIntegerArgument("amount", 1, 100),),
        (
            CompiledInstruction(
                "troop_add_gold",
                (HandlerOperand.PLAYER_TROOP, HandlerOperand.ARG0),
            ),
        ),
    )


class ExtensionSdkTests(unittest.TestCase):
    def test_bundle_registers_compiled_operations_for_host_composition(self):
        def factory(*args, **kwargs):
            return None

        extension = example_extension(
            backend_operations=(
                "scan_agents",
                "npc_say",
                "example.dialogue.grant-gold",
            )
        )
        extension = AgenticExtension(
            extension.extension_id,
            extension.version,
            extension.description,
            extension.protocol,
            extension.integration_revision_min,
            extension.integration_revision_max,
            extension.applications,
            extension.resources,
            module_required=True,
        )
        bundle = ExtensionBundle(
            extension,
            {"example-npc": factory},
            compiled_operations=(grant_gold_operation(),),
        )
        registry = ExtensionRegistry(protocol=2, integration_revision=16)

        bundle.register(registry)

        self.assertEqual(registry.compiled_operations(), (grant_gold_operation(),))
        with self.assertRaisesRegex(ValueError, "opcode 1001 collides"):
            ExtensionBundle(
                AgenticExtension(
                    "example.other",
                    "1.0.0",
                    "Other compiled extension",
                    2,
                    16,
                    16,
                    (
                        ApplicationKind(
                            "other-app",
                            "Other application",
                            {
                                "type": "object",
                                "properties": {},
                                "required": (),
                                "additionalProperties": False,
                            },
                            (RoleId.OBSERVER_READONLY,),
                            (),
                            (),
                            (),
                            False,
                        ),
                    ),
                    (ResourceClaim("patch-seam", "other"),),
                    module_required=True,
                ),
                {"other-app": factory},
                compiled_operations=(grant_gold_operation("example.other.grant-gold"),),
            ).register(registry)

    def test_builtin_faction_settings_are_bounded_before_runtime(self):
        registry = built_in_extension_registry()
        settings = {
            "faction_id": 15,
            "controlled_party_ids": list(range(33)),
            "order_options": [
                {
                    "party_id": 0,
                    "order": "travel",
                    "target_party_id": 26,
                    "title": "Defend Praven",
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "too many items"):
            registry.validate_settings("native-faction", settings)

    def test_registry_validates_settings_compatibility_and_collisions(self):
        def factory(*args, **kwargs):
            return None

        registry = ExtensionRegistry(protocol=2, integration_revision=16)
        registry.register(example_extension(), {"example-npc": factory})

        settings = registry.validate_settings("example-npc", {"agent_id": 7})
        self.assertEqual(dict(settings), {"agent_id": 7})
        self.assertEqual(
            registry.control_claims("example-npc", settings),
            (("agent", "7"),),
        )
        catalog = registry.catalog()
        self.assertEqual(catalog["schema"], "warband.agentic/extensions/v1")
        self.assertEqual(catalog["contract_schema"], CONTRACT_VERSION)
        self.assertEqual(catalog["extensions"][0]["extension_id"], "example.dialogue")
        self.assertNotIn("factory", str(catalog).lower())

        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            registry.validate_settings(
                "example-npc", {"agent_id": 7, "bridge_operation": "party_order"}
            )
        with self.assertRaisesRegex(ValueError, "integration revision"):
            ExtensionRegistry(protocol=2, integration_revision=16).register(
                example_extension(revision_min=17), {"example-npc": factory}
            )
        with self.assertRaisesRegex(ValueError, "resource claim collision"):
            registry.register(
                AgenticExtension(
                    "example.other",
                    "1.0.0",
                    "Conflicting extension",
                    2,
                    16,
                    16,
                    (
                        ApplicationKind(
                            "other-app",
                            "Another app",
                            {
                                "type": "object",
                                "properties": {},
                                "required": (),
                                "additionalProperties": False,
                            },
                            (RoleId.OBSERVER_READONLY,),
                            (),
                            (),
                            (),
                            False,
                        ),
                    ),
                    (ResourceClaim("patch-seam", "npc-dialogue-hook"),),
                ),
                {"other-app": factory},
            )

    def test_scoped_backend_allows_only_declared_operation_families(self):
        backend = ScopedGameBackend(FakeStore(), ("scan_agents", "npc_say"))

        self.assertEqual(backend.snapshot()["protocol"], 2)
        self.assertEqual(backend.module_catalog["troops"]["7"], "Trainer")
        command = backend.enqueue_operation("scan_agents", {})
        self.assertEqual(command["id"], 42)
        self.assertEqual(backend.command(40)["kind"], "scan_agents")
        self.assertFalse(backend.scan_result(40)["complete"])

        with self.assertRaisesRegex(PermissionError, "not declared"):
            backend.enqueue_operation("party_order", {"party_id": 500})
        with self.assertRaisesRegex(PermissionError, "not declared"):
            backend.command(41)
        with self.assertRaisesRegex(PermissionError, "not declared"):
            backend.world_result(41)


if __name__ == "__main__":
    unittest.main()
