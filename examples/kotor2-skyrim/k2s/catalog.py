"""KOTOR 2 content → a JSON catalog: every item, creature, force power, journal quest and module.

The catalog is the converter's single source of truth. Every later step (arsenal plugin, dialogue,
quests, maps) reads it rather than the game, and it is written to the user's private output folder, never
into the repository: it holds the game's own text.

Column names in KOTOR 2's 2DAs (baseitems, itempropdef, spells, appearance) are read by name with
fallbacks, and anything that wasn't found is listed under `diagnostics`, so a wrong guess shows up in the
catalog instead of becoming silent bad data.
"""
from __future__ import annotations

import re
from collections import Counter

from .kotor import K2Install, as_int, clean_text

# KOTOR's equip slot bits (baseitems.2da `equipableslots`), inherited from Aurora/NWN.
SLOT_HEAD, SLOT_BODY, SLOT_HANDS = 0x1, 0x2, 0x8
SLOT_RIGHT, SLOT_LEFT = 0x10, 0x20
SLOT_LEFT_ARM, SLOT_RIGHT_ARM = 0x80, 0x100
SLOT_IMPLANT, SLOT_BELT = 0x200, 0x400

RANGED_WORDS = re.compile(r"blaster|pistol|rifle|repeat|disruptor|(?<![a-z])ion(?![a-z])|bowcaster|carbine|sonic|cannon"
                          r"|(?<![a-z])gun|launcher")
TWO_HANDED_RANGED = re.compile(r"rifle|repeat|bowcaster|carbine|cannon|launcher")
TWO_HANDED_MELEE = re.compile(r"double|staff|quarter|two.?hand|gamorr|great|pike|force_?pike|war_?blade")
SABER_COLOURS = ["blue", "red", "green", "yellow", "violet", "cyan", "silver", "orange", "viridian", "bronze",
                 "black", "white", "gold", "purple"]
# Template ModelVariation → colour as in KOTOR's own g_w_lghtsbr01..05 (blue, red, green, yellow, violet).
# Higher numbers are TSL's extra colours; unconfirmed, so the catalog marks them "guess".
VARIATION_COLOUR = {1: "blue", 2: "red", 3: "green", 4: "yellow", 5: "violet"}
# The blade's texture in the saber's own model is the real answer (w_lsabre<code>01), read from the install.
BLADE_TEXTURE_COLOUR = {"blue": "blue", "red": "red", "gren": "green", "yelo": "yellow", "purp": "violet",
                        "gold": "orange", "turq": "cyan", "dgrn": "viridian", "silv": "silver"}


def item_model(it: dict) -> str:
    """The model resref an item draws with: baseitems' default model with the item's ModelVariation in
    place of its trailing number (w_lghtsbr_001 + variation 3 → w_lghtsbr_003)."""
    base = (it.get("default_model") or "").lower()
    m = re.match(r"(.*?)(\d+)$", base)
    if m and it.get("model_variation"):
        return f"{m.group(1)}{it['model_variation']:0{len(m.group(2))}d}"
    return base


def col(row: dict | None, *names: str, default: str = "") -> str:
    if not row:
        return default
    for n in names:
        if n in row and row[n] not in ("", "****"):
            return row[n]
    return default


