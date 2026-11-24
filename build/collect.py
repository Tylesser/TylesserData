"""Merges what the Tylesser Collector recorded and builds the Tylesser - Data addon's Data/*.lua.

  python build/collect.py                      summary of every file found
  python build/collect.py merge                also writes build/out/collected.json (everything merged, to look at)
  python build/collect.py build                merges and writes Data/*.lua
  python build/collect.py files                lists the files it reads
  ... --from <dir>                             read the uploads in <dir> (*.lua and *.lua.gz, any depth) instead

Without --from it reads your own file from the game's WTF folder and tools/collector/inbox/*.lua (files people sent
you). The weekly GitHub Action (.github/workflows/weekly.yml) runs it --from the uploads downloaded from tylesser.com.

One file per install: the collector saves an anonymous install ID, and an install's newest file replaces its older
ones (a file grows week after week; counting both would count its kills twice). build/exclude.txt lists install IDs
whose files are left out (a bad or fake upload). Every record counts the installs that saw it (seenBy); records seen
by fewer than TYLESSER_MIN_SOURCES installs (default 1) stay out of the addon.

Only reads files. Keeps game data only: the collector never records a player's name, realm or GUID, and nothing
here adds one (file names and install IDs stay out of the output).
"""
import glob
import gzip
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = r"C:\Program Files (x86)\World of Warcraft\_forever_"
INBOX = os.environ.get("TYLESSER_INBOX") or r"E:\Games\Wow\tools\collector\inbox"
OUT_JSON = os.environ.get("TYLESSER_COLLECT_JSON") or os.path.join(HERE, "out", "collected.json")
ADDON = os.environ.get("TYLESSER_DATA_DIR") or os.path.normpath(os.path.join(HERE, ".."))
EXCLUDE = os.environ.get("TYLESSER_EXCLUDE") or os.path.join(HERE, "exclude.txt")
MIN_SOURCES = int(os.environ.get("TYLESSER_MIN_SOURCES") or 1)
FROM_DIR = None  # --from <dir>


# A reader for the Lua table literals the game writes into SavedVariables (the same as tools/devlog's) ---------------

TOKEN = re.compile(r'''\s*(?:(--\[\[.*?\]\])|(--[^\n]*)|("(?:\\.|[^"\\])*")|(\[\[.*?\]\])|([-+]?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+|0x[0-9a-fA-F]+|inf|nan))|(\w+)|(.))''', re.S)
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
           "\n": "\n"}


