"""KOTOR 2 conversations (.dlg) and the journal → structured trees, readable scripts and a Skyrim worklist.

A KOTOR DLG is a graph: NPC lines (EntryList) link to player replies (ReplyList), which link back to NPC
lines. `StartingList` holds the entry points, each guarded by a condition script (`Active`, plus `Active2`
in TSL, with `Not`/`Not2` and `Logic` = AND/OR). Lines run action scripts (`Script`, `Script2`) and can
advance the journal (`Quest` + `QuestEntry`). Links with `IsChild` point back to a node already shown.

Skyrim's equivalent (built later from this output):
- one dialogue QUST per speaker group;
- the conversation's start → a DLBR branch whose starting DIAL topic holds the starter INFOs;
- each player reply → a DIAL topic (its prompt is the reply text);
- each NPC line → an INFO under the topic that leads to it, with "choices" (TCLT) to the next replies;
- KOTOR condition scripts → CTDA conditions on quest stages / globals; action scripts → Papyrus fragments.
The worklist written here counts every KOTOR script that needs a Papyrus port.
"""
from __future__ import annotations

from collections import Counter

from .kotor import K2Install

LINK_FIELDS = ("Active", "Active2", "Not", "Not2", "Logic", "IsChild", "LinkComment")


def _link(l: dict) -> dict:
    out = {"to": l.get("Index", 0)}
    for f in LINK_FIELDS:
        v = l.get(f)
        if v not in (None, "", 0):
            out[f.lower()] = v
    params = {k: v for k, v in l.items() if k.startswith("Param") and v not in (None, "", 0)}
    if params:
        out["params"] = params
    return out


def _node(n: dict, idx: int, kind: str) -> dict:
    text = n.get("Text") or {}
    out = {
        "id": idx,
        "text": text.get("text", ""),
        "strref": text.get("strref", -1),
    }
    for f in ("Speaker", "Listener", "Script", "Script2", "VO_ResRef", "Sound", "Quest", "Comment"):
        v = n.get(f)
        if v not in (None, ""):
            out[f.lower()] = v
    if n.get("Quest"):
        out["quest_entry"] = n.get("QuestEntry", 0)
    if n.get("PlotIndex", -1) not in (-1, None):
        out["plot_index"] = n.get("PlotIndex")
    anims = [a.get("Animation") for a in n.get("AnimList", []) or [] if a.get("Animation") is not None]
    if anims:
        out["animations"] = anims
    links = n.get("RepliesList" if kind == "entry" else "EntriesList", []) or []
    out["next"] = [_link(l) for l in links]
    return out


def conversation(install: K2Install, resref: str) -> dict:
    g = install.gff(resref, "dlg") or {}
    entries = [_node(n, i, "entry") for i, n in enumerate(g.get("EntryList", []) or [])]
    replies = [_node(n, i, "reply") for i, n in enumerate(g.get("ReplyList", []) or [])]
    return {
        "resref": resref,
        "vo_id": g.get("VO_ID", ""),
        "on_end": g.get("EndConversation", ""),
        "on_abort": g.get("EndConverAbort", ""),
        "skippable": bool(g.get("Skippable", 0)),
        "camera_model": g.get("CameraModel", ""),
        "conversation_type": g.get("ConversationType", 0),
        "starters": [_link(l) for l in g.get("StartingList", []) or []],
        "entries": entries,
        "replies": replies,
    }


def scripts_used(conv: dict) -> Counter:
    c: Counter = Counter()
    for links in [conv["starters"]] + [n["next"] for n in conv["entries"] + conv["replies"]]:
        for l in links:
            for f in ("active", "active2"):
                if l.get(f):
                    c[("condition", l[f])] += 1
    for n in conv["entries"] + conv["replies"]:
        for f in ("script", "script2"):
            if n.get(f):
                c[("action", n[f])] += 1
    for f in ("on_end", "on_abort"):
        if conv.get(f):
            c[("action", conv[f])] += 1
    return c


def readable(conv: dict, max_depth: int = 40) -> str:
    """The conversation as an indented script (Markdown), each node shown once."""
    lines = [f"# {conv['resref']}", ""]
    seen: set[tuple[str, int]] = set()

    def cond(l: dict) -> str:
        parts = []
        for f, neg in (("active", "not"), ("active2", "not2")):
            if l.get(f):
                parts.append(("!" if l.get(neg) else "") + l[f])
        return f" [if {(' or ' if l.get('logic') else ' and ').join(parts)}]" if parts else ""

    def walk(kind: str, idx: int, depth: int, via: dict):
        nodes = conv["entries"] if kind == "entry" else conv["replies"]
        if not 0 <= idx < len(nodes):
            return
        n = nodes[idx]
        pad = "  " * depth
        who = (n.get("speaker") or "NPC") if kind == "entry" else "PLAYER"
        key = (kind, idx)
        if key in seen or via.get("ischild") or depth > max_depth:
            lines.append(f"{pad}- ↩ {who} #{idx}: {n['text'][:60]}")
            return
        seen.add(key)
        extra = []
        if n.get("script"):
            extra.append(f"run {n['script']}")
        if n.get("script2"):
            extra.append(f"run {n['script2']}")
        if n.get("quest"):
            extra.append(f"journal {n['quest']}#{n.get('quest_entry', 0)}")
        if n.get("vo_resref"):
            extra.append(f"vo {n['vo_resref']}")
        tail = f" _({'; '.join(extra)})_" if extra else ""
        lines.append(f"{pad}- **{who}** #{idx}{cond(via)}: {n['text'] or '[continue]'}{tail}")
        for l in n["next"]:
            walk("reply" if kind == "entry" else "entry", l["to"], depth + 1, l)

    for s in conv["starters"]:
        walk("entry", s["to"], 0, s)
        lines.append("")
    return "\n".join(lines)


def journal_to_quests(journal: list[dict]) -> list[dict]:
    """KOTOR journal categories → Skyrim quest stages and objectives (stage = entry ID, like KOTOR's)."""
    out = []
    for q in journal:
        stages = []
        for e in sorted(q["entries"], key=lambda e: e["id"]):
            stages.append({"stage": e["id"], "log": e["text"], "completes": e["end"],
                           "objective": _first_sentence(e["text"])})
        out.append({"editor_id": "K2Q_" + _edid(q["tag"] or q["name"]), "kotor_tag": q["tag"],
                    "name": q["name"], "priority": q["priority"], "stages": stages})
    return out


def _first_sentence(text: str) -> str:
    s = text.strip().split(". ")[0].strip()
    return (s[:117] + "...") if len(s) > 120 else s


def _edid(text: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]", "", text.title())[:40] or "Unnamed"
