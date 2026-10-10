"""Read files out of the user's Skyrim SE archives (BSA version 105, LZ4 frames), so the converter can use
vanilla meshes as references and templates without anything being extracted by hand.

Layout (UESP "Skyrim Mod:Archive File Format"): 36-byte header; folder records of 24 bytes (hash u64,
count u32, pad u32, offset u64); per folder a bstring name then 16-byte file records (hash u64, size u32,
offset u32); then the zero-terminated file names. A file's size bit 0x40000000 flips the archive's
"compressed" default; compressed data is the original size (u32) then an LZ4 frame. With archive flag
0x100 each file's data starts with its full path as a bstring.
"""
from __future__ import annotations

import struct
from pathlib import Path

ARCHIVE_COMPRESSED, ARCHIVE_EMBED_NAMES = 0x4, 0x100


class BSA:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.files: dict[str, tuple[int, int, bool]] = {}
        with open(self.path, "rb") as f:
            magic, version, _, flags, nfolders, nfiles, _, _, _, _ = struct.unpack("<4sIIIIIIIHH", f.read(36))
            if magic != b"BSA\0" or version != 105:
                raise ValueError(f"{self.path.name}: not an SSE BSA (version {version})")
            self.flags = flags
            folders = [struct.unpack("<QIIQ", f.read(24)) for _ in range(nfolders)]
            records = []
            for _, count, _, _ in folders:
                n = f.read(1)[0]
                folder = f.read(n)[:-1].decode("latin-1").lower()
                for _ in range(count):
                    _, size, offset = struct.unpack("<QII", f.read(16))
                    records.append((folder, size, offset))
            names = f.read().split(b"\0")
        for (folder, size, offset), name in zip(records, names):
            compressed = bool(flags & ARCHIVE_COMPRESSED) ^ bool(size & 0x40000000)
            self.files[f"{folder}\\{name.decode('latin-1').lower()}"] = (offset, size & 0x3FFFFFFF, compressed)

    def read(self, name: str) -> bytes:
        offset, size, compressed = self.files[name.lower().replace("/", "\\")]
        with open(self.path, "rb") as f:
            f.seek(offset)
            data = f.read(size)
        if self.flags & ARCHIVE_EMBED_NAMES:
            data = data[1 + data[0]:]
        if compressed:
            import lz4.frame
            data = lz4.frame.decompress(data[4:])
        return data


def find(data_dir: str | Path, name: str) -> bytes | None:
    """A file by its Data-relative path: loose first, then every BSA in the Data folder."""
    data_dir = Path(data_dir)
    loose = data_dir / name
    if loose.exists():
        return loose.read_bytes()
    key = name.lower().replace("/", "\\")
    for p in sorted(data_dir.glob("*.bsa")):
        try:
            b = BSA(p)
        except ValueError:
            continue
        if key in b.files:
            return b.read(key)
    return None
