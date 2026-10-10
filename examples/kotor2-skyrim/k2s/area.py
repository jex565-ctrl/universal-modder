"""A KOTOR 2 area → a Skyrim SE interior cell: room meshes with collision, the cell and its references,
lights, an entry marker where KOTOR spawns the player, and the area's characters.

Units and axes: areas need no turn (KOTOR and Skyrim are both Z up), only metres → units (×70).
Room models are room-local and placed at their .lyt position; walkmeshes (.wok) are in area coordinates.

Collision comes from the walkmesh, not the render mesh: every walkable face becomes a thin floor prism, and
every walkable edge with no walkable neighbour anywhere in the area becomes a wall prism 3 m high. So you can
walk exactly where KOTOR lets you walk, doorways between rooms stay open, and no render triangles need a
Havok MOPP (which can't be generated without Bethesda's tools).

Lighting: KOTOR bakes room lighting into lightmaps, which Skyrim can't use (BSTriShape has one UV set), so the
cell gets a bright ambient and one fill light per room instead.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from . import bsa, nif
from .esp import Plugin, Record, zstring
from .kotor import K2Install, clean_text, gff_dict
from .maps import _module_res
from .meshes import NORMAL_MAP
from .models import export_texture, load_mdl, mesh_parts, texture_alpha

UNITS = 70.0
WALL_HEIGHT = 3.0          # metres
FLOOR_DEPTH = 0.25         # metres below the walkmesh
WALL_THICKNESS = 0.05      # metres
COC_MARKER, XMARKER_HEADING = 0x32, 0x34
RIGID_BODY_TEMPLATE = "meshes/clutter/quest/ms11unholyaltar.nif"
LIGHT_TEMPLATE = "WRWindowFill"
KREIA_TRAITS = "IdgrodRavencrone"  # vanilla seer whose face, race and voice type Kreia borrows


def _key(p):
    return (round(p[0], 2), round(p[1], 2), round(p[2], 2))


def walk_collision(install: K2Install, rooms: list[dict]) -> dict[str, list]:
    """Per room model: convex prisms (Havok units, room-local) for its floor and the area's walls."""
    from pykotor.resource.formats.bwm import read_bwm
    faces = []  # (room, [p0, p1, p2]) in area metres
    for room in rooms:
        wok = install.get(room["model"], "wok")
        if wok is None:
            continue
        for f in read_bwm(wok.data()).walkable_faces():
            faces.append((room, [(float(v.x), float(v.y), float(v.z)) for v in (f.v1, f.v2, f.v3)]))
    edges: dict[tuple, int] = {}
    for _, tri in faces:
        for i in range(3):
            e = tuple(sorted((_key(tri[i]), _key(tri[(i + 1) % 3]))))
            edges[e] = edges.get(e, 0) + 1
    out: dict[str, list] = {r["model"]: [] for r in rooms}
    s = UNITS / nif.HAVOK_SCALE  # metres → Havok units
    for room, tri in faces:
        ox, oy, oz = room["pos"]
        local = [((p[0] - ox) * s, (p[1] - oy) * s, (p[2] - oz) * s) for p in tri]
        out[room["model"]].append(nif.prism(local, (0, 0, -FLOOR_DEPTH * s)))
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            if edges[tuple(sorted((_key(a), _key(b))))] != 1:
                continue
            la = ((a[0] - ox) * s, (a[1] - oy) * s, (a[2] - oz) * s)
            lb = ((b[0] - ox) * s, (b[1] - oy) * s, (b[2] - oz) * s)
            dx, dy = lb[0] - la[0], lb[1] - la[1]
            m = math.hypot(dx, dy) or 1.0
            # push the wall outward (away from the triangle's third point)
            c = tri[(i + 2) % 3]
            lc = ((c[0] - ox) * s, (c[1] - oy) * s)
            nx, ny = -dy / m, dx / m
            if (lc[0] - la[0]) * nx + (lc[1] - la[1]) * ny > 0:
                nx, ny = -nx, -ny
            h = WALL_HEIGHT * s
            quad = [la, lb, (lb[0], lb[1], lb[2] + h), (la[0], la[1], la[2] + h)]
            out[room["model"]].append(nif.prism(quad, (nx * WALL_THICKNESS * s, ny * WALL_THICKNESS * s, 0)))
    return out


def room_parts(install: K2Install, model: str) -> list[dict]:
    m = load_mdl(install, model)
    if m is None:
        return []
    parts = []
    # skinned meshes (KOTOR's posed bodies in rooms) would show in their bind pose; left out for now
    for p in mesh_parts(m, skinless=True):
        if p["kind"] != "mesh":
            continue
        parts.append({**p, "verts": [(v[0] * UNITS, v[1] * UNITS, v[2] * UNITS) for v in p["verts"]],
                      "uvs": [(u, 1.0 - v) for u, v in p["uvs"]], "alpha": texture_alpha(install, p["texture"])})
    return parts


def module_entry(install: K2Install, module: str) -> dict | None:
    ifo = _module_res(install, module, "module", "ifo")
    if ifo is None:
        return None
    g = gff_dict(ifo.data(), install)
    pos = [g.get("Mod_Entry_X", 0.0), g.get("Mod_Entry_Y", 0.0), g.get("Mod_Entry_Z", 0.0)]
    heading = math.atan2(g.get("Mod_Entry_Dir_Y", 1.0), g.get("Mod_Entry_Dir_X", 0.0))
    return {"pos": pos, "rot_z": (math.pi / 2 - heading) % (2 * math.pi)}