def unquote(text):
    body = text[1:-1]
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt.isdigit():
                m = re.match(r"\d{1,3}", body[i + 1:])
                out.append(chr(int(m.group(0))))
                i += 1 + len(m.group(0))
                continue
            out.append(ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def tokens(text):
    for m in TOKEN.finditer(text):
        block, line, string, long, number, word, sym = m.groups()
        if block or line:
            continue
        if string:
            yield ("str", unquote(string))
        elif long:
            yield ("str", long[2:-2])
        elif number:
            yield ("num", float(number) if any(c in number for c in ".eEn") else int(number, 0))
        elif word:
            yield ("word", word)
        elif sym and sym.strip():
            yield ("sym", sym)


class Parser:
    def __init__(self, text):
        self.toks = list(tokens(text))
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def value(self):
        kind, val = self.take()
        if kind in ("str", "num"):
            return val
        if kind == "word":
            return {"true": True, "false": False, "nil": None}.get(val, val)
        if kind == "sym" and val == "-":
            return -self.value()
        if kind == "sym" and val == "{":
            return self.table()
        raise ValueError("unexpected %r" % (val,))

    def table(self):
        arr, obj = [], {}
        while True:
            kind, val = self.peek()
            if kind == "sym" and val == "}":
                self.take()
                break
            if kind == "sym" and val == "[":
                self.take()
                key = self.value()
                self.take()  # ]
                self.take()  # =
                obj[key] = self.value()
            elif kind == "word" and self.i + 1 < len(self.toks) and self.toks[self.i + 1] == ("sym", "="):
                self.take()
                self.take()
                obj[val] = self.value()
            else:
                arr.append(self.value())
            if self.peek() in (("sym", ","), ("sym", ";")):
                self.take()
        if obj and not arr:
            # integer keys 1..n written as ["1"]-style or [1] = ... become a list
            if all(isinstance(k, int) for k in obj) and sorted(obj) == list(range(1, len(obj) + 1)):
                return [obj[k] for k in range(1, len(obj) + 1)]
            return {str(k): v for k, v in obj.items()}
        if obj:
            merged = {str(i + 1): v for i, v in enumerate(arr)}
            merged.update({str(k): v for k, v in obj.items()})
            return merged
        return arr




SPOT_MERGE = 1.0  # map percent, as in the collector
SPOT_CAP = 40


def files():
    override = os.environ.get("TYLESSER_COLLECT_FILES")  # (the tests: their own sample files)
    if override:
        return [p for p in override.split(os.pathsep) if p]
    if FROM_DIR:
        found = glob.glob(os.path.join(FROM_DIR, "**", "*.lua"), recursive=True)
        found += glob.glob(os.path.join(FROM_DIR, "**", "*.lua.gz"), recursive=True)
        return sorted(found)
    found = glob.glob(os.path.join(GAME, "WTF", "Account", "*", "SavedVariables", "TylesserCollector.lua"))
    found += sorted(glob.glob(os.path.join(INBOX, "*.lua")))
    return found


def read(path):
    if path.endswith(".gz"):
        text = gzip.open(path, "rt", encoding="utf-8", errors="replace").read()
    else:
        text = open(path, encoding="utf-8", errors="replace").read()
    p = Parser(text)
    while p.peek()[0] is not None:
        kind, name = p.take()
        if kind == "word" and p.peek() == ("sym", "="):
            p.take()
            value = p.value()
            if name == "TylesserCollectorDB":
                return value if isinstance(value, dict) else {}
    return {}


# Helpers --------------------------------------------------------------------------------------------------------------

def items(table):
    """A Lua table read back as a dict (string keys) or a list (1..n): (key, value) pairs either way."""
    if isinstance(table, dict):
        return table.items()
    if isinstance(table, list):
        return ((str(i + 1), v) for i, v in enumerate(table))
    return ()


def as_list(table):
    if isinstance(table, list):
        return table
    if isinstance(table, dict):
        return [table[k] for k in sorted(table, key=lambda k: int(k) if str(k).isdigit() else 0)]
    return []


def key_int(key):
    try:
        return int(float(key))
    except (TypeError, ValueError):
        return None


def add_spots(target, spots):
    """target: {map: [[x, y, n], ...]}; spots: the collector's {map: {{x, y, n}, ...}}."""
    for map_key, lst in items(spots):
        map_id = key_int(map_key)
        if map_id is None:
            continue
        mine = target.setdefault(map_id, [])
        for spot in as_list(lst):
            spot = as_list(spot)
            if len(spot) < 2:
                continue
            x, y, n = float(spot[0]), float(spot[1]), int(spot[2]) if len(spot) > 2 else 1
            for old in mine:
                if (old[0] - x) ** 2 + (old[1] - y) ** 2 <= SPOT_MERGE ** 2:
                    total = old[2] + n
                    old[0] = round((old[0] * old[2] + x * n) / total, 1)
                    old[1] = round((old[1] * old[2] + y * n) / total, 1)
                    old[2] = total
                    break
            else:
                if len(mine) < SPOT_CAP:
                    mine.append([x, y, n])


class Votes:
    """The most frequent value of a field across files (ties: the newest)."""
    def __init__(self):
        self.counts = {}

    def add(self, value):
        if value not in (None, ""):
            self.counts[value] = self.counts.get(value, 0) + 1

    def best(self):
        return max(self.counts.items(), key=lambda kv: kv[1])[0] if self.counts else None


# Merging ---------------------------------------------------------------------------------------------------------------

def respawn_estimate(sightings):
    """A rare's respawn, roughly: the shortest wait from a sighting dead to the next sighting alive (seconds)."""
    best = None
    ordered = sorted((s for s in sightings if isinstance(s, dict) and s.get("t")), key=lambda s: s["t"])
    for before, after in zip(ordered, ordered[1:]):
        if before.get("dead") and after.get("dead") is False:
            gap = after["t"] - before["t"]
            if gap > 60 and (best is None or gap < best):
                best = gap
    return best


def restock_estimate(observations):
    """A limited item's restock, roughly: the shortest time in which the count went up (seconds)."""
    best = None
    ordered = sorted((o for o in observations if isinstance(o, dict) and o.get("t") is not None), key=lambda o: o["t"])
    for before, after in zip(ordered, ordered[1:]):
        if (after.get("n") or 0) > (before.get("n") or 0):
            gap = after["t"] - before["t"]
            if gap > 0 and (best is None or gap < best):
                best = gap
    return best


def merge(dbs):
    npcs, objects, quests, vendors, trainers, loot, taxi = {}, {}, {}, {}, {}, {}, {}
    instances, encounters, areas, discovered, graveyards, flights = {}, {}, {}, {}, {}, {}
    sightings, stock = {}, {}
    quest_items = {}
    vignettes, pois, texts, speech, prices, recipes = {}, {}, {}, {}, {}, {}
    mail, found = {}, {}
    votes = {}
    errors = []

    def vote(kind, id_, field, value):
        votes.setdefault((kind, id_, field), Votes()).add(value)

    sources = {}  # (kind, key) = the installs that saw it

    for number, db in enumerate(dbs):
        install = db.get("install") if isinstance(db.get("install"), str) else "file:%d" % number

        def seen(kind, key):
            sources.setdefault((kind, key), set()).add(install)

        errors += [e for _, e in items(db.get("errors"))]
        for item_key, quest in items(db.get("questItems")):
            iid = key_int(item_key)
            if iid is not None:
                # a quest ID beats a plain "true" (an item flagged as a quest item without its quest)
                if isinstance(quest, (int, float)) and not isinstance(quest, bool) or iid not in quest_items:
                    quest_items[iid] = int(quest) if isinstance(quest, (int, float)) and not isinstance(quest, bool) else True
        for key, npc in items(db.get("npcs")):
            nid = key_int(key)
            if nid is None or not isinstance(npc, dict):
                continue
            out = npcs.setdefault(nid, {"spots": {}})
            seen("npcs", nid)
            for field in ("name", "title", "class", "type", "faction", "reaction"):
                vote("npc", nid, field, npc.get(field))
            for field, pick in (("minLevel", min), ("maxLevel", max)):
                if isinstance(npc.get(field), (int, float)):
                    out[field] = pick(out.get(field, npc[field]), int(npc[field]))
            if npc.get("boss"):
                out["boss"] = True
            if npc.get("gossip"):
                gossip = [g for _, g in items(npc["gossip"]) if isinstance(g, dict)]
                if len(gossip) >= len(out.get("gossip", [])):
                    out["gossip"] = gossip
            if npc.get("taxiNode"):
                out["taxiNode"] = int(npc["taxiNode"])
            if npc.get("encounter"):
                out["encounter"] = int(npc["encounter"])
            add_spots(out["spots"], npc.get("spots"))
            for service, _ in items(npc.get("services")):
                out.setdefault("services", set()).add(service)
            for level, pair in items(npc.get("xp")):
                pair, lvl = as_list(pair), key_int(level)
                if lvl and len(pair) >= 2:
                    old = out.setdefault("xp", {}).setdefault(lvl, [0, 0])
                    old[0] += int(pair[0])
                    old[1] += int(pair[1])
            for faction, amount in items(npc.get("rep")):
                out.setdefault("rep", {})[faction] = amount
            for spell, count in items(npc.get("spells")):
                sid = key_int(spell)
                if sid:
                    out.setdefault("spells", {})[sid] = out.get("spells", {}).get(sid, 0) + int(count or 0)
            for field in ("greeting", "family"):
                vote("npc", nid, field, npc.get(field))
            for field in ("power", "inn"):
                if npc.get(field) is not None:
                    out[field] = npc[field]
            for text, how in items(npc.get("says")):
                out.setdefault("says", {})[text] = how
            for text, _ in items(npc.get("pages")):
                out.setdefault("pages", {})[text] = True
            for name, what in items(npc.get("options")):
                out.setdefault("options", {})[name] = what
            if isinstance(npc.get("respawnSeen"), (int, float)):
                out["respawnSeen"] = min(out.get("respawnSeen", npc["respawnSeen"]), int(npc["respawnSeen"]))
            if npc.get("discoversFlightPath"):
                out["discoversFlightPath"] = True
            if npc.get("skinnable"):
                out["skinnable"] = True
            if isinstance(npc.get("skinSkillMin"), (int, float)):
                out["skinSkillMin"] = min(out.get("skinSkillMin", npc["skinSkillMin"]), int(npc["skinSkillMin"]))
            if isinstance(npc.get("requires"), dict):
                out["requires"] = npc["requires"]
            for _, sighting in items(npc.get("sightings")):
                if isinstance(sighting, dict):
                    sightings.setdefault(nid, []).append(sighting)
        for key, obj in items(db.get("objects")):
            oid = key_int(key)
            if oid is None or not isinstance(obj, dict):
                continue
            out = objects.setdefault(oid, {"spots": {}})
            seen("objects", oid)
            vote("object", oid, "name", obj.get("name"))
            add_spots(out["spots"], obj.get("spots"))
            for service, _ in items(obj.get("services")):
                out.setdefault("services", set()).add(service)
            if obj.get("gather"):
                out["gather"] = obj["gather"]
            for map_key, _ in items(obj.get("leadsTo")):
                if key_int(map_key) is not None:
                    out.setdefault("leadsTo", set()).add(key_int(map_key))
            req = obj.get("requires")
            if isinstance(req, dict) and req.get("skill"):
                # the highest level any file saw the game ask for (a tooltip may show none)
                old = out.get("requires") or {}
                level = max([v for v in (old.get("level"), req.get("level")) if isinstance(v, (int, float))] or [0]) or None
                out["requires"] = {"skill": req["skill"], "level": level}
            for field, pick in (("skillMin", min), ("skillMax", max)):
                if isinstance(obj.get(field), (int, float)):
                    out[field] = pick(out.get(field, obj[field]), int(obj[field]))
        for key, quest in items(db.get("quests")):
            qid = key_int(key)
            if qid is None or not isinstance(quest, dict):
                continue
            out = quests.setdefault(qid, {"starts": {}, "ends": {}, "accepted": {}, "objectiveSpots": {}})
            seen("quests", qid)
            for field in ("title", "text", "description", "progressText", "completionText", "tag", "line", "zone"):
                vote("quest", qid, field, quest.get(field))
            for field in ("tagID", "lineID"):
                if quest.get(field) is not None:
                    out[field] = quest[field]
            if isinstance(quest.get("offeredAt"), (int, float)):
                out["offeredAt"] = min(out.get("offeredAt", quest["offeredAt"]), int(quest["offeredAt"]))
            for level, xp in items(quest.get("xpByLevel")):
                if key_int(level) is not None:
                    out.setdefault("xpByLevel", {})[key_int(level)] = xp
            for field in ("level", "group", "frequency", "xp", "money", "rewardMoney", "rewardXP", "requiredMoney",
                          "timeLimit"):
                if isinstance(quest.get(field), (int, float)):
                    out[field] = max(out.get(field, 0), int(quest[field])) if field in ("xp", "money", "rewardMoney", "rewardXP") else int(quest[field])
            for field in ("choices", "rewards", "required"):
                lst = [i for i in as_list(quest.get(field)) if isinstance(i, dict) and i.get("item")]
                if len(lst) >= len(out.get(field, [])) and lst:
                    out[field] = lst
            for faction, amount in items(quest.get("rep")):
                out.setdefault("rep", {})[faction] = amount
            for field in ("objectiveNpcs", "objectiveSources"):
                for index, causes in items(quest.get(field)):
                    idx = key_int(index)
                    if idx is None:
                        continue
                    bucket = out.setdefault(field, {}).setdefault(idx, {})
                    for cause, count in items(causes):
                        key = key_int(cause) if field == "objectiveNpcs" else str(cause)
                        if key is not None:
                            bucket[key] = bucket.get(key, 0) + int(count or 0)
            for item_key, _ in items(quest.get("dropItems")):
                if key_int(item_key) is not None:
                    out.setdefault("dropItems", set()).add(key_int(item_key))
            for before, count in items(quest.get("after")):
                bid = key_int(before)
                if bid:
                    out.setdefault("after", {})[bid] = out.get("after", {}).get(bid, 0) + int(count or 0)
            out["done"] = out.get("done", 0) + int(quest.get("done") or 0)
            objectives = as_list(quest.get("objectives"))
            if len(objectives) >= len(out.get("objectives", [])) and objectives:
                out["objectives"] = [o for o in objectives if isinstance(o, dict)]
            for field in ("starts", "ends"):
                for kind, ids in items(quest.get(field)):
                    bucket = out[field].setdefault(kind, set())
                    for id_key, _ in items(ids):
                        if key_int(id_key) is not None:
                            bucket.add(key_int(id_key))
            for field in ("races", "classes", "factions"):
                bucket = out.setdefault(field, set())
                for name, _ in items(quest.get(field)):
                    bucket.add(name)
            add_spots(out["accepted"], (quest.get("accepted") or {}).get("spots") if isinstance(quest.get("accepted"), dict) else None)
            for index, record in items(quest.get("objectiveSpots")):
                if isinstance(record, dict):
                    add_spots(out["objectiveSpots"].setdefault(key_int(index), {}), record.get("spots"))
        for key, vendor in items(db.get("vendors")):
            vid = key_int(key)
            if vid is None or not isinstance(vendor, dict):
                continue
            out = vendors.setdefault(vid, {"items": {}, "seen": 0})
            newer = (vendor.get("seen") or 0) >= out["seen"]
            for item_key, entry in items(vendor.get("items")):
                iid = key_int(item_key)
                if iid is not None and isinstance(entry, dict) and (newer or iid not in out["items"]):
                    entry = dict(entry)
                    if "costs" in entry:
                        entry["costs"] = [c for c in as_list(entry["costs"]) if isinstance(c, dict)]
                    out["items"][iid] = entry
            out["seen"] = max(out["seen"], vendor.get("seen") or 0)
            for item_key, observations in items(vendor.get("stock")):
                iid = key_int(item_key)
                if iid is not None:
                    stock.setdefault((vid, iid), []).extend(o for _, o in items(observations) if isinstance(o, dict))
        for key, trainer in items(db.get("trainers")):
            tid = key_int(key)
            if tid is None or not isinstance(trainer, dict):
                continue
            out = trainers.setdefault(tid, {"services": {}})
            if trainer.get("type") is not None:
                out["type"] = trainer["type"]
            for service_key, entry in items(trainer.get("services")):
                if isinstance(entry, dict):
                    # a spell ID stays a number ([1002]); a service without one keeps its "name:rank" key
                    key = int(service_key) if str(service_key).isdigit() else str(service_key)
                    out["services"][key] = entry
        for key, record in items(db.get("loot")):
            if not isinstance(record, dict) or ":" not in str(key):
                continue
            out = loot.setdefault(str(key), {"opened": 0, "items": {}})
            seen("loot", str(key))
            out["opened"] += int(record.get("opened") or 0)
            if record.get("money"):
                out["money"] = out.get("money", 0) + int(record["money"])
                out["moneyTimes"] = out.get("moneyTimes", 0) + int(record.get("moneyTimes") or 0)
            for field, pick in (("skillMin", min), ("skillMax", max)):
                if isinstance(record.get(field), (int, float)):
                    out[field] = pick(out.get(field, record[field]), int(record[field]))
            for item_key, pair in items(record.get("items")):
                iid = key_int(item_key)
                pair = as_list(pair)
                if iid is not None and len(pair) >= 2:
                    old = out["items"].setdefault(iid, [0, 0])
                    old[0] += int(pair[0])
                    old[1] += int(pair[1])
        for key, node in items(db.get("taxi")):
            nid = key_int(key)
            if nid is None or not isinstance(node, dict):
                continue
            out = taxi.setdefault(nid, {})
            for field in ("name", "map", "x", "y", "faction", "master"):
                if node.get(field) is not None:
                    out[field] = node[field]
            for to, cost in items(node.get("costs")):
                if key_int(to) is not None and isinstance(cost, (int, float)):
                    out.setdefault("costs", {})[key_int(to)] = int(cost)
            for to, path in items(node.get("routes")):
                if key_int(to) is not None:
                    out.setdefault("routes", {})[key_int(to)] = [int(h) for h in as_list(path) if isinstance(h, (int, float))]
        for key, inst in items(db.get("instances")):
            iid = key_int(key)
            if iid is None or not isinstance(inst, dict):
                continue
            out = instances.setdefault(iid, {"entrance": {}, "difficulties": set()})
            for field in ("name", "type"):
                if inst.get(field):
                    out[field] = inst[field]
            for difficulty, _ in items(inst.get("difficulties")):
                if key_int(difficulty) is not None:
                    out["difficulties"].add(key_int(difficulty))
            entrance = inst.get("entrance")
            add_spots(out["entrance"], entrance.get("spots") if isinstance(entrance, dict) else None)
        for key, enc in items(db.get("encounters")):
            eid = key_int(key)
            if eid is None or not isinstance(enc, dict):
                continue
            out = encounters.setdefault(eid, {"kills": 0, "wipes": 0, "npcs": set(), "difficulties": set()})
            for field in ("name", "instance"):
                if enc.get(field):
                    out[field] = enc[field]
            out["kills"] += int(enc.get("kills") or 0)
            out["wipes"] += int(enc.get("wipes") or 0)
            for npc_key, _ in items(enc.get("npcs")):
                if key_int(npc_key):
                    out["npcs"].add(key_int(npc_key))
            for difficulty, _ in items(enc.get("difficulties")):
                if key_int(difficulty) is not None:
                    out["difficulties"].add(key_int(difficulty))
        for map_key, names in items(db.get("areas")):
            mid = key_int(map_key)
            if mid is None:
                continue
            for name, area in items(names):
                if isinstance(area, dict):
                    out = areas.setdefault(mid, {}).setdefault(name, {"spots": {}})
                    if area.get("zone"):
                        out["zone"] = area["zone"]
                    add_spots(out["spots"], area.get("spots"))
        for name, place in items(db.get("discovered")):
            if isinstance(place, dict):
                out = discovered.setdefault(name, {})
                for field in ("xp", "map", "x", "y"):
                    if place.get(field) is not None:
                        out[field] = place[field]
        yard = db.get("graveyards")
        add_spots(graveyards, yard.get("spots") if isinstance(yard, dict) else None)
        for key, record in items(db.get("flights")):
            if isinstance(record, dict) and "-" in str(key):
                out = flights.setdefault(str(key), {"sum": 0, "n": 0})
                out["sum"] += int(record.get("sum") or 0)
                out["n"] += int(record.get("n") or 0)
        for key, v in items(db.get("vignettes")):
            vid = key_int(key)
            if vid is None or not isinstance(v, dict):
                continue
            out = vignettes.setdefault(vid, {"spots": {}})
            seen("vignettes", vid)
            for field in ("name", "type", "atlas", "quest", "kind", "id"):
                if v.get(field) is not None:
                    out[field] = v[field]
            add_spots(out["spots"], v.get("spots"))
        for map_key, entries in items(db.get("pois")):
            mid = key_int(map_key)
            if mid is None:
                continue
            for poi_key, poi in items(entries):
                if isinstance(poi, dict) and key_int(poi_key) is not None:
                    pois.setdefault(mid, {}).setdefault(key_int(poi_key), {}).update(poi)
        for key, text in items(db.get("texts")):
            if isinstance(text, dict):
                out = texts.setdefault(str(key), {"pages": {}})
                if text.get("title"):
                    out["title"] = text["title"]
                for page, body in items(text.get("pages")):
                    if key_int(page) is not None:
                        out["pages"][key_int(page)] = body
        for key, letter in items(db.get("mail")):
            if isinstance(letter, dict):
                out = mail.setdefault(str(key), {})
                for field in ("sender", "subject", "money", "text"):
                    if letter.get(field) is not None:
                        out[field] = letter[field]
                lst = [i for i in as_list(letter.get("items")) if isinstance(i, dict)]
                if lst:
                    out["items"] = lst
        spots_found = db.get("flightPathsFound")
        add_spots(found, spots_found.get("spots") if isinstance(spots_found, dict) else None)
        for name, lines in items(db.get("speech")):
            for text, how in items(lines):
                speech.setdefault(str(name), {})[text] = how
        for key, history in items(db.get("prices")):
            iid = key_int(key)
            if iid is not None:
                prices.setdefault(iid, []).extend(h for _, h in items(history) if isinstance(h, dict) and h.get("p"))
        for key, recipe in items(db.get("recipes")):
            rid = key_int(key)
            if rid is None or not isinstance(recipe, dict):
                continue
            out = recipes.setdefault(rid, {"colors": {}})
            for field in ("name", "profession", "product", "makesMin", "makesMax"):
                if recipe.get(field) is not None:
                    out[field] = recipe[field]
            reagents = [r for r in as_list(recipe.get("reagents")) if isinstance(r, dict)]
            if reagents:
                out["reagents"] = reagents
            for skill, color in items(recipe.get("colors")):
                if key_int(skill) is not None:
                    out["colors"][key_int(skill)] = color
    # voted fields
    for (kind, id_, field), v in votes.items():
        target = {"npc": npcs, "object": objects, "quest": quests}[kind][id_]
        value = v.best()
        if value is not None:
            target[field] = value
    for quest in quests.values():
        for field in ("starts", "ends"):
            quest[field] = {k: sorted(v) for k, v in quest[field].items() if v}
        for field in ("races", "classes", "factions"):
            quest[field] = sorted(quest.get(field) or [])
    for record in list(npcs.values()) + list(objects.values()):
        if record.get("services"):
            record["services"] = sorted(record["services"])
    for quest in quests.values():
        if isinstance(quest.get("dropItems"), set):
            quest["dropItems"] = sorted(quest["dropItems"])
    for obj in objects.values():
        if isinstance(obj.get("leadsTo"), set):
            obj["leadsTo"] = sorted(obj["leadsTo"])
    for iid, history in prices.items():
        history.sort(key=lambda h: h.get("t") or 0)
        prices[iid] = history[-50:]
    # where a recipe turns yellow / green / grey: the lowest skill each colour was seen at
    for recipe in recipes.values():
        for color in ("medium", "easy", "trivial"):
            seen = [skill for skill, c in recipe["colors"].items() if c == color]
            if seen:
                recipe[color + "At"] = min(seen)
    for nid, seen in sightings.items():
        npc = npcs[nid]
        npc["sightings"] = len(seen)
        respawn = respawn_estimate(seen)
        if respawn:
            npc["respawn"] = respawn
        for sight in seen:
            if sight.get("map") and sight.get("x") is not None:
                add_spots(npc.setdefault("rareSpots", {}), {sight["map"]: [[sight["x"], sight["y"], 1]]})
    for (vid, iid), observations in stock.items():
        entry = vendors[vid]["items"].get(iid)
        restock = restock_estimate(observations)
        if entry is not None and restock:
            entry["restock"] = restock
    for record in list(instances.values()) + list(encounters.values()):
        for field in ("difficulties", "npcs"):
            if isinstance(record.get(field), set):
                record[field] = sorted(record[field])
    # how many installs saw each record (TYLESSER_MIN_SOURCES leaves out what too few saw: one fake file alone
    # can't put a creature, a spot or a drop into the addon once the minimum is raised)
    for (kind, key), installs in sources.items():
        table = {"npcs": npcs, "objects": objects, "quests": quests, "loot": loot, "vignettes": vignettes}[kind]
        if key in table:
            table[key]["seenBy"] = len(installs)
    return {"npcs": npcs, "objects": objects, "quests": quests, "vendors": vendors, "trainers": trainers,
            "loot": loot, "taxi": taxi, "instances": instances, "encounters": encounters, "areas": areas,
            "discovered": discovered, "graveyards": graveyards, "flights": flights, "questItems": quest_items,
            "vignettes": vignettes, "pois": pois, "texts": texts, "speech": speech, "prices": prices,
            "recipes": recipes, "mail": mail, "flightPathsFound": found, "errors": errors}


# The addon's data files -----------------------------------------------------------------------------------------------

def lua(value, indent=""):
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return repr(round(value, 3)) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "") + '"'
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(lua(v, indent) for v in value) + "}"
    if isinstance(value, dict):
        parts = []
        numbers = sorted(k for k in value if isinstance(k, (int, float)) and not isinstance(k, bool))
        names = sorted(str(k) for k in value if not isinstance(k, (int, float)))
        for k in numbers + names:
            v = value[k]
            if v is None or v == {} or v == []:
                continue
            if isinstance(k, (int, float)):
                key = "[" + str(int(k)) + "]"
            elif isinstance(k, str) and k.isidentifier():
                key = k
            else:
                key = "[" + lua(str(k)) + "]"
            parts.append(key + "=" + lua(v, indent))
        return "{" + ",".join(parts) + "}"
    return "nil"


