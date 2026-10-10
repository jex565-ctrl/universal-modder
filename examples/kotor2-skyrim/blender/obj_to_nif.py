"""Batch OBJ → Skyrim SE NIF with Blender and PyNifly. NOT YET RUN: written against PyNifly's documented
operator, but no Blender was available where it was written. Check one NIF in NifSkope before converting
a whole folder.

    blender --background --python blender/obj_to_nif.py -- <in_dir> <out_dir> [--scale 70]

- <in_dir>: `k2s models` or `k2s maps` output (OBJ + MTL + textures/).
- <out_dir>: becomes Data/meshes/kotor2/... (copy the textures to Data/textures/kotor2/ as DDS).
- --scale: KOTOR metres → Skyrim units (70 per metre). Item models are scaled the same way.

Needs PyNifly (https://github.com/BadDogSkyrim/PyNifly), installed as a Blender add-on, which registers
`bpy.ops.export_scene.pynifly`. Blade OBJs (`*_blade.obj`) get an emissive material; Skyrim draws a
glowing blade best with a BSEffectShaderProperty, which may still need setting in NifSkope.
"""
import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    scale = 70.0
    if "--scale" in argv:
        i = argv.index("--scale")
        scale = float(argv[i + 1])
        del argv[i:i + 2]
    if len(argv) < 2:
        sys.exit(__doc__)
    return Path(argv[0]), Path(argv[1]), scale


def clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_obj(path: Path):
    if hasattr(bpy.ops.wm, "obj_import"):  # Blender 3.2+
        bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    else:
        bpy.ops.import_scene.obj(filepath=str(path), axis_forward="Y", axis_up="Z")
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def make_emissive(objs, strength=4.0):
    for o in objs:
        for slot in o.material_slots:
            m = slot.material
            if m is None or not m.use_nodes:
                continue
            bsdf = m.node_tree.nodes.get("Principled BSDF")
            if bsdf is not None:
                key = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
                bsdf.inputs[key].default_value = bsdf.inputs["Base Color"].default_value
                if "Emission Strength" in bsdf.inputs:
                    bsdf.inputs["Emission Strength"].default_value = strength


def main():
    src, dst, scale = args()
    dst.mkdir(parents=True, exist_ok=True)
    for obj in sorted(src.rglob("*.obj")):
        clear()
        objs = import_obj(obj)
        if not objs:
            print(f"skip {obj}: no meshes")
            continue
        for o in objs:
            o.scale = (scale, scale, scale)
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        if obj.stem.endswith("_blade"):
            make_emissive(objs)
        out = dst / obj.relative_to(src).with_suffix(".nif")
        out.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.export_scene.pynifly(filepath=str(out), target_game="SKYRIMSE")
        print(f"wrote {out}")


main()
