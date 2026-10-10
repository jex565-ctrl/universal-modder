"""KOTOR 2 modules (Peragus, Telos, Nar Shaddaa, Dxun/Onderon, Dantooine, Korriban, Malachor V, the Ebon
Hawk...) → Skyrim-ready map kits.

For each area of a module this writes, into the user's private output folder:
- `layout.json`: rooms (model + position from the .lyt), door hooks, and every GIT placement (creatures,
  doors, placeables, waypoints, triggers, sounds, stores, encounters) with KOTOR and Skyrim coordinates;
- `rooms/<room>.obj`: the room's render geometry (models.py) for Blender → NIF;
- `walkmesh/<room>.obj`: the room's walkable faces from its .wok, the guide for Skyrim navmesh.

Units and axes: KOTOR uses metres, Z up, X east, Y north. Skyrim uses ~70 units per metre (the player is
~128 units tall), Z up, X east, Y north. KOTOR facing is counter-clockwise from +X (SetFacing(0) = east);
Skyrim's Z rotation is clockwise from +Y (0 = north), so `rz = pi/2 - bearing`. Check the facing on
a known placeable in game before trusting it for a whole map.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from pykotor.resource.formats.bwm import read_bwm
from pykotor.resource.formats.lyt import read_lyt

from .kotor import K2Install, gff_dict
from .models import export_model

UNITS_PER_METRE = 70.0


def to_skyrim(pos, bearing: float | None) -> dict:
    x, y, z = (float(c) for c in pos)
    out = {"pos": [round(x * UNITS_PER_METRE, 2), round(y * UNITS_PER_METRE, 2), round(z * UNITS_PER_METRE, 2)]}
    if bearing is not None:
        out["rot_z"] = round((math.pi / 2 - bearing) % (2 * math.pi), 6)
    return out


def _placement(kind: str, s: dict) -> dict:
    pos = [s.get(k, s.get(k2, 0.0)) for k, k2 in (("XPosition", "X"), ("YPosition", "Y"), ("ZPosition", "Z"))]
    if "Bearing" in s:
        bearing = float(s["Bearing"])
    elif "XOrientation" in s or "YOrientation" in s:
        bearing = math.atan2(float(s.get("YOrientation", 0.0)), float(s.get("XOrientation", 1.0)))
    else:
        bearing = None
    out = {"kind": kind, "template": s.get("TemplateResRef", ""), "tag": s.get("Tag", ""), "pos": pos,
           "bearing": bearing, "skyrim": to_skyrim(pos, bearing)}
    for f in ("LinkedTo", "LinkedToModule", "TransitionDestin", "Conversation"):
        if s.get(f):
            out[f.lower()] = s[f] if not isinstance(s[f], dict) else s[f].get("text", "")
    if isinstance(s.get("LocalizedName"), dict) and s["LocalizedName"].get("text"):
        out["name"] = s["LocalizedName"]["text"]
    if "Geometry" in s:  # triggers and encounters: polygon points relative to the position
        out["polygon"] = [[p.get("PointX", 0.0), p.get("PointY", 0.0), p.get("PointZ", 0.0)] for p in s["Geometry"]]
    return out


def module_areas(install: K2Install, module: str) -> list[str]:
    """Area resrefs of a module (from its module.ifo, else every .are in its containers)."""
    code = module.lower()
    resources = [r for c, rs in install.by_module.items() if re.sub(r"(_s|_dlg|_a|_adx|_x)?\.(rim|mod|erf)$", "", c) == code
                 for r in rs]
    ifo = next((r for r in resources if r.resname == "module" and r.ext == "ifo"), None)
    if ifo is not None:
        try:
            areas = [a.get("Area_Name", "") for a in gff_dict(ifo.data()).get("Mod_Area_list", []) or []]
            if any(areas):
                return [a for a in areas if a]
        except Exception:  # noqa: BLE001
            pass
    return sorted({r.resname for r in resources if r.ext == "are"})


def _module_res(install: K2Install, module: str, resname: str, ext: str):
    code = module.lower()
    for c, rs in install.by_module.items():
        if re.sub(r"(_s|_dlg|_a|_adx|_x)?\.(rim|mod|erf)$", "", c) != code:
            continue
        for r in rs:
            if r.resname == resname.lower() and r.ext == ext:
                return r
    return install.get(resname, ext)


def export_area(install: K2Install, module: str, area: str, out_dir: Path, geometry: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"module": module, "area": area}
    are = _module_res(install, module, area, "are")
    if are is not None:
        a = gff_dict(are.data(), install)
        result["name"] = (a.get("Name") or {}).get("text", "")
        result["tag"] = a.get("Tag", "")
        result["environment"] = {k: a.get(k) for k in ("SunAmbientColor", "SunDiffuseColor", "SunFogOn", "SunFogNear",
                                                       "SunFogFar", "SunFogColor", "DynAmbientColor", "Unescapable",
                                                       "StealthXPEnabled") if k in a}
        result["scripts"] = {k: a.get(k) for k in ("OnEnter", "OnExit", "OnHeartbeat", "OnUserDefined") if a.get(k)}
    lyt_res = _module_res(install, module, area, "lyt")
    rooms = []
    if lyt_res is not None:
        lyt = read_lyt(lyt_res.data())
        for room in lyt.rooms:
            p = (float(room.position.x), float(room.position.y), float(room.position.z))
            rooms.append({"model": room.model.lower(), "pos": list(p), "skyrim": to_skyrim(p, None)})
        result["door_hooks"] = [{"room": d.room, "door": d.door,
                                 "pos": [float(d.position.x), float(d.position.y), float(d.position.z)]}
                                for d in lyt.doorhooks]
    result["rooms"] = rooms
    git = _module_res(install, module, area, "git")
    placements = []
    if git is not None:
        g = gff_dict(git.data(), install)
        for list_name, items in g.items():
            if isinstance(items, list):
                kind = re.sub(r"\s*List$", "", list_name).strip().lower()
                placements += [_placement(kind, s) for s in items if isinstance(s, dict)]
    result["placements"] = placements
    if geometry:
        result["room_models"] = []
        for room in rooms:
            m = export_model(install, room["model"], out_dir / "rooms")
            result["room_models"].append(m)
            wok = install.get(room["model"], "wok")
            if wok is not None:
                result.setdefault("walkmeshes", []).append(
                    export_walkmesh(wok.data(), out_dir / "walkmesh" / f"{room['model']}.obj"))
    (out_dir / "layout.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def export_walkmesh(data: bytes, path: Path) -> str:
    """The walkable faces of a .wok/.pwk/.dwk as OBJ (metres, area space)."""
    bwm = read_bwm(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# walkable faces, converted locally by kotor2skyrim"]
    n = 0
    for face in bwm.walkable_faces():
        for v in (face.v1, face.v2, face.v3):
            lines.append(f"v {float(v.x):.5f} {float(v.y):.5f} {float(v.z):.5f}")
        lines.append(f"f {n + 1} {n + 2} {n + 3}")
        n += 3
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
