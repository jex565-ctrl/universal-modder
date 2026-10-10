"""A KOTOR conversation (.dlg, exported by k2s.dialogue) → Skyrim dialogue records with the original voice.

KOTOR alternates NPC entries and player replies. Skyrim has topics (DIAL: what the player says) holding
INFOs (what the NPC answers, one or more lines), joined by "choices" (TCLT: the topics offered next).
- The starting entry becomes the NPC's Hello line (a Hello topic of the conversation's quest).
- Every player reply with text becomes a topic; its INFO is the NPC entry KOTOR would pick next, plus any
  entries chained through text-less "[continue]" replies, spoken in order as responses 1, 2, 3...
- The replies after that chain become the INFO's choices. Replies offered at the start are top-level
  topics, each with its own dialogue branch (DLBR).
- A reply that leads nowhere ends the conversation (Goodbye flag).
- KOTOR conditions (NWScript) aren't ported yet: skill checks pass, plot checks fail, so a branch shows
  what a first conversation would. Every INFO carries GetIsID(speaker) so only that NPC says it.

Voice: Skyrim looks for `Sound/Voice/<plugin>/<voice type>/<quest>_<topic>_<INFO FormID>_<n>.wav`
(it also accepts .fuz/.xwm). Quest and topic EditorIDs are kept to 10 and 15 characters, so the name needs
no truncation rule, and the INFO FormID is written with load-order byte 00.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from .esp import Plugin, Record, Subrecord, zstring
from .kotor import clean_text

GET_IS_ID = 72
HELLO_DATA = bytes([0, 7, 73, 0])     # category Misc, subtype Hello
TOPIC_DATA = bytes([0, 0, 0, 0])      # custom player topic
GOODBYE = 0x0001
MAX_CHAIN = 12


def _condition_true(name: str) -> bool:
    n = (name or "").lower()
    return n.startswith(("c_sc_", "c_ac_", "c_skill"))  # skill/attribute checks pass


def _link_ok(link: dict) -> bool:
    cond = link.get("active")
    if not cond:
        return True
    ok = _condition_true(cond)
    return not ok if link.get("not") else ok


def _say(node: dict) -> str:
    """What gets spoken/shown: designer stage directions in {} are already removed by clean_text."""
    return re.sub(r"\s+", " ", clean_text(node.get("text") or "")).strip()


def ctda_is_id(npc: int) -> bytes:
    return struct.pack("<B3xfHHIIIIi", 0, 1.0, GET_IS_ID, 0, npc, 0, 0, 0, -1)


def trdt(n: int) -> bytes:
    return struct.pack("<II4xB3xIB3x", 0, 50, n, 0, 1)


class Converter:
    def __init__(self, plugin: Plugin, conv: dict, speaker: int, quest_edid: str, prefix: str, full_name: str):
        self.p = plugin
        self.E = {e["id"]: e for e in conv["entries"]}
        self.R = {r["id"]: r for r in conv["replies"]}
        self.speaker = speaker
        self.prefix = prefix
        self.quest = plugin.new_record("QUST", quest_edid)
        self.quest.add("FULL", zstring(full_name))
        self.quest.add("DNAM", struct.pack("<HBBII", 0x0011, 50, 0, 0, 0))
        self.quest.add("NEXT", b"")
        self.quest.add("ANAM", struct.pack("<I", 0))
        self.topics: dict[int, Record] = {}
        self.dials: list[Record] = []
        self.voice: list[tuple[str, str]] = []  # (wav file name, KOTOR vo resref)
        self.pending: list[tuple[int, Record]] = []

    # -------------------------------------------------------------- graph helpers
    def chain(self, entry_id: int) -> tuple[list[dict], dict]:
        """NPC entries spoken in a row from `entry_id`, following text-less replies; returns (lines, last)."""
        lines, e, seen = [], self.E[entry_id], set()
        while e["id"] not in seen and len(lines) < MAX_CHAIN:
            seen.add(e["id"])
            if _say(e):
                lines.append(e)
            nxt = [l for l in e.get("next", []) if _link_ok(l)]
            if len(nxt) == 1 and not _say(self.R[nxt[0]["to"]]):
                follow = [l for l in self.R[nxt[0]["to"]].get("next", []) if _link_ok(l)]
                if follow:
                    e = self.E[follow[0]["to"]]
                    continue
            break
        return lines, e

    def choices(self, entry: dict) -> list[int]:
        return [l["to"] for l in entry.get("next", []) if _link_ok(l) and _say(self.R[l["to"]])]

    # -------------------------------------------------------------- records
    def info(self, dial: Record, lines: list[dict], choices: list[int], goodbye: bool) -> Record:
        r = Record("INFO", self.p.new_formid())
        r.add("ENAM", struct.pack("<HH", GOODBYE if goodbye else 0, 0))
        r.add("CNAM", b"\0")
        for c in choices:
            r.add("TCLT", struct.pack("<I", self.topic(c).formid))
        if not lines:
            r.add("TRDT", trdt(1))
            r.add("NAM1", zstring(""))
            r.add("NAM2", zstring(""))
            r.add("NAM3", zstring(""))
        for n, e in enumerate(lines, 1):
            r.add("TRDT", trdt(n))
            r.add("NAM1", zstring(_say(e)))
            r.add("NAM2", zstring(e.get("vo_resref") or ""))
            r.add("NAM3", zstring(""))
            if e.get("vo_resref"):
                self.voice.append((self._voice_name(dial, r, n), e["vo_resref"]))
        r.add("CTDA", ctda_is_id(self.speaker))
        dial.children.append(r)
        return r

    def _voice_name(self, dial: Record, info: Record, n: int) -> str:
        return f"{self.quest.edid}_{dial.edid}_{info.formid & 0xFFFFFF:08X}_{n}.wav"

    def topic(self, reply_id: int) -> Record:
        if reply_id in self.topics:
            return self.topics[reply_id]
        d = Record("DIAL", self.p.new_formid())
        d.add("EDID", zstring(f"{self.prefix}R{reply_id}"))
        d.add("FULL", zstring(_say(self.R[reply_id])))
        d.add("PNAM", struct.pack("<f", 50.0))
        d.add("QNAM", struct.pack("<I", self.quest.formid))
        d.add("DATA", TOPIC_DATA)
        d.add("SNAM", b"CUST")
        self.topics[reply_id] = d
        self.dials.append(d)
        self.pending.append((reply_id, d))
        return d

    def build(self, start_entry: int) -> dict:
        lines, last = self.chain(start_entry)
        hello = Record("DIAL", self.p.new_formid())
        hello.add("EDID", zstring(f"{self.prefix}Hello"))
        hello.add("PNAM", struct.pack("<f", 50.0))
        hello.add("QNAM", struct.pack("<I", self.quest.formid))
        hello.add("DATA", HELLO_DATA)
        hello.add("SNAM", b"HELO")
        self.dials.append(hello)
        self.info(hello, lines, [], False)
        top = self.choices(last)
        for rid in top:
            d = self.topic(rid)
            b = self.p.new_record("DLBR", f"{self.prefix}B{rid}")
            b.add("QNAM", struct.pack("<I", self.quest.formid))
            b.add("TNAM", struct.pack("<I", 0))
            b.add("DNAM", struct.pack("<I", 1))   # top-level
            b.add("SNAM", struct.pack("<I", d.formid))
            d.subrecords.insert(3, Subrecord("BNAM", struct.pack("<I", b.formid)))
        while self.pending:
            rid, d = self.pending.pop(0)
            nxt = [l for l in self.R[rid].get("next", []) if _link_ok(l)]
            if not nxt:
                self.info(d, [], [], True)
                continue
            lines, last = self.chain(nxt[0]["to"])
            ch = self.choices(last)
            self.info(d, lines, ch, goodbye=not ch)
        for d in self.dials:
            d.add("TIFC", struct.pack("<I", len(d.children)))
            self.p.add(d)
        return {"quest": self.quest.edid, "topics": len(self.topics), "top_level": len(top),
                "infos": sum(len(d.children) for d in self.dials), "voiced_lines": len(self.voice)}


def export_voice(kotor2: str | Path, voice: list[tuple[str, str]], folder: Path, ffmpeg: str = "ffmpeg") -> dict:
    """Decode each KOTOR line into `folder` under its Skyrim file name."""
    from .voice import decode, index_voice, to_skyrim_wav
    idx = index_voice(kotor2)
    folder.mkdir(parents=True, exist_ok=True)
    done, missing = 0, []
    for name, vo in voice:
        src = idx.get(vo.lower())
        if src is None:
            missing.append(vo)
            continue
        data, kind = decode(src)
        to_skyrim_wav(data, kind, folder / name, ffmpeg)
        done += 1
    return {"written": done, "missing": missing}
