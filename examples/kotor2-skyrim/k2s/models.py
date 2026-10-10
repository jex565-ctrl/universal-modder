"""KOTOR 2 models (.mdl + .mdx) and textures (.tpc/.tga) → Wavefront OBJ + MTL and DDS/TGA, from the
user's own install.

OBJ is the hand-off format: `blender/obj_to_nif.py` turns each OBJ into a Skyrim SE NIF with PyNifly.
A direct MDL→NIF writer would skip Blender, but NIF has too many ways to be subtly wrong for Skyrim's
renderer to write without NifSkope at hand; Blender + PyNifly is what the Skyrim community uses.

Geometry is flattened into model space: each node's local transform is translation then rotation (a
quaternion x, y, z, w), applied parent first. Walkmesh (AABB) nodes and nodes with `render` off are left
out of the render OBJ; lightsaber blade nodes are exported separately (`*_blade.obj`) so the blade can get
an emissive Skyrim material in the crystal's colour.
"""
from __future__ import annotations

import math
from pathlib import Path

from .kotor import K2Install


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def _qrot(q, v):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    q = (x / n, y / n, z / n, w / n)
    p = (v[0], v[1], v[2], 0.0)
    conj = (-q[0], -q[1], -q[2], q[3])
    r = _qmul(_qmul(q, p), conj)
    return r[0], r[1], r[2]


class Transform:
    def __init__(self, rot=(0.0, 0.0, 0.0, 1.0), pos=(0.0, 0.0, 0.0)):
        self.rot = rot
        self.pos = pos

    def child(self, local_pos, local_rot) -> "Transform":
        p = _qrot(self.rot, local_pos)
        return Transform(_qmul(self.rot, local_rot), (self.pos[0] + p[0], self.pos[1] + p[1], self.pos[2] + p[2]))

    def apply(self, v):
        r = _qrot(self.rot, v)
        return self.pos[0] + r[0], self.pos[1] + r[1], self.pos[2] + r[2]

    def apply_dir(self, v):
        return _qrot(self.rot, v)


def _v3(v):
    return float(v.x), float(v.y), float(v.z)


def load_mdl(install: K2Install, name: str):
    """A model's node tree via k2s.mdlraw (see there for why not PyKotor's reader)."""
    from .mdlraw import RawModel
    mdl = install.get(name, "mdl")
    if mdl is None:
        return None
    mdx = install.get(name, "mdx")
    return RawModel(mdl.data(), mdx.data() if mdx else None)


def mesh_parts(model) -> list[dict]:
    """Every renderable mesh node in model space: name, texture, kind (mesh/blade), verts, normals, uvs, faces.

    A TSL lightsaber blade is drawn twice: saber nodes (flag 0x800, 176 vertices the engine animates) and
    plain crossed planes with the crystal's texture (w_lsabre<colour>01). The planes are the static blade;
    the saber nodes are skipped."""
    parts = []

    def walk(node, parent: Transform):
        t = parent.child(node.position, node.orientation)
        mesh = node.mesh
        if mesh is not None and not node.is_saber and mesh.render and mesh.faces and mesh.verts:
            tex = mesh.texture.lower()
            kind = "blade" if tex.startswith("w_lsabre") or "blade" in node.name.lower() else "mesh"
            parts.append({
                "name": node.name,
                "kind": kind,
                "texture": tex if tex and tex != "null" else "",
                "lightmap": "",
                "verts": [t.apply(v) for v in mesh.verts],
                "normals": [t.apply_dir(n) for n in mesh.normals],
                "uvs": list(mesh.uvs),
                "faces": mesh.faces,
            })
        for c in node.children:
            walk(c, t)

    walk(model.root, Transform())
    return parts


def write_obj(parts: list[dict], obj_path: Path, scale: float = 1.0) -> Path | None:
    """Write parts as one OBJ with a group and material per part. `scale` converts metres to target units."""
    if not parts:
        return None
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = obj_path.with_suffix(".mtl")
    lines = ["# converted locally from KOTOR 2 by kotor2skyrim; do not redistribute", f"mtllib {mtl_path.name}"]
    mtl = []
    textures = set()
    base = 1
    for i, p in enumerate(parts):
        mat = p["texture"] or f"untextured_{i}"
        lines.append(f"g {p['name'] or 'part'}_{i}")
        lines.append(f"usemtl {mat}")
        for v in p["verts"]:
            lines.append(f"v {v[0] * scale:.6f} {v[1] * scale:.6f} {v[2] * scale:.6f}")
        has_uv = len(p["uvs"]) == len(p["verts"])
        has_n = len(p["normals"]) == len(p["verts"])
        for u in p["uvs"] if has_uv else ():
            lines.append(f"vt {u[0]:.6f} {u[1]:.6f}")
        for n in p["normals"] if has_n else ():
            lines.append(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
        for f in p["faces"]:
            if max(f) >= len(p["verts"]):
                continue
            idx = [x + base for x in f]
            if has_uv and has_n:
                lines.append("f " + " ".join(f"{x}/{x}/{x}" for x in idx))
            elif has_uv:
                lines.append("f " + " ".join(f"{x}/{x}" for x in idx))
            elif has_n:
                lines.append("f " + " ".join(f"{x}//{x}" for x in idx))
            else:
                lines.append("f " + " ".join(str(x) for x in idx))
        base += len(p["verts"])
        if mat not in textures:
            textures.add(mat)
            mtl += [f"newmtl {mat}", "Kd 1 1 1"]
            if p["texture"]:
                mtl.append(f"map_Kd textures/{p['texture']}.dds")
            mtl.append("")
    obj_path.write_text("\n".join(lines) + "\n")
    mtl_path.write_text("\n".join(mtl) + "\n")
    return obj_path


def export_model(install: K2Install, name: str, out_dir: Path, scale: float = 1.0) -> dict:
    """MDL → `<name>.obj` (+ `<name>_blade.obj` for sabers) and the list of textures it needs."""
    model = load_mdl(install, name)
    if model is None:
        return {"model": name, "error": "not found"}
    parts = mesh_parts(model)
    body = [p for p in parts if p["kind"] == "mesh"]
    blades = [p for p in parts if p["kind"] == "blade"]
    out = {"model": name, "parts": len(parts), "textures": sorted({p["texture"] for p in parts if p["texture"]})}
    o = write_obj(body, out_dir / f"{name}.obj", scale)
    if o:
        out["obj"] = str(o)
    if blades:
        out["blade_obj"] = str(write_obj(blades, out_dir / f"{name}_blade.obj", scale))
    return out


def export_texture(install: K2Install, name: str, out_dir: Path) -> str | None:
    """A texture by resref → DDS (TPC re-encoded by PyKotor), falling back to TGA."""
    from pykotor.resource.formats.tpc import read_tpc, write_tpc
    from pykotor.resource.type import ResourceType

    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("tpc", "tga", "dds"):
        r = install.get(name, ext)
        if r is None:
            continue
        if ext == "dds":
            p = out_dir / f"{name}.dds"
            p.write_bytes(r.data())
            return str(p)
        tpc = read_tpc(r.data())
        for target, suffix in ((ResourceType.DDS, "dds"), (ResourceType.TGA, "tga")):
            p = out_dir / f"{name}.{suffix}"
            try:
                write_tpc(tpc, p, target)
                return str(p)
            except Exception:  # noqa: BLE001 - try the next format
                continue
    return None
