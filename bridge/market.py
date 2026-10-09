"""Durable bounded merchant pages, asynchronous engine messages, honest pricing."""

import json


class MerchantExports:
    def trade_event(self, query, command):
        if command["kind"] != "goods_trade":
            raise ValueError("Trade facts must correspond to a goods trade command")
        keys = (
            "mode",
            "item",
            "source-slot",
            "destination-slot",
            "price",
            "merchant",
            "town",
            "player-gold",
            "merchant-gold",
            "source-item",
            "destination-item",
            "source-amount",
            "destination-amount",
            "factor",
            "can-execute",
        )
        facts = {key.replace("-", "_"): int(query[key]) for key in keys}
        args = command["arguments"]
        mode = int(args["side"] == "sell") + 2 * int(args["execute"])
        if (
            facts["mode"] != mode
            or facts["item"] != args["item_id"]
            or facts["source_slot"] != args["slot"]
            or not 1 <= facts["price"] <= 1000000
            or any(abs(value) > 2**53 for value in facts.values())
        ):
            raise ValueError("Trade facts do not match requested item/slot/mode")
        if args["execute"] and facts["price"] != args["expected_price"]:
            raise ValueError("Executed price differs from explicit price agreement")
        stored = self.db.execute(
            "SELECT payload FROM goods_trade_results WHERE job=?", (command["id"],)
        ).fetchone()
        if stored and json.loads(stored[0]) != facts:
            raise ValueError("Conflicting duplicate trade result")
        self.db.execute(
            "INSERT OR REPLACE INTO goods_trade_results VALUES (?,?)",
            (command["id"], json.dumps(facts)),
        )
        self.db.commit()

    def trade_result(self, command):
        if command["kind"] != "goods_trade":
            raise ValueError("Not a goods trade command")
        stored = self.db.execute(
            "SELECT payload FROM goods_trade_results WHERE job=?", (command["id"],)
        ).fetchone()
        return {
            "command": command,
            "complete": stored is not None,
            "facts": json.loads(stored[0]) if stored else None,
            "source": "Full-unmodified goods adapter and Native economic events",
            "caveat": (
                "Quote is not reservation; execution recomputes price. "
                "Inspect facts before retrying."
            ),
        }

    def __init__(self, database, catalog):
        self.db, self.catalog = database, catalog
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS merchant_exports "
            "(job INTEGER PRIMARY KEY, payload TEXT)"
        )
        self.db.commit()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS goods_trade_results "
            "(job INTEGER PRIMARY KEY, payload TEXT)"
        )
        self.db.commit()

    def event(self, path, query, command):
        if command["kind"] != "scan_merchant":
            raise ValueError("Merchant event must match a merchant command")
        job, args = command["id"], command["arguments"]
        stored = self.db.execute(
            "SELECT payload FROM merchant_exports WHERE job=?", (job,)
        ).fetchone()
        page = (
            json.loads(stored[0])
            if stored
            else {
                "rows": {},
                "total": None,
                "expected_count": None,
                "merchant_troop_id": None,
                "town_party_id": None,
            }
        )
        merchant, town = int(query["merchant"]), int(query["town"])
        if not 0 < merchant < 100000 or not 0 <= town < 1000000:
            raise ValueError("Invalid merchant/town entity IDs")
        if page["merchant_troop_id"] not in (None, merchant) or page[
            "town_party_id"
        ] not in (None, town):
            raise ValueError("Merchant page entity changed")
        page.update(merchant_troop_id=merchant, town_party_id=town)
        if path == "/merchant-row":
            row = {
                key: int(query[key.replace("_", "-")])
                for key in (
                    "slot",
                    "item",
                    "modifier",
                    "amount",
                    "max_amount",
                    "base_value",
                    "buy_factor",
                    "sell_factor",
                )
            }
            slot = row["slot"]
            if not args["offset"] <= slot < args["offset"] + args["limit"]:
                raise ValueError("Merchant slot outside requested page")
            if any(abs(value) > 2**53 for value in row.values()):
                raise ValueError("Merchant value out of bounds")
            row["name"] = self.catalog.get("items", {}).get(str(row["item"]))
            row["equipped"] = slot < 10
            page["rows"][str(slot)] = row
        elif path == "/merchant-end":
            count, total = int(query["count"]), int(query["total"])
            if not 0 <= total <= 10000 or count != min(
                args["limit"], max(0, total - args["offset"])
            ):
                raise ValueError("Invalid merchant completion count")
            page.update(
                total=total, expected_count=count, merchant_gold=int(query["gold"])
            )
        else:
            raise ValueError("Unknown merchant event")
        self.db.execute(
            "INSERT OR REPLACE INTO merchant_exports VALUES (?,?)",
            (job, json.dumps(page)),
        )
        self.db.commit()

    def result(self, command):
        if command["kind"] != "scan_merchant":
            raise ValueError("Not a merchant command")
        stored = self.db.execute(
            "SELECT payload FROM merchant_exports WHERE job=?", (command["id"],)
        ).fetchone()
        if stored is None:
            return {"command": command, "complete": False}
        page = json.loads(stored[0])
        rows = sorted(page.pop("rows").values(), key=lambda row: row["slot"])
        args = command["arguments"]
        complete = page["expected_count"] == len(rows) and [
            row["slot"] for row in rows
        ] == list(range(args["offset"], args["offset"] + len(rows)))
        return {
            **page,
            "rows": rows,
            "command": command,
            "complete": complete,
            "merchant": args["merchant"],
            "offset": args["offset"],
            "next_offset": args["offset"] + args["limit"]
            if complete and args["offset"] + args["limit"] < page["total"]
            else None,
            "source": "Native inventory and original game price-factor scripts",
            "pricing_caveat": (
                "Factors/base values are NOT final transaction quotes; "
                "modifiers, partial stacks and engine rounding still apply"
            ),
            "transaction_support": False,
        }
