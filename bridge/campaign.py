"""Durable, bounded, out-of-order campaign snapshots, never inferred game state."""

import json
import time

from bridge.protocol import DATASETS


class CampaignExports:
    def __init__(self, database, catalog):
        self.db = database
        self.catalog = catalog
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS campaign_exports "
            "(job INTEGER PRIMARY KEY, created REAL, payload TEXT)"
        )
        self.db.commit()

    def event(self, path, query, command):
        args = command["arguments"]
        if (
            command["kind"] != "scan_campaign"
            or int(query["dataset"]) != DATASETS[args["dataset"]]
        ):
            raise ValueError("Campaign event does not match the requested dataset")
        stored = self.db.execute(
            "SELECT * FROM campaign_exports WHERE job=?", (command["id"],)
        ).fetchone()
        page = (
            json.loads(stored["payload"])
            if stored
            else {
                "dataset": args["dataset"],
                "offset": args["offset"],
                "limit": args["limit"],
                "rows": {},
                "expected_count": None,
                "total": None,
            }
        )
        if path == "/campaign-row":
            values = {
                field: int(query[field])
                for field in ("id", "a", "b", "c", "d", "e", "f")
            }
            if any(abs(value) > 2**53 for value in values.values()) or values["id"] < 0:
                raise ValueError("Campaign row value out of bounds")
            key = str(values["id"])
            if key not in page["rows"] and len(page["rows"]) >= args["limit"]:
                raise ValueError("Campaign page exceeds requested limit")
            page["rows"][key] = self.decode(args["dataset"], values)
        elif path == "/campaign-end":
            count, total = int(query["count"]), int(query["total"])
            expected = min(args["limit"], max(0, total - args["offset"]))
            if not 0 <= total <= 100000 or count != expected:
                raise ValueError("Invalid campaign page completion count")
            page.update(expected_count=count, total=total)
        else:
            raise ValueError("Unknown campaign event")
        created = stored["created"] if stored else time.time()
        self.db.execute(
            "INSERT OR REPLACE INTO campaign_exports VALUES (?,?,?)",
            (command["id"], created, json.dumps(page)),
        )
        self.db.commit()

    def decode(self, dataset, v):
        row = {"id": v["id"]}
        if dataset in ("party", "prisoners"):
            row.update(
                troop_id=v["a"],
                count=v["b"],
                name=self.catalog.get("troops", {}).get(str(v["a"])),
            )
            if dataset == "party":
                row["wounded"] = v["c"]
        elif dataset == "inventory":
            row.update(
                slot=v["id"],
                item_id=v["a"],
                modifier=v["b"],
                amount=v["c"],
                equipped=v["id"] < 10,
                name=self.catalog.get("items", {}).get(str(v["a"])),
            )
        elif dataset == "character":
            attributes = ("strength", "agility", "intelligence", "charisma")
            row.update(
                value=v["a"],
                stat="level"
                if v["id"] == 0
                else attributes[v["id"] - 1]
                if v["id"] < 5
                else self.catalog.get("skills", {}).get(str(v["id"] - 5)),
                skill_id=v["id"] - 5 if v["id"] >= 5 else None,
            )
        elif dataset == "world_parties":
            row.update(
                party_id=v["id"],
                faction_id=v["a"],
                template_id=v["b"],
                party_type=v["c"],
                members=v["d"],
                position={"x": v["e"] / 100, "y": v["f"] / 100},
                name=self.catalog.get("parties", {}).get(str(v["id"])),
                faction=self.catalog.get("factions", {}).get(str(v["a"])),
            )
        elif dataset == "quests":
            row.update(
                quest_id=v["id"],
                giver_troop_id=v["a"],
                target_troop_id=v["b"],
                target_center_id=v["c"],
                state=v["d"],
                expiration_days=v["e"],
                definition=self.catalog.get("quests", {}).get(str(v["id"])),
            )
        return row

    def result(self, job):
        stored = self.db.execute(
            "SELECT * FROM campaign_exports WHERE job=?", (job,)
        ).fetchone()
        if stored is None:
            return {
                "command_id": job,
                "complete": False,
                "reason": "No export received",
            }
        page = json.loads(stored["payload"])
        complete = len(page["rows"]) == page["expected_count"]
        age = time.time() - stored["created"]
        next_offset = page["offset"] + len(page["rows"])
        return {
            **page,
            "rows": sorted(page["rows"].values(), key=lambda r: r["id"]),
            "complete": complete,
            "command_id": job,
            "age_seconds": round(age, 3),
            "stale": age > 30,
            "source": "Warband engine scripts",
            "name_source": "module definitions, not live renamed parties/items",
            "next_offset": next_offset
            if complete and next_offset < page["total"]
            else None,
            "consistency": "Separate pages are not an atomic game-time snapshot",
        }