def flat_spots(spots):
    """{map: [[x, y, n]]} -> {[map] = {x, y, n, x, y, n, ...}} (fewer tables in game)."""
    return {m: [c for spot in lst for c in (spot[0], spot[1], spot[2])] for m, lst in spots.items() if lst}


def write_table(name, table, note):
    path = os.path.join(ADDON, "Data", name + ".lua")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("-- Generated by build/collect.py build. Don't edit: rebuild instead.\n")
        f.write("-- " + note + "\n")
        f.write("local _, ns = ...\n")
        f.write("ns.data.%s = {\n" % name)
        for key in sorted(table, key=lambda k: (isinstance(k, str), k)):
            k = "[" + (str(key) if isinstance(key, int) else lua(key)) + "]"
            f.write("  %s=%s,\n" % (k, lua(table[key])))
        f.write("}\n")
    return path


def enough(table):
    """The records seen by at least TYLESSER_MIN_SOURCES installs."""
    return {k: v for k, v in table.items() if not isinstance(v, dict) or v.get("seenBy", MIN_SOURCES) >= MIN_SOURCES}


def build(data):
    data = dict(data)
    for kind in ("npcs", "objects", "quests", "loot", "vignettes"):
        data[kind] = enough(data[kind])
    npcs = {}
    for nid, n in data["npcs"].items():
        npcs[nid] = {k: v for k, v in n.items() if k not in ("spots", "rareSpots", "xp", "spells")}
        npcs[nid]["spots"] = flat_spots(n["spots"])
        if n.get("rareSpots"):
            npcs[nid]["rareSpots"] = flat_spots(n["rareSpots"])
        if n.get("xp"):
            # average xp per kill at each of your levels
            npcs[nid]["xp"] = {lvl: round(p[0] / p[1]) for lvl, p in n["xp"].items() if p[1]}
        if n.get("spells"):
            npcs[nid]["spells"] = sorted(n["spells"])
    objects = {oid: {"name": o.get("name"), "services": o.get("services"), "gather": o.get("gather"),
                     "requires": o.get("requires"), "skillMin": o.get("skillMin"), "skillMax": o.get("skillMax"),
                     "leadsTo": o.get("leadsTo"),
                     "spots": flat_spots(o["spots"])}
               for oid, o in data["objects"].items()}
    quests = {}
    for qid, q in data["quests"].items():
        out = {k: v for k, v in q.items() if k not in ("accepted", "objectiveSpots", "text")}
        out["accepted"] = flat_spots(q["accepted"])
        out["objectiveSpots"] = {i: flat_spots(s) for i, s in q["objectiveSpots"].items() if i is not None and s}
        if q.get("text"):
            out["text"] = q["text"]
        quests[qid] = out
    vendors = {vid: {"items": v["items"], "seen": v["seen"]} for vid, v in data["vendors"].items()}
    trainers = data["trainers"]
    loot = {k: {kk: vv for kk, vv in v.items()} for k, v in data["loot"].items()}
    written = [
        write_table("npcs", npcs, "[npcID] = { name, title, minLevel, maxLevel, boss, class, type, faction, reaction, gossip, taxiNode, spots = { [uiMapID] = { x, y, n, ... } } }"),
        write_table("objects", objects, "[objectID] = { name, spots = { [uiMapID] = { x, y, n, ... } } }"),
        write_table("quests", quests, "[questID] = { title, text, level, group, frequency, xp, money, objectives, starts / ends = { npc = {ids}, object = {ids}, item = {ids} }, races, classes, factions, accepted = spots, objectiveSpots = { [index] = spots } }"),
        write_table("vendors", vendors, "[npcID] = { seen, items = { [itemID] = { price, stack, limit, extended, costs = { { amount, item, currency } } } } }"),
        write_table("trainers", trainers, "[npcID] = { type, services = { [spellID or \"name:rank\"] = { name, rank, level, cost, spell, skill, skillRank } } }"),
        write_table("loot", loot, "[\"npc:<id>\" | \"object:<id>\" | \"fishing:<uiMapID>\"] = { opened, items = { [itemID] = { times, quantity } } }"),
        write_table("taxi", data["taxi"], "[nodeID] = { name, map, x, y, faction, master }"),
        write_table("instances", {i: {"name": v.get("name"), "type": v.get("type"), "difficulties": v["difficulties"],
                                      "entrance": flat_spots(v["entrance"])} for i, v in data["instances"].items()},
                    "[instanceID] = { name, type, difficulties, entrance = { [uiMapID] = { x, y, n, ... } } }"),
        write_table("encounters", data["encounters"], "[encounterID] = { name, instance, kills, wipes, npcs, difficulties }"),
        write_table("areas", {m: {name: {"zone": a.get("zone"), "spots": flat_spots(a["spots"])} for name, a in names.items()}
                              for m, names in data["areas"].items()},
                    "[uiMapID] = { [sub-zone name] = { zone, spots = { [uiMapID] = { x, y, n, ... } } } }"),
        write_table("discovered", data["discovered"], "[place name] = { xp, map, x, y }"),
        write_table("graveyards", {"spots": flat_spots(data["graveyards"])}, "spots = { [uiMapID] = { x, y, n, ... } }"),
        write_table("questItems", data["questItems"], "[itemID] = questID (or true: a quest item without its quest)"),
        write_table("vignettes", {i: dict({k: v for k, v in x.items() if k != "spots"}, spots=flat_spots(x["spots"]))
                                  for i, x in data["vignettes"].items()},
                    "[vignetteID] = { name, type, atlas, quest, kind, id, spots = { [uiMapID] = { x, y, n, ... } } }"),
        write_table("pois", data["pois"], "[uiMapID] = { [areaPoiID] = { name, description, atlas, linkedMap, x, y } }"),
        write_table("texts", data["texts"], "[\"object:<id>\" | \"item:<id>\" | \"title:<title>\"] = { title, pages }"),
        write_table("speech", data["speech"], "[speaker name] = { [line] = \"say\" | \"yell\" | \"emote\" | \"whisper\" } (speakers not met)"),
        write_table("prices", {i: [[h.get("t"), h.get("p"), h.get("q")] for h in hist] for i, hist in data["prices"].items()},
                    "[itemID] = { { time, lowest price, quantity }, ... } (oldest first)"),
        write_table("mail", data["mail"], "[\"<sender>: <subject>\"] = { sender, subject, money, text, items } (NPCs and the game only)"),
        write_table("recipes", data["recipes"], "[recipeID] = { name, profession, product, makesMin, makesMax, reagents, colors = { [skill] = colour }, mediumAt, easyAt, trivialAt }"),
        write_table("flights", {k: round(v["sum"] / v["n"]) for k, v in data["flights"].items() if v["n"]},
                    "[\"<from node>-<to node>\"] = seconds"),
    ]
    stamp = os.path.join(ADDON, "Data", "built.lua")
    counts = {k: len(data[k]) for k in ("npcs", "objects", "quests", "vendors", "trainers", "loot", "taxi",
                                        "instances", "encounters", "areas", "discovered", "flights", "questItems",
                                        "vignettes", "texts", "recipes", "prices")}
    with open(stamp, "w", encoding="utf-8", newline="\n") as f:
        f.write("-- Generated by build/collect.py build.\nlocal _, ns = ...\n")
        f.write("ns.data.built = %s\n" % lua({"date": time.strftime("%Y-%m-%d %H:%M"), "files": len(files()), "counts": counts}))
    return written + [stamp]


