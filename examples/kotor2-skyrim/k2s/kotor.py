"""Read the user's own KOTOR 2 install through PyKotor (https://pypi.org/project/pykotor/, LGPL-3.0).

PyKotor parses KEY/BIF, ERF/RIM/MOD, GFF, 2DA, TLK, LYT, BWM and MDL. This module adds only:
- one resource index with the game's own priority: override > modules > chitin (BIFs);
- GFF structs turned into plain Python data (dicts, lists, str, int), so the rest of the converter never
  depends on PyKotor's object model;
- small 2DA and TLK helpers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

# PyKotor logs every case-insensitive path probe at DEBUG through its own handlers.
logging.disable(logging.INFO)
logging.getLogger().setLevel(logging.WARNING)
for _name in ("pykotor", "loggerplus", "root"):
    logging.getLogger(_name).setLevel(logging.WARNING)

from pykotor.common.language import LocalizedString  # noqa: E402
from pykotor.common.misc import ResRef  # noqa: E402
from pykotor.extract.installation import Installation  # noqa: E402
from pykotor.resource.formats.gff import GFFList, GFFStruct, read_gff  # noqa: E402
from pykotor.resource.formats.twoda import read_2da  # noqa: E402

PRIORITY = {"override": 0, "module": 1, "texturepack": 2, "chitin": 3}


@dataclass
class Res:
    resname: str          # lower-case resref
    ext: str              # lower-case extension: uti, dlg, 2da, mdl ...
    source: str           # "override", "module", "chitin"
    container: str        # module file name, BIF path, or override folder
    _file: object         # PyKotor FileResource

    def data(self) -> bytes:
        return self._file.data()


class K2Install:
    """A KOTOR 2 installation (Steam/GOG, the 2021 Aspyr update or the original 2005 PC release)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not (self.path / "chitin.key").exists() and not any(p.name.lower() == "chitin.key" for p in self.path.glob("*")):
            raise FileNotFoundError(f"{self.path} has no chitin.key; pass the folder that holds swkotor2.exe")
        self.inst = Installation(self.path)
        self.index: dict[tuple[str, str], Res] = {}
        self.by_module: dict[str, list[Res]] = {}
        for f in self.inst.chitin_resources():
            self._add(f, "chitin", str(getattr(f, "filepath", lambda: "")()))
        for mod in self.inst.modules_list():
            for f in self.inst.module_resources(mod):
                res = self._add(f, "module", mod)
                self.by_module.setdefault(mod.lower(), []).append(res)
        # swpc_tex_tpa (high), tpb (medium) and tpc (low) hold the same names at three sizes; equal priority
        # means the last one added wins, so add them low to high.
        for pack in sorted(self.inst.texturepacks_list(), key=lambda n: str(n).lower(), reverse=True):
            for f in self.inst.texturepack_resources(pack):
                self._add(f, "texturepack", pack)
        for f in self.inst.override_resources():
            self._add(f, "override", "override")
        self._tlk = None
        self._twoda: dict[str, list[dict[str, str]] | None] = {}

    def _add(self, f, source: str, container: str) -> Res:
        res = Res(f.resname().lower(), f.restype().extension.lower(), source, container, f)
        key = (res.resname, res.ext)
        old = self.index.get(key)
        if old is None or PRIORITY[source] <= PRIORITY[old.source]:
            self.index[key] = res
        return res

    # ------------------------------------------------------------ lookups
    def get(self, resname: str, ext: str) -> Res | None:
        return self.index.get((resname.lower(), ext.lower()))

    def all(self, ext: str) -> list[Res]:
        return sorted((r for (n, e), r in self.index.items() if e == ext.lower()), key=lambda r: r.resname)

    def gff(self, resname: str, ext: str) -> dict | None:
        r = self.get(resname, ext)
        return gff_dict(r.data(), self) if r else None

    def string(self, strref: int) -> str:
        if strref is None or strref < 0:
            return ""
        if self._tlk is None:
            self._tlk = self.inst.talktable()
        try:
            return self._tlk.string(strref) or ""
        except Exception:  # noqa: BLE001 - a bad strref in one item shouldn't stop a batch
            return ""

    def sound_of(self, strref: int) -> str:
        if strref is None or strref < 0:
            return ""
        if self._tlk is None:
            self._tlk = self.inst.talktable()
        try:
            return str(self._tlk.sound(strref) or "")
        except Exception:  # noqa: BLE001
            return ""

    def twoda(self, name: str) -> list[dict[str, str]] | None:
        """Rows of a 2DA as dicts keyed by lower-case column, plus '_row' (index) and '_label'."""
        name = name.lower()
        if name not in self._twoda:
            r = self.get(name, "2da")
            if r is None:
                self._twoda[name] = None
            else:
                t = read_2da(r.data())
                cols = t.get_headers()
                rows = []
                for i, row in enumerate(t):
                    d = {c.lower(): (row.get_string(c) or "") for c in cols}
                    d["_row"] = str(i)
                    d["_label"] = row.label()
                    rows.append(d)
                self._twoda[name] = rows
        return self._twoda[name]


# ---------------------------------------------------------------- GFF → plain data

def locstring(value: LocalizedString, install: K2Install | None) -> dict:
    """{'strref': n, 'text': '...'}: inline English text wins, then dialog.tlk."""
    strref = getattr(value, "stringref", -1)
    text = ""
    try:
        for _lang, _gender, s in value:
            if s:
                text = s
                break
    except TypeError:
        pass
    if not text and install is not None and strref is not None and strref >= 0:
        text = install.string(strref)
    return {"strref": strref, "text": text}


def struct_dict(s: GFFStruct, install: K2Install | None = None) -> dict:
    out = {}
    for label, _ftype, value in s:
        out[label] = _value(value, install)
    return out


def _value(v, install):
    if isinstance(v, GFFStruct):
        return struct_dict(v, install)
    if isinstance(v, GFFList):
        return [struct_dict(x, install) for x in v]
    if isinstance(v, LocalizedString):
        return locstring(v, install)
    if isinstance(v, ResRef):
        return str(v).lower()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, (int, float, str)) or v is None:
        return v
    # Vector3/Vector4 orientation values
    for attrs in (("x", "y", "z", "w"), ("x", "y", "z")):
        if all(hasattr(v, a) for a in attrs):
            return [float(getattr(v, a)) for a in attrs]
    return str(v)


def gff_dict(data: bytes, install: K2Install | None = None) -> dict:
    return struct_dict(read_gff(data).root, install)


def clean_text(text: str, player: str = "Exile") -> str:
    """Game text as a player should see it: designer tags like {x01} dropped, <FullName> (the player's name,
    which Skyrim item and topic text can't insert) replaced by the Exile's title."""
    import re
    text = re.sub(r"\{[^}]*\}", "", text or "")
    return re.sub(r"<FullName>", player, text, flags=re.I).strip()


def as_int(text, default: int = 0) -> int:
    """2DA cells: '' and '****' are empty; hex like '0x00030' is allowed."""
    if text is None:
        return default
    t = str(text).strip()
    if not t or t == "****":
        return default
    try:
        return int(t, 0) if t.lower().startswith("0x") else int(float(t))
    except ValueError:
        return default