def _refr(plugin: Plugin, base: int, pos, rot_z: float = 0.0, edid: str | None = None, sig: str = "REFR",
          scale: float | None = None) -> Record:
    r = Record(sig, plugin.new_formid())
    if edid:
        r.add("EDID", zstring(edid))
    r.add("NAME", struct.pack("<I", base))
    if scale:
        r.add("XSCL", struct.pack("<f", scale))
    r.add("DATA", struct.pack("<6f", pos[0], pos[1], pos[2], 0.0, 0.0, rot_z))
    return r


def _bounds(parts) -> bytes:
    vs = [v for p in parts for v in p["verts"]] or [(0, 0, 0)]
    lo = [max(-32768, int(math.floor(min(v[k] for v in vs)))) for k in range(3)]
    hi = [min(32767, int(math.ceil(max(v[k] for v in vs)))) for k in range(3)]
    return struct.pack("<6h", *lo, *hi)


def xcll(ambient=(70, 74, 82), directional=(40, 42, 50)) -> bytes:
    """Interior lighting (92 bytes): ambient, directional and fog colours, fog near/far, directional
    rotation and fade, fog clip/power, directional ambient (6 colours, specular, fresnel), fog far colour,
    fog max, light fade begin/end, and inheritance flags (0: nothing from a lighting template)."""
    rgba = lambda c: bytes([*c, 0])  # noqa: E731
    out = rgba(ambient) + rgba(directional) + rgba((0, 0, 0)) + struct.pack("<ff", 0.0, 60000.0)
    out += struct.pack("<iifff", 0, 150, 1.0, 60000.0, 1.0)
    out += rgba(ambient) * 6 + rgba((0, 0, 0)) + struct.pack("<f", 1.0)
    out += rgba((0, 0, 0)) + struct.pack("<fffI", 1.0, 3000.0, 6000.0, 0)
    assert len(out) == 92
    return out


def build(install: K2Install, module: str, area: str, layout: dict, skyrim_data: str | Path, out: Path,
          plugin: Plugin, masters, arsenal: dict, catalog: dict) -> dict:
    """Meshes into `out/mod`, records into `plugin`. Returns what was placed."""
    tag = module.upper()
    mesh_rel = f"kotor2\\{module}"
    mesh_dir = out / "mod" / "meshes" / "kotor2" / module
    tex_dir = out / "mod" / "textures" / "kotor2"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    tex_dir.mkdir(parents=True, exist_ok=True)
    (tex_dir / "flat_n.dds").write_bytes(nif.flat_normal_dds())
    rb = next(b for t, b in nif.read(bsa.find(skyrim_data, RIGID_BODY_TEMPLATE)).blocks if t == "bhkRigidBody")
    collision = walk_collision(install, layout["rooms"])
    textures: set[str] = set()

    cell = Record("CELL", plugin.new_formid())
    cell.add("EDID", zstring(f"K2_{tag}"))
    cell.add("FULL", zstring(clean_text(layout.get("name") or tag)))
    cell.add("DATA", struct.pack("<H", 0x0001))
    cell.add("XCLL", xcll())
    cell.add("XCLW", struct.pack("<I", 0xCF000000))
    plugin.add(cell)

    light = plugin.new_record("LIGH", f"K2_{tag}_Fill")
    masters.copy_fields(*masters.first([LIGHT_TEMPLATE], "LIGH")[1:], plugin,
                        ["OBND", "DATA", "FNAM"], light)
    data = bytearray(light.get("DATA"))
    struct.pack_into("<I", data, 4, 900)               # radius
    data[8:12] = bytes([170, 180, 200, 0])            # cold white, dimmer
    light.subrecords = [s if s.sig != "DATA" else type(s)("DATA", bytes(data)) for s in light.subrecords]

    placed = {"rooms": 0, "collision_prisms": 0, "lights": 0}
    for room in layout["rooms"]:
        model = room["model"]
        parts = room_parts(install, model)
        convexes = collision.get(model, [])
        if not parts and not convexes:
            continue
        tex_paths = {p["texture"]: f"textures\\kotor2\\{p['texture']}.dds" for p in parts if p["texture"]}
        textures.update(tex_paths)
        (mesh_dir / f"{model}.nif").write_bytes(nif.static(parts, tex_paths, NORMAL_MAP, convexes, rb))
        stat = plugin.new_record("STAT", f"K2_{model}")
        stat.add("OBND", _bounds(parts))
        stat.add("MODL", zstring(f"{mesh_rel}\\{model}.nif"))
        stat.add("DNAM", struct.pack("<fI", 30.0, 0))
        pos = [c * UNITS for c in room["pos"]]
        cell.children.append(_refr(plugin, stat.formid, pos))
        if parts:
            vs = [v for p in parts for v in p["verts"]]
            centre = [(min(v[k] for v in vs) + max(v[k] for v in vs)) / 2 for k in range(3)]
            top = max(v[2] for v in vs)
            cell.children.append(_refr(plugin, light.formid,
                                       (pos[0] + centre[0], pos[1] + centre[1], pos[2] + min(top - 20, centre[2] + 150))))
            placed["lights"] += 1
        placed["rooms"] += 1
        placed["collision_prisms"] += len(convexes)

    entry = module_entry(install, module)
    if entry:
        p = [c * UNITS for c in entry["pos"]]
        cell.persistent.append(_refr(plugin, COC_MARKER, (p[0], p[1], p[2] + 10), entry["rot_z"]))
        placed["entry"] = entry

    for t in sorted(textures):
        export_texture(install, t, tex_dir)
    placed["textures"] = len(textures)
    placed["cell"] = f"K2_{tag}"
    return placed
