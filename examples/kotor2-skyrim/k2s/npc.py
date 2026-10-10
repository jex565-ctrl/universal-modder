"""KOTOR characters as Skyrim NPC_ records.

A Skyrim NPC's face is baked by the Creation Kit into per-NPC FaceGen files, which this converter can't
make. So each KOTOR character borrows a vanilla NPC as a traits template (TPLT with ACBS "Use Traits"):
race, sex, face, height and voice type come from that NPC; name, outfit, inventory, level and dialogue are
the KOTOR character's own. The vanilla record is copied (it carries every field the engine expects) and its
faction, AI package, crime and inventory fields are dropped.

The cast table chooses a look-alike per character; edit it freely.
"""
from __future__ import annotations

import struct

from .esp import Plugin, Record, Subrecord, zstring

USE_TRAITS = 0x0001
DROP = {"EDID", "FULL", "SHRT", "SNAM", "PKID", "CRIF", "COCT", "CNTO", "DOFT", "SOFT", "VMAD", "INAM", "TPLT"}

CAST = {
    # KOTOR tag: (vanilla traits NPC, outfit OTFT EditorID, Skyrim name)
    "kreia": ("IdgrodRavencrone", "GreybeardOutfitWithHat", "Kreia"),
    "atton": ("Brynjolf", None, "Atton Rand"),
}


def make_npc(plugin: Plugin, masters, tag: str, edid: str, name: str | None = None,
             outfit: str | None = None, items: list[tuple[int, int]] = (), level: int = 20) -> Record:
    traits_edid, default_outfit, default_name = CAST[tag]
    gid, src, pf = masters.first([traits_edid], "NPC_")
    rec = plugin.new_record("NPC_", edid)
    for s in src.subrecords:
        if s.sig in DROP:
            continue
        data = s.data
        if s.sig == "ACBS":
            b = bytearray(data)
            struct.pack_into("<I", b, 0, struct.unpack_from("<I", b, 0)[0] & ~0x80)  # not "PC level mult"
            struct.pack_into("<h", b, 8, level)
            struct.pack_into("<H", b, 18, USE_TRAITS)
            data = bytes(b)
        if s.sig in ("VTCK", "RNAM", "ATKR", "CNAM", "HCLF", "PNAM", "ZNAM"):
            fid = struct.unpack_from("<I", data, 0)[0]
            data = struct.pack("<I", masters.remap(fid, pf, plugin))
        rec.subrecords.append(Subrecord(s.sig, data))
        if s.sig == "ACBS":
            rec.subrecords.append(Subrecord("TPLT", struct.pack("<I", masters.local_formid(gid, plugin))))
    rec.subrecords.insert(_after(rec, "AIDT"), Subrecord("FULL", zstring(name or default_name)))
    if items:
        at = _after(rec, "ATKR") if rec.get("ATKR") else _after(rec, "RNAM")
        rec.subrecords.insert(at, Subrecord("COCT", struct.pack("<I", len(items))))
        for i, (fid, count) in enumerate(items):
            rec.subrecords.insert(at + 1 + i, Subrecord("CNTO", struct.pack("<Ii", fid, count)))
    o = outfit or default_outfit
    if o:
        rec.subrecords.insert(_after(rec, "NAM8"), Subrecord("DOFT", struct.pack("<I", masters.formid(o, plugin))))
    return rec


def _after(rec: Record, sig: str) -> int:
    idx = [i for i, s in enumerate(rec.subrecords) if s.sig == sig]
    return idx[-1] + 1 if idx else len(rec.subrecords)


def actor_ref(plugin: Plugin, base: int, pos, rot_z: float, edid: str | None = None) -> Record:
    r = Record("ACHR", plugin.new_formid())
    if edid:
        r.add("EDID", zstring(edid))
    r.add("NAME", struct.pack("<I", base))
    r.add("DATA", struct.pack("<6f", pos[0], pos[1], pos[2], 0.0, 0.0, rot_z))
    return r
