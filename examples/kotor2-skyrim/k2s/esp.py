"""Skyrim Special Edition plugin (.esp/.esm/.esl) writer and reader.

Only what the converter needs, written from xEdit's record definitions (TES5Edit `Core/wbDefinitionsTES5.pas`)
and the layout in `knowledge/techniques/bethesda-plugin-record-format-esm-esp-esl.md`:

- 24-byte record and group headers, subrecords `sig + u16 size + data`, the `XXXX` escape for big ones;
- top-level groups in the order the Creation Kit writes them;
- a reader that walks top-level groups of the requested types only (skipping the rest by size), inflates
  compressed records (flag 0x40000), and keeps subrecords raw.

Plugins written here are not localized: strings are inline, cp1252 (Skyrim SE's own encoding for
non-localized plugins).
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

FORM_VERSION_SSE = 44
HEDR_VERSION_SSE = 1.71

FLAG_ESM = 0x1
FLAG_LOCALIZED = 0x80
FLAG_ESL = 0x200
FLAG_COMPRESSED = 0x40000

# Top-level group order as the Creation Kit writes Skyrim plugins.
GROUP_ORDER = (
    "GMST KYWD LCRT AACT TXST GLOB CLAS FACT HDPT HAIR EYES RACE SOUN ASPC MGEF SCPT LTEX ENCH SPEL SCRL ACTI "
    "TACT ARMO BOOK CONT DOOR INGR LIGH MISC APPA STAT SCOL MSTT PWAT GRAS TREE CLDC FLOR FURN WEAP AMMO NPC_ "
    "LVLN KEYM ALCH IDLM COBJ PROJ HAZD SLGM LVLI WTHR CLMT SPGD RFCT REGN NAVI CELL WRLD DIAL QUST IDLE PACK "
    "CSTY LSCR LVSP ANIO WATR EFSH EXPL DEBR IMGS IMAD FLST PERK BPTD ADDN AVIF CAMS CPTH VTYP MATT IPCT IPDS "
    "ARMA ECZN LCTN MESG RGDL DOBJ LGTM MUSC FSTP FSTS SMBN SMQN SMEN DLBR MUST DLVW WOOP SHOU EQUP RELA SCEN "
    "ASTP OTFT ARTO MATO MOVT SNDR DUAL SNCT SOPM COLL CLFM REVB"
).split()

ENCODING = "cp1252"


def zstring(text: str) -> bytes:
    """A null-terminated string as Skyrim stores it. Characters cp1252 lacks become '?'."""
    return text.encode(ENCODING, errors="replace") + b"\0"


def read_zstring(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode(ENCODING, errors="replace")


@dataclass
class Subrecord:
    sig: str
    data: bytes

    def to_bytes(self) -> bytes:
        sig = self.sig.encode("ascii")
        if len(sig) != 4:
            raise ValueError(f"subrecord signature must be 4 characters: {self.sig!r}")
        if len(self.data) > 0xFFFF:
            # The XXXX escape: real size first, then the subrecord with size 0.
            return b"XXXX" + struct.pack("<HI", 4, len(self.data)) + sig + struct.pack("<H", 0) + self.data
        return sig + struct.pack("<H", len(self.data)) + self.data


@dataclass
class Record:
    sig: str
    formid: int
    subrecords: list[Subrecord] = field(default_factory=list)
    flags: int = 0
    version: int = FORM_VERSION_SSE

    def add(self, sig: str, data: bytes) -> "Record":
        self.subrecords.append(Subrecord(sig, data))
        return self

    def get(self, sig: str) -> bytes | None:
        for s in self.subrecords:
            if s.sig == sig:
                return s.data
        return None

    def get_all(self, sig: str) -> list[bytes]:
        return [s.data for s in self.subrecords if s.sig == sig]

    @property
    def edid(self) -> str:
        d = self.get("EDID")
        return read_zstring(d) if d is not None else ""

    def to_bytes(self) -> bytes:
        body = b"".join(s.to_bytes() for s in self.subrecords)
        flags = self.flags & ~FLAG_COMPRESSED  # never written compressed
        return (self.sig.encode("ascii") + struct.pack("<IIIIHH", len(body), flags, self.formid, 0, self.version, 0)
                + body)


def _group(label: bytes, group_type: int, contents: bytes) -> bytes:
    return b"GRUP" + struct.pack("<I", 24 + len(contents)) + label + struct.pack("<iII", group_type, 0, 0) + contents


class Plugin:
    """A new plugin. Masters are file names in load order; new records get FormIDs from 0x800 up.

    A FormID's top byte indexes this plugin's master list; the index equal to len(masters) is this
    plugin itself. With `esl=True` the light flag is set, which allows object IDs 0x800-0xFFF only.
    """

    def __init__(self, name: str, masters: list[str], *, esl: bool = False, esm: bool = False,
                 author: str = "", description: str = ""):
        self.name = name
        self.masters = list(masters)
        self.esl = esl
        self.esm = esm
        self.author = author
        self.description = description
        self.records: list[Record] = []
        self._next = 0x800

    @property
    def self_index(self) -> int:
        return len(self.masters)

    def new_formid(self) -> int:
        oid = self._next
        self._next += 1
        if self.esl and oid > 0xFFF:
            raise OverflowError("a light (ESL) plugin holds 2048 new records at most; build without esl")
        if oid > 0xFFFFFF:
            raise OverflowError("out of object IDs")
        return (self.self_index << 24) | oid

    def add(self, record: Record) -> Record:
        self.records.append(record)
        return record

    def new_record(self, sig: str, edid: str, flags: int = 0) -> Record:
        r = Record(sig, self.new_formid(), flags=flags)
        r.add("EDID", zstring(edid))
        return self.add(r)

    def header(self, num_records: int) -> bytes:
        rec = Record("TES4", 0, flags=(FLAG_ESM if self.esm else 0) | (FLAG_ESL if self.esl else 0))
        rec.add("HEDR", struct.pack("<fII", HEDR_VERSION_SSE, num_records, self._next))
        rec.add("CNAM", zstring(self.author or "kotor2skyrim"))
        if self.description:
            rec.add("SNAM", zstring(self.description))
        for m in self.masters:
            rec.add("MAST", zstring(m))
            rec.add("DATA", struct.pack("<Q", 0))
        rec.add("INTV", struct.pack("<I", 1))
        return rec.to_bytes()

    def to_bytes(self) -> bytes:
        by_type: dict[str, list[Record]] = {}
        for r in self.records:
            by_type.setdefault(r.sig, []).append(r)
        unknown = set(by_type) - set(GROUP_ORDER)
        if unknown:
            raise ValueError(f"no top-level group order known for {sorted(unknown)}")
        groups = []
        count = 0
        for sig in GROUP_ORDER:
            recs = by_type.get(sig)
            if not recs:
                continue
            if sig in ("CELL", "WRLD", "DIAL"):
                raise NotImplementedError(f"{sig} needs child groups; write it with a dedicated builder")
            groups.append(_group(sig.encode("ascii"), 0, b"".join(r.to_bytes() for r in recs)))
            count += 1 + len(recs)  # HEDR counts records and groups
        return self.header(count) + b"".join(groups)

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.to_bytes())
        return p


# ---------------------------------------------------------------- reading

def parse_subrecords(data: bytes) -> list[Subrecord]:
    out = []
    i = 0
    big = None
    while i + 6 <= len(data):
        sig = data[i:i + 4].decode("ascii", errors="replace")
        size = struct.unpack_from("<H", data, i + 4)[0]
        i += 6
        if sig == "XXXX":
            big = struct.unpack_from("<I", data, i)[0]
            i += size
            continue
        if big is not None:
            size, big = big, None
        out.append(Subrecord(sig, data[i:i + size]))
        i += size
    return out


@dataclass
class PluginFile:
    """A plugin read from disk: its header facts and the records of the requested top-level types."""
    path: Path
    flags: int
    masters: list[str]
    records: dict[str, list[Record]]
    num_records: int = 0

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def localized(self) -> bool:
        return bool(self.flags & FLAG_LOCALIZED)

    def all_records(self):
        for recs in self.records.values():
            yield from recs


def _read_record(buf: bytes, pos: int) -> tuple[Record, int]:
    sig = buf[pos:pos + 4].decode("ascii", errors="replace")
    size, flags, formid, _vc1, version, _vc2 = struct.unpack_from("<IIIIHH", buf, pos + 4)
    data = buf[pos + 24:pos + 24 + size]
    if flags & FLAG_COMPRESSED:
        data = zlib.decompress(data[4:])
    return Record(sig, formid, parse_subrecords(data), flags=flags & ~FLAG_COMPRESSED, version=version), pos + 24 + size


def _walk_group(buf: bytes, start: int, end: int, out: list[Record]):
    pos = start
    while pos < end:
        if buf[pos:pos + 4] == b"GRUP":
            gsize = struct.unpack_from("<I", buf, pos + 4)[0]
            _walk_group(buf, pos + 24, pos + gsize, out)
            pos += gsize
        else:
            rec, pos = _read_record(buf, pos)
            out.append(rec)


def read_plugin(path: str | Path, types: set[str] | None = None) -> PluginFile:
    """Read a plugin. `types` limits which top-level groups are parsed (None = all)."""
    p = Path(path)
    buf = p.read_bytes()
    if buf[:4] != b"TES4":
        raise ValueError(f"{p}: not a Skyrim plugin (no TES4 header)")
    header, pos = _read_record(buf, 0)
    masters = [read_zstring(d) for d in header.get_all("MAST")]
    hedr = header.get("HEDR")
    num = struct.unpack_from("<fII", hedr)[1] if hedr and len(hedr) >= 12 else 0
    records: dict[str, list[Record]] = {}
    while pos < len(buf):
        if buf[pos:pos + 4] != b"GRUP":
            raise ValueError(f"{p}: expected a top-level GRUP at offset {pos}")
        gsize, label, gtype = struct.unpack_from("<I4si", buf, pos + 4)
        sig = label.decode("ascii", errors="replace")
        if gtype == 0 and (types is None or sig in types):
            out: list[Record] = []
            _walk_group(buf, pos + 24, pos + gsize, out)
            records.setdefault(sig, []).extend(r for r in out if r.sig == sig or types is None)
        pos += gsize
    return PluginFile(p, header.flags, masters, records, num)
