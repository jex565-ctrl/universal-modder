"""KOTOR 2 weapon models → Skyrim SE NIFs and DDS textures, written as a mod folder (`<out>/mod/`) whose
`meshes/kotor2/` and `textures/kotor2/` go into Skyrim's Data folder (or a mod manager).

Axes and units: KOTOR models are in metres with the blade along +Z and the grip at the origin; Skyrim
weapons are in game units (70 per metre) with the blade along +Y. So (x, y, z) → 70·(x, z, −y), a −90°
turn about X, which keeps handedness (no winding change). UVs flip vertically (v → 1 − v), because
KOTOR's v runs up and DirectX's runs down.

Templates are vanilla meshes from the user's own archives, by Skyrim animation type (k2s.stats):
one-handed sword, dagger, greatsword, mace. Ranged weapons need the crossbow's skinned, animated rig and
are not converted yet (they keep the vanilla crossbow look).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import bsa, nif
from .kotor import K2Install
from .models import export_texture, load_mdl, mesh_parts

UNITS_PER_METRE = 70.0
TEMPLATES = {  # arsenal "template" → vanilla mesh
    "sword": "meshes/weapons/steel/steelsword.nif",
    "dagger": "meshes/weapons/steel/steeldagger.nif",
    "greatsword": "meshes/weapons/steel/steelgreatsword.nif",
    "mace": "meshes/weapons/steel/steelmace.nif",
}
NORMAL_MAP = "textures\\kotor2\\flat_n.dds"


def to_skyrim(part: dict, scale: float = UNITS_PER_METRE) -> dict:
    def p(v):
        return (v[0] * scale, v[2] * scale, -v[1] * scale)

    def d(n):
        return (n[0], n[2], -n[1])

    return {**part,
            "verts": [p(v) for v in part["verts"]],
            "normals": [d(n) for n in part["normals"]],
            "uvs": [(u, 1.0 - v) for u, v in part["uvs"]]}


def build(install: K2Install, arsenal: dict, skyrim_data: str | Path, out: Path,
          only: set[str] | None = None) -> dict:
    mod = out / "mod"
    mesh_dir, tex_dir = mod / "meshes" / "kotor2", mod / "textures" / "kotor2"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    tex_dir.mkdir(parents=True, exist_ok=True)
    (tex_dir / "flat_n.dds").write_bytes(nif.flat_normal_dds())
    templates: dict[str, bytes] = {}
    done, skipped, textures = [], {}, set()
    models = {}
    for it in arsenal["items"].values():
        if it.get("sig") == "WEAP" and it.get("model"):
            models.setdefault(it["model"], it.get("template"))
    for model, tmpl in sorted(models.items()):
        if only and model not in only:
            continue
        if tmpl not in TEMPLATES:
            skipped[model] = f"no mesh template for {tmpl!r} yet"
            continue
        m = load_mdl(install, model)
        if m is None:
            skipped[model] = "model not found"
            continue
        parts = [to_skyrim(p) for p in mesh_parts(m)]
        if not parts:
            skipped[model] = "no renderable geometry"
            continue
        if tmpl not in templates:
            data = bsa.find(skyrim_data, TEMPLATES[tmpl])
            if data is None:
                raise FileNotFoundError(f"{TEMPLATES[tmpl]} not in {skyrim_data}")
            templates[tmpl] = data
        tex_paths = {p["texture"]: f"textures\\kotor2\\{p['texture']}.dds" for p in parts if p["texture"]}
        (mesh_dir / f"{model}.nif").write_bytes(nif.weapon(templates[tmpl], parts, tex_paths, NORMAL_MAP))
        textures.update(tex_paths)
        done.append(model)
    missing = []
    for t in sorted(textures):
        src = export_texture(install, t, tex_dir)
        if not src or not src.endswith(".dds"):
            missing.append(t)
    summary = {"meshes": len(done), "skipped": skipped, "textures": len(textures), "textures_missing": missing,
               "folder": str(mod)}
    (out / "meshes.json").write_text(json.dumps({**summary, "converted": done}, indent=1))
    return summary


def install_mod(out: Path, skyrim_data: str | Path) -> list[str]:
    """Copy `<out>/mod` into Skyrim's Data folder; returns the files written (for an exact uninstall)."""
    written = []
    for f in (out / "mod").rglob("*"):
        if f.is_file():
            dst = Path(skyrim_data) / f.relative_to(out / "mod")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            written.append(str(dst))
    return written
