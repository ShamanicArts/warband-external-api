import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.test_game_bridge import mission_telemetry
from warband_agentic import (
    CompiledContext,
    CompiledInstruction,
    CompiledIntegerArgument,
    CompiledOperation,
    HandlerOperand,
)


def grant_gold_operation():
    return CompiledOperation(
        name="example.grant-gold",
        opcode=1001,
        context=CompiledContext.CAMPAIGN,
        arguments=(CompiledIntegerArgument("amount", minimum=1, maximum=100),),
        handler=(
            CompiledInstruction(
                "troop_add_gold",
                (HandlerOperand.PLAYER_TROOP, HandlerOperand.ARG0),
            ),
        ),
    )


class CompiledExtensionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(
            Path(self.temp.name) / "bridge.sqlite3",
            compiled_operations=(grant_gold_operation(),),
        )
        self.query = {
            **mission_telemetry(),
            "context": "campaign",
            "scene": "-1",
            "session": "-1",
            "build": "16",
            "captive": "0",
        }
        self.store.poll(self.query)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_validates_and_encodes_declared_operation(self):
        for arguments in ({"amount": 0}, {"amount": 101}, {"amount": 1, "x": 2}):
            with self.assertRaises(ValueError):
                self.store.enqueue_operation("example.grant-gold", arguments)
        self.store.poll({**self.query, "build": "15"})
        with self.assertRaisesRegex(ValueError, "integration revision 16"):
            self.store.enqueue_operation("example.grant-gold", {"amount": 75})
        self.store.poll(self.query)

        command = self.store.enqueue_operation("example.grant-gold", {"amount": 75})

        self.assertEqual(command["scene"], -1)
        self.assertEqual(command["session"], -1)
        parts = self.store.poll(self.query).split("|")
        self.assertEqual(parts[3:9], ["1001", "75", "0", "0", "-1", "-1"])


if __name__ == "__main__":
    unittest.main()