class Catalog:
    def __init__(self, install: K2Install):
        self.k = install
        self.diag: Counter = Counter()
        self.baseitems = install.twoda("baseitems") or []
        if not self.baseitems:
            self.diag["baseitems.2da missing"] += 1
        self.itempropdef = install.twoda("itempropdef") or []
        self.costtable = install.twoda("iprp_costtable") or []

    # ------------------------------------------------------------ helpers
    def base_row(self, index: int) -> dict | None:
        return self.baseitems[index] if 0 <= index < len(self.baseitems) else None

    def strref_text(self, cell: str) -> str:
        n = as_int(cell, -1)
        return self.k.string(n) if n >= 0 else ""

    def _table_row(self, table: str, index: int) -> dict | None:
        rows = self.k.twoda(table) if table else None
        if rows and 0 <= index < len(rows):
            return rows[index]
        return None

    def _row_name(self, row: dict | None) -> str:
        if not row:
            return ""
        return self.strref_text(col(row, "name", "strref")) or col(row, "label", "_label")

    def describe_property(self, p: dict) -> dict:
        """One UTI property (PropertiesList entry) → names, a readable line, and parsed numbers."""
        prop_index = p.get("PropertyName", 0)
        pdef = self.itempropdef[prop_index] if 0 <= prop_index < len(self.itempropdef) else None
        name = self._row_name(pdef) or f"property {prop_index}"
        sub_table = col(pdef, "subtyperesref")
        sub = self._row_name(self._table_row(sub_table, p.get("Subtype", 0))) if sub_table else ""
        cost_name = ""
        cost_row = None
        ct = p.get("CostTable", 0)
        if 0 <= ct < len(self.costtable):
            cost_name = col(self.costtable[ct], "name", "label")
            if cost_name:
                cost_row = self._table_row(cost_name, p.get("CostValue", 0))
        value = self._row_name(cost_row) if cost_row else ""
        out = {"property": name, "subtype": sub, "value": value,
               "text": " ".join(x for x in (name + ":" if (sub or value) else name, sub, value) if x).strip()}
        avg = _average(cost_row, value)
        label = (col(pdef, "label") + " " + name).lower()
        if avg is not None:
            if "damage" in label and ("bonus" in label or "massive" in label) and "vs" not in label \
                    and "reduc" not in label and "immun" not in label:
                out["damage_avg"] = avg
            elif re.search(r"\b(ac|armou?r|defen[cs]e)\b", label) and "bonus" in label and "vs" not in label:
                out["ac"] = avg
            elif "attack" in label and "bonus" in label and "vs" not in label:
                out["attack"] = avg
        return out

    # ------------------------------------------------------------ items
    def classify(self, base: dict | None, base_index: int) -> dict:
        label = (col(base, "_label", "label") + " " + col(base, "label")).lower()
        slots = as_int(col(base, "equipableslots"), 0)
        ranged = as_int(col(base, "rangedweapon"), 0) > 0 or bool(RANGED_WORDS.search(label))
        info = {"slots": slots}
        if re.search(r"creature|claw|bite|(?<![a-z])slam|natural", label):
            info["class"] = "creature_weapon"  # monsters' built-in attacks, not loot
        elif "crystal" in label or "sbrcrstl" in col(base, "itemclass").lower():
            info["class"] = "crystal"  # TSL crystals: colour and bonuses for the saber they're fitted to
        elif "saber" in label:
            info["class"] = "lightsaber"
            info["kind"] = "double" if "double" in label else "short" if "short" in label else "standard"
            info["hands"] = 2 if info["kind"] == "double" else 1
        elif slots & (SLOT_RIGHT | SLOT_LEFT):
            if ranged:
                info["class"] = "ranged"
                info["hands"] = 2 if TWO_HANDED_RANGED.search(label) else 1
                info["kind"] = "heavy" if re.search(r"repeat|cannon|launcher", label) else \
                    "rifle" if info["hands"] == 2 else "pistol"
            else:
                info["class"] = "melee"
                info["hands"] = 2 if TWO_HANDED_MELEE.search(label) else 1
                info["kind"] = "staff" if re.search(r"staff|quarter|pike", label) else \
                    "blunt" if re.search(r"baton|club|mace|stun", label) else \
                    "dagger" if re.search(r"vibroblade|knife|dagger|short", label) else "blade"
        elif slots & SLOT_BODY:
            info["class"] = "robe" if "robe" in label or "jedi" in label else "armor"
            m = re.search(r"class_?(\d+)", label)
            info["armor_class"] = int(m.group(1)) if m else as_int(col(base, "baseac"), 0)
        elif slots & SLOT_HEAD:
            info["class"] = "head"
        elif slots & SLOT_HANDS:
            info["class"] = "hands"
        elif slots & (SLOT_LEFT_ARM | SLOT_RIGHT_ARM):
            info["class"] = "arms"
        elif slots & SLOT_IMPLANT:
            info["class"] = "implant"
        elif slots & SLOT_BELT:
            info["class"] = "belt"
        else:
            info["class"] = "misc"
        if base is None:
            self.diag[f"item with unknown base item {base_index}"] += 1
        return info

    def item(self, res) -> dict:
        g = self.k.gff(res.resname, "uti") or {}
        base_index = g.get("BaseItem", -1)
        base = self.base_row(base_index)
        info = self.classify(base, base_index)
        name = clean_text(g.get("LocalizedName", {}).get("text", ""))
        desc = clean_text((g.get("DescIdentified") or g.get("Description") or {}).get("text", ""))
        # TSL properties with an UpgradeType other than 255 only switch on when that upgrade slot is
        # filled (crystals, cells, emitters), so they don't count towards the item's own power.
        all_props = g.get("PropertiesList", []) or []
        props = [self.describe_property(p) for p in all_props if p.get("UpgradeType", 255) == 255]
        upgrade_props = [{**self.describe_property(p), "upgrade_type": p["UpgradeType"]}
                         for p in all_props if p.get("UpgradeType", 255) != 255]
        it = {
            "resref": res.resname,
            "source": f"{res.source}:{res.container}",
            "tag": g.get("Tag", ""),
            "name": name or res.resname,
            "description": desc,
            "base_item": base_index,
            "base_label": col(base, "label", "_label"),
            "base_name": self.strref_text(col(base, "name")),
            **info,
            "dice": [as_int(col(base, "numdice"), 0), as_int(col(base, "dietoroll"), 0)],
            "crit_threat": as_int(col(base, "critthreat"), 0),
            "crit_mult": as_int(col(base, "crithitmult"), 0),
            "base_ac": as_int(col(base, "baseac"), 0),
            "default_model": col(base, "defaultmodel", "modelname"),
            "model_variation": g.get("ModelVariation", 0),
            "texture_variation": g.get("TextureVar", 0),
            "body_variation": g.get("BodyVariation", 0),
            "cost": g.get("Cost", 0),
            "upgrade_level": g.get("UpgradeLevel", 0),
            "plot": bool(g.get("Plot", 0)),
            "properties": props,
            "upgrade_properties": upgrade_props,
            "damage_bonus_avg": round(sum(p.get("damage_avg", 0) for p in props), 2),
            "ac_bonus": round(sum(p.get("ac", 0) for p in props), 2),
            "attack_bonus": round(sum(p.get("attack", 0) for p in props), 2),
        }
        if base is not None and not col(base, "numdice") and it["class"] in ("melee", "ranged", "lightsaber"):
            self.diag["baseitems.2da: no numdice column"] += 1
        if it["class"] == "lightsaber":
            it["colour"], it["colour_source"] = self.saber_colour(it)
        return it

    def saber_colour(self, it: dict) -> tuple[str, str]:
        text = f"{it['name']} {it['tag']} {it['resref']}".lower()
        for c in SABER_COLOURS:
            if re.search(rf"\b{c}\b", text):
                return c, "name"
        for p in it["properties"] + it["upgrade_properties"]:
            for c in SABER_COLOURS:
                if c in p["text"].lower():
                    return c, "property"
        tex = self.blade_texture(item_model(it))
        if tex:
            return BLADE_TEXTURE_COLOUR.get(tex, tex), "model"
        m = re.search(r"lghtsbr(\d+)", it["resref"])
        var = int(m.group(1)) if m else it["model_variation"]
        if var in VARIATION_COLOUR:
            return VARIATION_COLOUR[var], "variation"
        return "blue", "guess"

    def blade_texture(self, model: str) -> str:
        """The colour code in a saber model's blade texture (w_lsabreblue01 -> 'blue'), or ''."""
        if not hasattr(self, "_blades"):
            self._blades = {}
        if model not in self._blades:
            self._blades[model] = ""
            r, x = self.k.get(model, "mdl"), self.k.get(model, "mdx")
            if r:
                try:
                    from .mdlraw import RawModel
                    mdl = RawModel(r.data(), x.data() if x else None)
                    for nd in mdl.root.walk():
                        m = re.match(r"w_lsabre([a-z]+?)\d*$", ((nd.mesh and nd.mesh.texture) or "").lower())
                        if m:
                            self._blades[model] = m.group(1)
                            break
                except Exception:  # noqa: BLE001 - a bad model falls back to the name/variation rules
                    self.diag[f"saber model unreadable: {model}"] += 1
        return self._blades[model]

    def items(self) -> list[dict]:
        return [self.item(r) for r in self.k.all("uti")]

    # ------------------------------------------------------------ creatures
    def creatures(self) -> list[dict]:
        appearance = self.k.twoda("appearance") or []
        out = []
        for r in self.k.all("utc"):
            g = self.k.gff(r.resname, "utc") or {}
            first = g.get("FirstName", {}).get("text", "")
            last = g.get("LastName", {}).get("text", "")
            app = g.get("Appearance_Type", 0)
            arow = appearance[app] if 0 <= app < len(appearance) else None
            out.append({
                "resref": r.resname,
                "source": f"{r.source}:{r.container}",
                "tag": g.get("Tag", ""),
                "name": " ".join(x for x in (first, last) if x) or r.resname,
                "appearance": app,
                "appearance_label": col(arow, "_label", "label"),
                "race": col(arow, "race"),
                "model": col(arow, "modela", "model", "race"),
                "gender": g.get("Gender", 0),
                "hp": g.get("MaxHitPoints", g.get("HitPoints", 0)),
                "fp": g.get("MaxForcePoints", g.get("ForcePoints", 0)),
                "faction": g.get("FactionID", 0),
                "conversation": g.get("Conversation", ""),
                "soundset": g.get("SoundSetFile", 0),
                "classes": [(c.get("Class"), c.get("ClassLevel")) for c in g.get("ClassList", []) or []],
                "equipment": [e.get("EquippedRes", "") for e in g.get("Equip_ItemList", []) or []],
                "inventory": [e.get("InventoryRes", "") for e in g.get("ItemList", []) or []],
                "stats": {k: g.get(k, 0) for k in ("Str", "Dex", "Con", "Int", "Wis", "Cha")},
            })
        return out

    # ------------------------------------------------------------ force powers
    def force_powers(self) -> list[dict]:
        rows = self.k.twoda("spells") or []
        out = []
        for row in rows:
            name = self.strref_text(col(row, "name"))
            if not name:
                continue
            out.append({
                "row": as_int(row["_row"]),
                "label": col(row, "label", "_label"),
                "name": name,
                "description": self.strref_text(col(row, "spelldesc", "description")),
                "force_cost": as_int(col(row, "forcepoints", "fpcost", "spcost", "forcecost"), 0),
                "alignment": col(row, "forcehostile", "forcefriendly", "pips"),
                "category": col(row, "category", "usertype"),
                "impact_script": col(row, "impactscript"),
                "talent_category": col(row, "talentcategory"),
            })
        return out

    # ------------------------------------------------------------ journal
    def journal(self) -> list[dict]:
        g = self.k.gff("global", "jrl") or {}
        out = []
        for cat in g.get("Categories", []) or []:
            out.append({
                "tag": cat.get("Tag", ""),
                "name": cat.get("Name", {}).get("text", ""),
                "priority": cat.get("Priority", 0),
                "planet": cat.get("PlanetID", -1),
                "plot_index": cat.get("PlotIndex", -1),
                "comment": cat.get("Comment", ""),
                "entries": [{"id": e.get("ID", 0), "text": e.get("Text", {}).get("text", ""),
                             "end": bool(e.get("End", 0)), "xp_percentage": e.get("XP_Percentage", 1.0)}
                            for e in cat.get("EntryList", []) or []],
            })
        return out

    # ------------------------------------------------------------ modules
    def modules(self) -> list[dict]:
        """One row per module (e.g. 101PER, Peragus), from its .rim/_s.rim/_dlg.erf/.mod files."""
        mods: dict[str, dict] = {}
        for container, resources in self.k.by_module.items():
            code = re.sub(r"(_s|_dlg|_a|_adx|_x)?\.(rim|mod|erf)$", "", container)
            m = mods.setdefault(code, {"module": code, "containers": [], "areas": [], "counts": Counter()})
            m["containers"].append(container)
            for r in resources:
                m["counts"][r.ext] += 1
                if r.resname == "module" and r.ext == "ifo":
                    ifo = self._module_gff(r)
                    m["name"] = (ifo.get("Mod_Name") or {}).get("text", "")
                    m["entry_area"] = ifo.get("Mod_Entry_Area", "")
                    m["entry"] = [ifo.get("Mod_Entry_X", 0.0), ifo.get("Mod_Entry_Y", 0.0), ifo.get("Mod_Entry_Z", 0.0)]
                    m["areas"] = [a.get("Area_Name", "") for a in ifo.get("Mod_Area_list", []) or []]
                    m["on_load"] = ifo.get("Mod_OnModLoad", "")
        out = []
        for m in sorted(mods.values(), key=lambda m: m["module"]):
            m["counts"] = dict(m["counts"])
            out.append(m)
        return out

    def _module_gff(self, res) -> dict:
        from .kotor import gff_dict
        try:
            return gff_dict(res.data(), self.k)
        except Exception:  # noqa: BLE001 - one damaged module shouldn't stop the catalog
            self.diag[f"unreadable {res.resname}.{res.ext} in {res.container}"] += 1
            return {}

    # ------------------------------------------------------------ all
    def build(self) -> dict:
        data = {
            "game": "Star Wars: Knights of the Old Republic II - The Sith Lords",
            "install": str(self.k.path),
            "items": self.items(),
            "creatures": self.creatures(),
            "force_powers": self.force_powers(),
            "journal": self.journal(),
            "modules": self.modules(),
            "dialogues": sorted(r.resname for r in self.k.all("dlg")),
        }
        data["summary"] = {
            "items_by_class": dict(Counter(i["class"] for i in data["items"])),
            "creatures": len(data["creatures"]),
            "force_powers": len(data["force_powers"]),
            "quests": len(data["journal"]),
            "modules": len(data["modules"]),
            "dialogues": len(data["dialogues"]),
        }
        data["diagnostics"] = dict(self.diag)
        return data


def _average(cost_row: dict | None, label: str) -> float | None:
    """The average of a cost-table value: NumDice/Die columns, a 'XdY' label, or a plain number."""
    if cost_row:
        n, d = as_int(col(cost_row, "numdice"), 0), as_int(col(cost_row, "die", "dietoroll"), 0)
        if n and d:
            return n * (d + 1) / 2
        for c in ("value", "amount", "bonus"):
            if col(cost_row, c):
                return float(as_int(col(cost_row, c), 0))
    text = f"{label} {col(cost_row, 'label')}".lower()
    m = re.search(r"(\d+)\s*d\s*(\d+)", text)
    if m:
        return int(m.group(1)) * (int(m.group(2)) + 1) / 2
    m = re.search(r"[+-]?\d+", text)
    return float(m.group(0)) if m else None
