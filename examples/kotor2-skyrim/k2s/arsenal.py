"""The catalog's weapons and armour → `KotOR2_Arsenal.esp`, a light (ESL-flagged) Skyrim SE plugin.

Every KOTOR 2 lightsaber, melee weapon, blaster, armour, robe, helmet, glove, arm band, implant and belt
becomes a Skyrim WEAP or ARMO record with real-time stats (stats.py). Models, sounds, impact sets,
keywords and the first-person model come from a vanilla template of the same archetype in the user's own
Skyrim masters, so every item is usable in game before any KOTOR mesh is converted. With `meshes` (the
`--use-meshes` flag), a weapon whose converted model exists as `meshes/kotor2/<model>.nif` uses it instead. Blasters fire from the crossbow archetype with a new ammo, "Power Cell".

Also written: a "KotOR 2 Footlocker" container with one of everything (plus power cells), new keywords
(K2Lightsaber, K2Blaster, K2VibroWeapon, K2Robe) for later perks and scripts, and `arsenal.json` mapping
each KOTOR resref to its Skyrim EditorID and FormID.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from . import stats
from .catalog import item_model
from .esp import Plugin, Record, zstring
from .skyrim import MasterSet

PLUGIN_NAME = "KotOR2_Arsenal.esp"

WEAPON_TEMPLATES = {
    "sword": (stats.ANIM_ONE_HAND_SWORD, ["SteelSword", "IronSword"]),
    "dagger": (stats.ANIM_DAGGER, ["SteelDagger", "IronDagger"]),
    "mace": (stats.ANIM_MACE, ["SteelMace", "IronMace"]),
    "greatsword": (stats.ANIM_TWO_HAND_SWORD, ["SteelGreatsword", "IronGreatsword"]),
    "crossbow": (stats.ANIM_CROSSBOW, ["DLC1Crossbow", "DLC1CrossbowBase"]),
}
ARMOR_TEMPLATES = {
    "cuirass_light": (0x4, 0, ["ArmorLeatherCuirass", "ArmorHideCuirass"]),
    "cuirass_heavy": (0x4, 1, ["ArmorSteelCuirassA", "ArmorIronCuirass"]),
    "helmet_light": (0x1 | 0x2, 0, ["ArmorLeatherHelmet", "ArmorHideHelmet"]),
    "gauntlets_light": (0x8, 0, ["ArmorLeatherGauntlets", "ArmorHideGauntlets"]),
}
NEW_KEYWORDS = {"lightsaber": "K2Lightsaber", "ranged": "K2Blaster", "melee": "K2VibroWeapon", "robe": "K2Robe"}


def edid_for(prefix: str, resref: str) -> str:
    return prefix + "".join(ch for ch in resref.title() if ch.isalnum())


def armor_slots(rec: Record) -> tuple[int, int] | None:
    """(biped slots, armour type) from BOD2 (SSE) or BODT (records inherited from Skyrim LE)."""
    b = rec.get("BOD2")
    if b and len(b) >= 8:
        return struct.unpack_from("<II", b)
    b = rec.get("BODT")
    if b and len(b) >= 12:
        slots, _flags, armor_type = struct.unpack_from("<IB3xI", b)
        return slots, armor_type
    return None


class Templates:
    def __init__(self, ms: MasterSet):
        self.ms = ms
        self.cache: dict[str, tuple] = {}

    def weapon(self, name: str):
        if name not in self.cache:
            anim, prefer = WEAPON_TEMPLATES[name]
            self.cache[name] = self.ms.weapon_by_anim(anim, prefer)
        return self.cache[name]

    def armor(self, name: str):
        if name not in self.cache:
            slot, armor_type, prefer = ARMOR_TEMPLATES[name]
            hit = None
            for e in prefer:
                h = self.ms.find(e)
                if h and h[1].sig == "ARMO":
                    hit = h
                    break
            if hit is None:
                for gid, rec, pf in self.ms.records("ARMO"):
                    s = armor_slots(rec)
                    if s and s[0] == slot and s[1] == armor_type and rec.get("MODL") and not rec.get("EITM") \
                            and not rec.get("TNAM") and not rec.flags & 0x4:
                        hit = (gid, rec, pf)
                        break
            if hit is None:
                raise KeyError(f"no vanilla armour for template {name}")
            self.cache[name] = hit
        return self.cache[name]

    def bolt(self):
        if "bolt" not in self.cache:
            best = None
            for gid, rec, pf in self.ms.records("AMMO"):
                d = rec.get("DATA") or b""
                flags = struct.unpack_from("<I", d, 4)[0] if len(d) >= 8 else 0
                if flags & 0x2 or flags & 0x4:  # non-playable, or an arrow ("Non-Bolt")
                    continue
                if best is None or "steel" in rec.edid.lower():
                    best = (gid, rec, pf)
            if best is None:
                raise KeyError("no crossbow bolt in the masters (is Dawnguard.esm loaded?)")
            self.cache["bolt"] = best
        return self.cache["bolt"]

    def container(self):
        if "cont" not in self.cache:
            hit = None
            for gid, rec, pf in self.ms.records("CONT"):
                model = (rec.get("MODL") or b"").lower()
                if b"chest" in model or b"footlocker" in model:
                    hit = (gid, rec, pf)
                    if b"footlocker" in model:
                        break
            if hit is None:
                raise KeyError("no vanilla chest container found")
            self.cache["cont"] = hit
        return self.cache["cont"]


def _desc(item: dict) -> str:
    lines = [item.get("description", "").strip()]
    props = [p["text"] for p in item.get("properties", []) if p.get("text")]
    if props:
        lines.append("KOTOR properties: " + "; ".join(props))
    return "\n".join(l for l in lines if l)[:2000]


def _keywords(rec: Record, kw: list[int]):
    if kw:
        rec.add("KSIZ", struct.pack("<I", len(kw)))
        rec.add("KWDA", struct.pack(f"<{len(kw)}I", *kw))


def dedupe(items: list[dict]) -> list[dict]:
    """Many KOTOR templates are copies (same name, base item and properties); keep one of each."""
    seen = {}
    for it in items:
        key = (it["name"].strip().lower(), it["base_item"], tuple(it["dice"]), it["damage_bonus_avg"],
               it["ac_bonus"], tuple(p["text"] for p in it["properties"]), it.get("colour"))
        if key not in seen or it["source"].startswith("override"):
            seen[key] = it
    return list(seen.values())


def usable(it: dict) -> bool:
    name = it.get("name", "").strip()
    return bool(name) and not name.lower().startswith(("error", "bad strref", "deleted", "do not use"))


def build(catalog: dict, ms: MasterSet, out_dir: str | Path, *, esl: bool = True, author: str = "",
          meshes: Path | None = None) -> dict:
    out_dir = Path(out_dir)
    items = [it for it in catalog["items"] if usable(it)]
    weapons = dedupe([it for it in items if stats.archetype_key(it)])
    armors = dedupe([it for it in items if stats.armor_key(it)])
    if esl and len(weapons) + len(armors) + len(NEW_KEYWORDS) + 3 > 2048:
        esl = False

    plugin = Plugin(PLUGIN_NAME, ms.masters, esl=esl, author=author or "kotor2skyrim",
                    description="KOTOR 2 weapons and armour with Skyrim real-time combat. Converted locally "
                                "from the user's own KOTOR 2 install; not for redistribution.")
    t = Templates(ms)
    kw = {k: plugin.new_record("KYWD", v).add("CNAM", struct.pack("<4B", 255, 255, 255, 0)).formid
          for k, v in NEW_KEYWORDS.items()}

    # Power cells: the blasters' ammo, a playable bolt that keeps the vanilla bolt's projectile for now.
    bgid, brec, bpf = t.bolt()
    cell = plugin.new_record("AMMO", "K2PowerCell")
    ms.copy_fields(brec, bpf, plugin, ["OBND"], cell)
    cell.add("FULL", zstring("Power Cell"))
    ms.copy_fields(brec, bpf, plugin, ["MODL", "MODT", "YNAM", "ZNAM"], cell)
    cell.add("DESC", zstring("A blaster power cell."))
    _keywords(cell, ms.keyword_ids(brec, bpf, plugin))
    proj = struct.unpack_from("<I", brec.get("DATA"), 0)[0]
    cell.add("DATA", struct.pack("<IIfIf", ms.remap(proj, bpf, plugin), 0, 0.0, 1, 0.0))

    wrng = stats.ranges(weapons, stats.archetype_key, stats.weapon_power)
    arng = stats.ranges(armors, stats.armor_key, stats.armor_power)
    mapping = {}

    for it in weapons:
        s = stats.weapon_stats(it, wrng)
        _gid, src, spf = t.weapon(s["template"])
        r = plugin.new_record("WEAP", edid_for("K2W_", it["resref"]))
        ms.copy_fields(src, spf, plugin, ["OBND"], r)
        name = it["name"]
        if it["class"] == "lightsaber" and it.get("colour") and it["colour"] not in name.lower():
            name = f"{name} ({it['colour']})"
        r.add("FULL", zstring(name))
        model = item_model(it)
        own_mesh = bool(meshes and model and (meshes / f"{model}.nif").exists())
        if own_mesh:  # the converted KOTOR model; the template's textures and 1st-person object don't fit it
            r.add("MODL", zstring(f"kotor2\\{model}.nif"))
        else:
            ms.copy_fields(src, spf, plugin, ["MODL", "MODT"], r)
        ms.copy_fields(src, spf, plugin, ["ETYP", "BIDS", "BAMT", "YNAM", "ZNAM"], r)
        _keywords(r, ms.keyword_ids(src, spf, plugin) + [kw[it["class"]]])
        r.add("DESC", zstring(_desc(it)))
        ms.copy_fields(src, spf, plugin, ["INAM"] + ([] if own_mesh else ["WNAM"]) +
                       ["SNAM", "XNAM", "NAM7", "TNAM", "UNAM", "NAM9", "NAM8"], r)
        r.add("DATA", struct.pack("<IfH", s["value"], s["weight"], s["damage"]))
        dnam = bytearray(src.get("DNAM"))
        struct.pack_into("<ff", dnam, 4, s["speed"], s["reach"])
        flags = struct.unpack_from("<H", dnam, 12)[0]
        flags = (flags | 0x1) if s["ignores_resistance"] else (flags & ~0x1)
        struct.pack_into("<H", dnam, 12, flags)
        if s["stagger"]:
            struct.pack_into("<f", dnam, 96, s["stagger"])
        r.add("DNAM", bytes(dnam))
        crdt = bytearray(src.get("CRDT") or bytes(24))
        if len(crdt) >= 20:
            struct.pack_into("<H", crdt, 0, s["crit_damage"])
            effect = struct.unpack_from("<I", crdt, 16)[0]
            struct.pack_into("<I", crdt, 16, ms.remap(effect, spf, plugin))
        r.add("CRDT", bytes(crdt))
        if src.get("VNAM"):
            r.add("VNAM", src.get("VNAM"))
        mapping[it["resref"]] = {"edid": r.edid, "formid": f"{r.formid:08X}", "name": name, "sig": "WEAP",
                                 "model": model, "own_mesh": own_mesh, **s}

    for it in armors:
        s = stats.armor_stats(it, arng)
        r = plugin.new_record("ARMO", edid_for("K2A_", it["resref"]))
        src = spf = None
        if s["template"]:
            _gid, src, spf = t.armor(s["template"])
            ms.copy_fields(src, spf, plugin, ["OBND"], r)
        else:
            r.add("OBND", bytes(12))
        r.add("FULL", zstring(it["name"]))
        if src is not None:
            ms.copy_fields(src, spf, plugin, ["MOD2", "MO2T", "MOD4", "MO4T"], r)
        r.add("BOD2", struct.pack("<II", s["slot"], s["armor_type"]))
        if src is not None:
            ms.copy_fields(src, spf, plugin, ["YNAM", "ZNAM", "ETYP", "BIDS", "BAMT", "RNAM"], r)
            keywords = ms.keyword_ids(src, spf, plugin)
        else:
            keywords = []
        if it["class"] == "robe":
            keywords.append(kw["robe"])
        _keywords(r, keywords)
        r.add("DESC", zstring(_desc(it)))
        if src is not None:
            ms.copy_fields(src, spf, plugin, ["MODL"], r)  # the armature (ARMA) list
        r.add("DATA", struct.pack("<if", s["value"], s["weight"]))
        r.add("DNAM", struct.pack("<i", s["rating"] * 100))
        mapping[it["resref"]] = {"edid": r.edid, "formid": f"{r.formid:08X}", "name": it["name"], "sig": "ARMO", **s}

    # The footlocker: one of everything, and power cells.
    cgid, crec, cpf = t.container()
    box = plugin.new_record("CONT", "K2Footlocker")
    ms.copy_fields(crec, cpf, plugin, ["OBND"], box)
    box.add("FULL", zstring("KotOR 2 Footlocker"))
    ms.copy_fields(crec, cpf, plugin, ["MODL", "MODT"], box)
    contents = [(cell.formid, 500)] + [(int(m["formid"], 16), 1) for m in mapping.values()]
    box.add("COCT", struct.pack("<I", len(contents)))
    for fid, n in contents:
        box.add("CNTO", struct.pack("<Ii", fid, n))
    box.add("DATA", struct.pack("<Bf", 0, 0.0))
    ms.copy_fields(crec, cpf, plugin, ["SNAM", "QNAM"], box)

    path = plugin.write(out_dir / PLUGIN_NAME)
    summary = {
        "plugin": str(path),
        "esl": esl,
        "masters": plugin.masters,
        "weapons": len(weapons),
        "armour": len(armors),
        "footlocker": {"edid": box.edid, "formid": f"{box.formid:08X}"},
        "power_cell": {"edid": cell.edid, "formid": f"{cell.formid:08X}"},
        "templates": {k: v[1].edid for k, v in t.cache.items()},
        "items": mapping,
    }
    (out_dir / "arsenal.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def console_batch(summary: dict, prefix: str) -> str:
    """Lines for Skyrim's `bat` command. `prefix` is the plugin's in-game ID prefix as the console shows it:
    'FE001' for the second light plugin (FormIDs FE001800...), or two hex digits like '5A' for a regular one."""
    prefix = prefix.upper()

    def fid(local: str) -> str:
        obj = int(local, 16) & (0xFFF if summary["esl"] else 0xFFFFFF)
        return f"{prefix}{obj:03X}" if summary["esl"] else f"{prefix}{obj:06X}"

    return "\n".join([f"player.placeatme {fid(summary['footlocker']['formid'])} 1", ""])
