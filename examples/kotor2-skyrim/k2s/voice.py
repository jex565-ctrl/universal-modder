"""KOTOR 2's own voice acting → Skyrim voice files, keeping the original performances.

KOTOR 2 keeps voiced lines in `StreamVoice/<area>/<vo_resref>.wav`. Some carry an obfuscation header,
and some are MP3 inside a WAV wrapper; PyKotor's deobfuscation strips the header. A DLG line's `VO_ResRef`
names its file (dialog.tlk's sound resref is the fallback).

Skyrim plays a dialogue response from `Data/Sound/Voice/<plugin>/<voice type>/<name>.fuz`, where a .fuz is
`'FUZE' + u32 version (1) + u32 lip size + .lip + .xwm`. The pipeline:
1. `k2s voice` (here, any OS, needs ffmpeg): decode each line to 44.1 kHz 16-bit mono WAV in
   `voice/wav/<voice type>/`, plus `voice/manifest.json` (line text, dialogue, entry, speaker).
2. On Windows: xWMAEncode.exe (it ships with the Creation Kit) turns each WAV into .xwm, and the Creation
   Kit's "Generate lip files" (or the LipGen tool) makes .lip for lip sync; `encode_voice.bat` is written
   for this step.
3. `k2s fuz` packs xwm + lip into .fuz under the final names, once the dialogue plugin has given every
   line its INFO FormID (Skyrim's file name embeds it: `<quest>_<topic>_<INFO formid>_<response>.fuz`).
The audio stays on the user's machine; never upload it.
"""
from __future__ import annotations

import json
import struct
import subprocess
import tempfile
from pathlib import Path

FUZ_MAGIC = b"FUZE"


def index_voice(install_path: str | Path) -> dict[str, Path]:
    """vo resref (lower case) → audio file, for every file under StreamVoice / StreamWaves."""
    root = Path(install_path)
    out: dict[str, Path] = {}
    for d in root.iterdir() if root.is_dir() else ():
        if d.is_dir() and d.name.lower() in ("streamvoice", "streamwaves"):
            for f in d.rglob("*"):
                if f.suffix.lower() in (".wav", ".mp3") and f.is_file():
                    out.setdefault(f.stem.lower(), f)
    return out


def decode(path: Path) -> tuple[bytes, str]:
    """Strip KOTOR's audio wrapper: (clean bytes, 'wav' or 'mp3')."""
    from pykotor.resource.formats.wav import get_deobfuscation_result
    from pykotor.resource.formats.wav.wav_obfuscation import DeobfuscationResult

    raw = path.read_bytes()
    data, kind = get_deobfuscation_result(raw)
    if kind == DeobfuscationResult.MP3_IN_WAV or data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return data, "mp3"
    return data, "wav"


def to_skyrim_wav(data: bytes, kind: str, out: Path, ffmpeg: str = "ffmpeg") -> Path:
    """Any decodable audio → 44.1 kHz, 16-bit, mono PCM WAV (what xWMAEncode and Skyrim's lip tools want)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix="." + kind, delete=False) as tmp:
        tmp.write(data)
        src = tmp.name
    try:
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "44100", "-sample_fmt", "s16",
                        str(out)], check=True)
    finally:
        Path(src).unlink(missing_ok=True)
    return out


def pack_fuz(xwm: bytes, lip: bytes = b"") -> bytes:
    return FUZ_MAGIC + struct.pack("<II", 1, len(lip)) + lip + xwm


def unpack_fuz(data: bytes) -> tuple[bytes, bytes]:
    if data[:4] != FUZ_MAGIC:
        raise ValueError("not a .fuz file")
    _version, lip_size = struct.unpack_from("<II", data, 4)
    return data[12:12 + lip_size], data[12 + lip_size:]


def export(install_path: str | Path, characters: dict, out_dir: str | Path, *, ffmpeg: str = "ffmpeg",
           only: set[str] | None = None, limit: int | None = None) -> dict:
    """Decode every voiced line of every character (or the tags in `only`) into `out_dir/voice`."""
    out_dir = Path(out_dir) / "voice"
    files = index_voice(install_path)
    manifest = []
    missing = 0
    done = 0
    for ch in characters["characters"]:
        if only and ch["tag"] not in only:
            continue
        for line in ch["lines"]:
            vo = (line.get("vo") or line.get("sound") or "").lower()
            if not vo:
                continue
            src = files.get(vo)
            if src is None:
                missing += 1
                continue
            wav = out_dir / "wav" / ch["voice_type"] / f"{vo}.wav"
            if not wav.exists():
                data, kind = decode(src)
                to_skyrim_wav(data, kind, wav, ffmpeg)
            manifest.append({"voice_type": ch["voice_type"], "speaker": ch["tag"], "name": ch["name"],
                             "dlg": line["dlg"], "entry": line["entry"], "text": line["text"], "vo": vo,
                             "wav": str(wav.relative_to(out_dir))})
            done += 1
            if limit and done >= limit:
                break
        if limit and done >= limit:
            break
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    bat = ["@echo off", "rem Run on Windows with xWMAEncode.exe (from the Creation Kit) on PATH.",
           "setlocal enabledelayedexpansion"]
    for m in manifest:
        wav = m["wav"].replace("/", "\\")
        bat.append(f'if not exist "{wav[:-4]}.xwm" xWMAEncode.exe -b 48000 "{wav}" "{wav[:-4]}.xwm"')
    (out_dir / "encode_voice.bat").write_text("\r\n".join(bat) + "\r\n")
    return {"lines": done, "missing_audio": missing, "indexed_files": len(files), "out": str(out_dir)}
