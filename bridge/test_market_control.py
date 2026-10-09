import tempfile
import unittest
from pathlib import Path

from bridge.game_bridge import Store
from bridge.protocol import validate_operation, wire_arguments
from bridge.test_game_bridge import mission_telemetry
from module_system import test_build_mcp_module as build_tests
from module_system.build_mcp_module import callback


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bridge.sqlite"
        self.catalog = {"menus": {"5": "town_trade"}, "items": {"100": "Bread"}}
        self.store = Store(self.path, self.catalog)
        self.query = {
            **mission_telemetry(),
            "context": "menu",
            "scene": "-1",
            "session": "-1",
            "menu": "5",
            "menu-session": "2",
            "build": "9",
        }
        self.store.poll(self.query)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def command(self):
        cmd = self.store.enqueue_operation(
            "scan_merchant", {"merchant": "goods", "offset": 10, "limit": 2}
        )
        self.store.poll(self.query)
        return cmd

    def test_market_command_has_exact_menu_entry_scope(self):
        cmd = self.command()
        self.assertEqual((cmd["scene"], cmd["session"]), (5, 2))
        self.assertEqual(
            wire_arguments("scan_merchant", cmd["arguments"]), [2, 10, 2, 0]
        )
        queued = self.store.enqueue_operation("scan_merchant", cmd["arguments"])
        self.store.poll({**self.query, "menu-session": "3"})
        self.assertEqual(self.store.command(queued["id"])["status"], "rejected")

    def test_end_before_rows_and_restart_preserve_actual_inventory(self):
        cmd = self.command()
        common = {"v": "2", "job": str(cmd["id"]), "merchant": "300", "town": "26"}
        self.store.event(
            "/merchant-end", {**common, "total": "12", "count": "2", "gold": "200"}
        )
        self.assertFalse(self.store.market.result(cmd)["complete"])
        for slot in (11, 10):
            self.store.event(
                "/merchant-row",
                {
                    **common,
                    "slot": str(slot),
                    "item": "100",
                    "modifier": "0",
                    "amount": "50",
                    "max-amount": "50",
                    "base-value": "50",
                    "buy-factor": "110",
                    "sell-factor": "90",
                },
            )
        result = self.store.market.result(cmd)
        self.assertTrue(result["complete"])
        self.assertEqual(result["rows"][0]["name"], "Bread")
        self.assertEqual(result["merchant_gold"], 200)
        self.assertFalse(result["transaction_support"])
        self.store.db.close()
        self.store = Store(self.path, self.catalog)
        self.assertEqual(
            self.store.market.result(self.store.command(cmd["id"]))["rows"],
            result["rows"],
        )

    def test_old_build_wrong_menu_and_malformed_pages_rejected(self):
        args = {"merchant": "goods", "offset": 10, "limit": 2}
        for change in (
            {"integration_revision": 8},
            {"menu_name": "village"},
            {"menu_session": None},
        ):
            with self.assertRaises(ValueError):
                validate_operation(
                    "scan_merchant", args, {**self.store.snapshot(), **change}
                )
        for change in (
            {"merchant": "all"},
            {"offset": True},
            {"offset": -1},
            {"limit": 17},
        ):
            with self.assertRaises(ValueError):
                validate_operation(
                    "scan_merchant", {**args, **change}, self.store.snapshot()
                )

    def test_market_callback_balanced_with_original_price_scripts(self):
        compiled = callback(
            native_globals={"current_town": 2 << 56},
            native_scripts={
                "game_get_item_buy_price_factor": 10,
                "game_get_item_sell_price_factor": 11,
            },
            troop_count=1000,
            market_menu_id=5,
        )
        build_tests.ModuleBuildTests.assert_balanced(self, compiled)

    def test_trade_ui_is_not_market_menu_and_rejects_underlying_actions(self):
        self.store.poll({**self.query, "context": "trade"})
        self.assertIsNone(self.store.snapshot()["menu_id"])
        with self.assertRaises(ValueError):
            self.store.enqueue_operation(
                "scan_merchant", {"merchant": "goods", "offset": 10, "limit": 16}
            )
        with self.assertRaises(ValueError):
            self.store.enqueue_operation("select_menu", {"action_id": 0})
