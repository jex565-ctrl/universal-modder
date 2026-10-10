"""KOTOR 2's characters → character sheets with every line they speak and the voice file for each line.

Speakers are worked out the way the game does it: an NPC line with a `Speaker` tag belongs to the creature
with that tag; an NPC line with no speaker belongs to the conversation's owner (a creature whose
`Conversation` field names the .dlg). Player lines (replies) belong to the Exile and aren't voiced in KOTOR 2.

Party members are the `p_*.utc` templates (p_kreia, p_atton, p_baodur, p_hk47, p_t3m4, p_mira, p_hanharr,
p_visas, p_mand, p_handmaiden, p_disciple, p_g0t0...). They get a `companion` flag.

In Skyrim each speaking character gets their own voice type (VTYP), so only they can say their lines, and
each line becomes an INFO whose response plays `Sound/Voice/<plugin>/<voice type>/<file>.fuz` (voice.py).
"""
from __future__ import annotations

import re
from collections import defaultdict

COMPANION_PREFIX = "p_"


def voice_type_edid(name: str, tag: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]", "", (name or tag).title()) or "Unknown"
    return f"K2Voice{base[:40]}"


def build(catalog: dict, conversations: dict[str, dict]) -> dict:
    """`conversations`: resref → dialogue.conversation() output. Returns {'characters': [...], 'unassigned': n}."""
    by_tag: dict[str, dict] = {}
    owners: dict[str, list[dict]] = defaultdict(list)
    for c in catalog.get("creatures", []):
        tag = (c.get("tag") or "").lower()
        if tag and (tag not in by_tag or c["resref"].startswith(COMPANION_PREFIX)):
            by_tag[tag] = c
        if c.get("conversation"):
            owners[c["conversation"].lower()].append(c)

    sheets: dict[str, dict] = {}

    def sheet(c: dict) -> dict:
        key = (c.get("tag") or c["resref"]).lower()
        if key not in sheets:
            sheets[key] = {
                "tag": key,
                "name": c.get("name", ""),
                "templates": [],
                "companion": False,
                "appearance": c.get("appearance_label", ""),
                "race": c.get("race", ""),
                "gender": c.get("gender", 0),
                "hp": c.get("hp", 0),
                "fp": c.get("fp", 0),
                "stats": c.get("stats", {}),
                "classes": c.get("classes", []),
                "equipment": c.get("equipment", []),
                "conversations": set(),
                "lines": [],
                "voice_type": voice_type_edid(c.get("name", ""), key),
            }
        s = sheets[key]
        if c["resref"] not in s["templates"]:
            s["templates"].append(c["resref"])
        if c["resref"].startswith(COMPANION_PREFIX):
            s["companion"] = True
            s["name"] = c.get("name") or s["name"]
        return s

    for c in catalog.get("creatures", []):
        sheet(c)

    unassigned = 0
    for resref, conv in conversations.items():
        owner = owners.get(resref.lower(), [])
        for e in conv["entries"]:
            if not e.get("text") and not e.get("vo_resref"):
                continue
            speaker = (e.get("speaker") or "").lower()
            c = by_tag.get(speaker) if speaker else (owner[0] if owner else None)
            if c is None:
                unassigned += 1
                continue
            s = sheet(c)
            s["conversations"].add(resref)
            s["lines"].append({"dlg": resref, "entry": e["id"], "text": e["text"], "strref": e["strref"],
                               "vo": e.get("vo_resref") or "", "sound": e.get("sound") or ""})
    out = []
    for s in sorted(sheets.values(), key=lambda s: (not s["companion"], -len(s["lines"]), s["tag"])):
        s["conversations"] = sorted(s["conversations"])
        s["voiced_lines"] = sum(1 for l in s["lines"] if l["vo"] or l["sound"])
        out.append(s)
    return {"characters": out, "unassigned_lines": unassigned}