# Command line ---------------------------------------------------------------------------------------------------------

def summary(data, n_files):
    print("%d file(s) read" % n_files)
    for key in ("npcs", "objects", "quests", "vendors", "trainers", "loot", "taxi", "instances", "encounters",
                "areas", "discovered", "flights", "vignettes", "pois", "texts", "speech", "prices", "recipes"):
        print("  %-10s %d" % (key, len(data[key])))
    spotted = sum(1 for n in data["npcs"].values() if n["spots"])
    print("  npcs with a spot: %d" % spotted)
    if data["errors"]:
        print("  collector errors: %d (first: %s)" % (len(data["errors"]), data["errors"][0]))


def excluded():
    if not os.path.exists(EXCLUDE):
        return set()
    return {line.split("#")[0].strip() for line in open(EXCLUDE, encoding="utf-8") if line.split("#")[0].strip()}


def newest_per_install(paths):
    """(path, db) for each install's newest file, without the excluded installs; files without an install ID (an
    older collector) each count on their own."""
    skip = excluded()
    best = {}
    for path in paths:
        try:
            db = read(path)
        except Exception as error:  # (a broken file: left out, the build goes on)
            print("skipped %s: %s" % (os.path.basename(path), error))
            continue
        install = db.get("install") if isinstance(db.get("install"), str) else None
        if install in skip:
            continue
        key = install or ("file:" + path)
        when = os.path.getmtime(path)
        if key not in best or when >= best[key][0]:
            best[key] = (when, path, db)
    return [(path, db) for _, path, db in best.values()]


def main(argv):
    global FROM_DIR
    if "--from" in argv:
        index = argv.index("--from")
        FROM_DIR = argv[index + 1]
        argv = argv[:index] + argv[index + 2:]
    command = argv[0] if argv else "summary"
    paths = files()
    if command == "files":
        for path in paths:
            print(path)
        return
    if not paths:
        sys.exit("No collector files yet: enable Tylesser - Collector, play, then /reload. Friends' files go in "
                 + INBOX)
    chosen = newest_per_install(paths)
    data = merge([db for _, db in chosen])
    summary(data, len(chosen))
    if command in ("merge", "build"):
        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        def plain(o):
            if isinstance(o, set):
                return sorted(o)
            raise TypeError(type(o))
        json.dump(data, open(OUT_JSON, "w", encoding="utf-8"), indent=1, default=plain)
        print("wrote", OUT_JSON)
    if command == "build":
        for path in build(data):
            print("wrote", path)


if __name__ == "__main__":
    main(sys.argv[1:])
