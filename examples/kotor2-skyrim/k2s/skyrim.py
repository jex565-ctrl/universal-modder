"""The user's own Skyrim SE masters as the source of placeholder models, sounds, keywords and animations.

Nothing from Skyrim is copied into this repository and no vanilla FormID is hard-coded: the converter reads
`Skyrim.esm`, `Update.esm` and `Dawnguard.esm` from the user's `Data` folder, finds vanilla records by
EditorID (or by structure, e.g. "a playable crossbow"), and references them from the new plugin. The
plugin then works with vanilla meshes until converted KOTOR meshes replace them.

A record's identity across files is (defining file, object ID): FormID 0xIIOOOOOO in file F means object
OOOOOO of F's master II, or of F itself when II == len(F.masters).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .esp import Plugin, PluginFile, Record, Subrecord, read_plugin

DEFAULT_MASTERS = ["Skyrim.esm", "Update.esm", "Dawnguard.esm"]
TEMPLATE_TYPES = {"KYWD", "WEAP", "ARMO", "AMMO", "PROJ", "EQUP", "CONT", "SNDR", "ARMA", "MISC", "LIGH"}

# Where FormIDs sit inside the subrecords the converter copies from vanilla templates, per record type.
# A list gives byte offsets of single FormIDs; "array" means the whole subrecord is a FormID array.
FORMID_FIELDS: dict[str, dict[str, object]] = {
    "WEAP": {sig: [0] for sig in ("ETYP", "BIDS", "BAMT", "YNAM", "ZNAM", "INAM", "WNAM", "SNAM", "XNAM",
                                  "NAM7", "TNAM", "UNAM", "NAM9", "NAM8", "EITM")} | {"KWDA": "array", "CRDT": [16]},
    "ARMO": {sig: [0] for sig in ("ETYP", "BIDS", "BAMT", "YNAM", "ZNAM", "RNAM", "MODL", "EITM")}
            | {"KWDA": "array"},
    "AMMO": {"YNAM": [0], "ZNAM": [0], "KWDA": "array", "DATA": [0]},
    "CONT": {"SNAM": [0], "QNAM": [0]},
}


@dataclass(frozen=True)
class GlobalID:
    file: str      # lower-case file name that defines the record
    object_id: int


class MasterSet:
    """The vanilla masters, read once, with lookups that return FormIDs valid inside a new plugin."""

    def __init__(self, data_dir: str | Path, masters: list[str] | None = None, types: set[str] | None = None):
        self.data_dir = Path(data_dir)
        self.masters = list(masters or DEFAULT_MASTERS)
        self.files: list[PluginFile] = []
        for m in self.masters:
            path = _find_case_insensitive(self.data_dir, m)
            if path is None:
                raise FileNotFoundError(f"{m} not found in {self.data_dir} (point --skyrim-data at Skyrim's Data folder)")
            self.files.append(read_plugin(path, types or TEMPLATE_TYPES))
        # EDID -> (global id, record, file); later masters override earlier ones (Update.esm wins).
        self.by_edid: dict[str, tuple[GlobalID, Record, PluginFile]] = {}
        self.by_gid: dict[GlobalID, tuple[Record, PluginFile]] = {}
        for pf in self.files:
            for rec in pf.all_records():
                gid = self.global_id(pf, rec.formid)
                self.by_gid[gid] = (rec, pf)
                if rec.edid:
                    self.by_edid[rec.edid.lower()] = (gid, rec, pf)

    # ------------------------------------------------------------ FormID algebra
    def global_id(self, pf: PluginFile, formid: int) -> GlobalID:
        idx = formid >> 24
        name = pf.masters[idx] if idx < len(pf.masters) else pf.name
        return GlobalID(name.lower(), formid & 0xFFFFFF)

    def local_formid(self, gid: GlobalID, plugin: Plugin) -> int:
        lower = [m.lower() for m in plugin.masters]
        if gid.file not in lower:
            raise KeyError(f"{gid.file} is not a master of {plugin.name}")
        return (lower.index(gid.file) << 24) | gid.object_id

    def remap(self, formid: int, pf: PluginFile, plugin: Plugin) -> int:
        if formid == 0:
            return 0
        return self.local_formid(self.global_id(pf, formid), plugin)

    # ------------------------------------------------------------ lookups
    def find(self, edid: str) -> tuple[GlobalID, Record, PluginFile] | None:
        return self.by_edid.get(edid.lower())

    def formid(self, edid: str, plugin: Plugin) -> int:
        hit = self.find(edid)
        if hit is None:
            raise KeyError(f"no vanilla record with EditorID {edid!r} in {', '.join(self.masters)}")
        return self.local_formid(hit[0], plugin)

    def first(self, edids: list[str], sig: str) -> tuple[GlobalID, Record, PluginFile]:
        """The first EditorID in `edids` that exists with record type `sig`."""
        for e in edids:
            hit = self.find(e)
            if hit and hit[1].sig == sig:
                return hit
        raise KeyError(f"none of {edids} found as {sig} in {', '.join(self.masters)}")

    def records(self, sig: str):
        seen = set()
        for pf in reversed(self.files):  # overrides first
            for rec in pf.records.get(sig, []):
                gid = self.global_id(pf, rec.formid)
                if gid not in seen:
                    seen.add(gid)
                    yield gid, rec, pf

    def weapon_by_anim(self, anim_type: int, prefer: list[str] = ()) -> tuple[GlobalID, Record, PluginFile]:
        """A playable, unenchanted vanilla weapon with DNAM animation type `anim_type` (9 = crossbow)."""
        for e in prefer:
            hit = self.find(e)
            if hit and hit[1].sig == "WEAP" and weapon_anim(hit[1]) == anim_type:
                return hit
        for gid, rec, pf in self.records("WEAP"):
            if weapon_anim(rec) == anim_type and not rec.get("EITM") and not rec.get("CNAM") and rec.get("MODL") \
                    and not rec.flags & 0x4:
                return gid, rec, pf
        raise KeyError(f"no vanilla weapon with animation type {anim_type}")

    # ------------------------------------------------------------ copying
    def copy_fields(self, src: Record, pf: PluginFile, plugin: Plugin, sigs: list[str], dst: Record):
        """Append `src`'s subrecords named in `sigs` (in `src` order) to `dst`, FormIDs remapped."""
        layout = FORMID_FIELDS.get(src.sig, {})
        for sub in src.subrecords:
            if sub.sig not in sigs:
                continue
            data = bytearray(sub.data)
            where = layout.get(sub.sig)
            offsets = range(0, len(data) - 3, 4) if where == "array" else (where or [])
            for off in offsets:
                if off + 4 <= len(data):
                    fid = struct.unpack_from("<I", data, off)[0]
                    struct.pack_into("<I", data, off, self.remap(fid, pf, plugin))
            dst.subrecords.append(Subrecord(sub.sig, bytes(data)))

    def keyword_ids(self, src: Record, pf: PluginFile, plugin: Plugin) -> list[int]:
        kw = src.get("KWDA") or b""
        return [self.remap(f, pf, plugin) for f in struct.unpack(f"<{len(kw) // 4}I", kw)]


def weapon_anim(rec: Record) -> int | None:
    d = rec.get("DNAM")
    return d[0] if d else None


def _find_case_insensitive(folder: Path, name: str) -> Path | None:
    direct = folder / name
    if direct.exists():
        return direct
    if folder.is_dir():
        for p in folder.iterdir():
            if p.name.lower() == name.lower():
                return p
    return None
