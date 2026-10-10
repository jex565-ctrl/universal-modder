"""kotor2skyrim: bring Knights of the Old Republic II into Skyrim SE from your own installs.

Steps (each reads what the previous wrote in --out, a private folder outside any repo):
  catalog     KOTOR 2 install -> catalog.json (items, creatures, force powers, journal, modules)
  arsenal     catalog + Skyrim masters -> KotOR2_Arsenal.esp (weapons, armour, power cells, footlocker)
  console     arsenal.json -> the console line that spawns the footlocker
  dialogue    every .dlg -> dialogue/<resref>.json + .md, quests.json, scripts_to_port.json
  characters  catalog + dialogue -> characters.json (who says which line, voice file per line)
  voice       characters.json -> voice/wav/<voice type>/*.wav (44.1 kHz mono) + encode_voice.bat
  maps        modules -> maps/<module>/<area>/layout.json, rooms/*.obj, walkmesh/*.obj
  models      item models -> models/*.obj (+ blade OBJs for lightsabers), textures/*.dds
  meshes      weapon models -> mod/meshes/kotor2/*.nif + mod/textures/kotor2/*.dds (no Blender needed)
  inspect     list the records of any Skyrim plugin (check what was built)

Run with: uv run --with pykotor==2.3.12 python -m k2s <step> ...   (from examples/kotor2-skyrim)

Examples:
  python -m k2s catalog --kotor2 "C:/Steam/steamapps/common/Knights of the Old Republic II" --out ~/k2s-out
  python -m k2s arsenal --out ~/k2s-out --skyrim-data "C:/Steam/steamapps/common/Skyrim Special Edition/Data"
  python -m k2s console --out ~/k2s-out --prefix FE001
  python -m k2s maps --kotor2 ... --out ~/k2s-out --module 101per
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _install(a):
    from .kotor import K2Install
    return K2Install(a.kotor2)


def _load(out: Path, name: str):
    p = out / name
    if not p.exists():
        sys.exit(f"{p} not found; run the step that writes it first")
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_catalog(a):
    from .catalog import Catalog
    cat = Catalog(_install(a)).build()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "catalog.json").write_text(json.dumps(cat, indent=1), encoding="utf-8")
    print(json.dumps({"summary": cat["summary"], "diagnostics": cat["diagnostics"]}, indent=1))


def cmd_arsenal(a):
    from .arsenal import build
    from .skyrim import MasterSet
    ms = MasterSet(a.skyrim_data, a.masters.split(",") if a.masters else None)
    s = build(_load(a.out, "catalog.json"), ms, a.out, esl=not a.no_esl,
              meshes=Path(a.skyrim_data) / "meshes" / "kotor2" if a.use_meshes else None)
    print(json.dumps({k: v for k, v in s.items() if k != "items"}, indent=1))


def cmd_console(a):
    from .arsenal import console_batch
    text = console_batch(_load(a.out, "arsenal.json"), a.prefix)
    (a.out / "kotor2.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    print(f"# saved as {a.out / 'kotor2.txt'}; copy it next to SkyrimSE.exe and type `bat kotor2` in the console")


def cmd_dialogue(a):
    from collections import Counter

    from .dialogue import conversation, journal_to_quests, readable, scripts_used
    k = _install(a)
    d = a.out / "dialogue"
    d.mkdir(parents=True, exist_ok=True)
    scripts: Counter = Counter()
    n, failed = 0, {}
    for r in k.all("dlg"):
        try:
            conv = conversation(k, r.resname)
        except Exception as e:  # noqa: BLE001 - a few retail .dlg files are damaged; log them and go on
            failed[r.resname] = f"{type(e).__name__}: {e}"[:200]
            continue
        (d / f"{r.resname}.json").write_text(json.dumps(conv, indent=1), encoding="utf-8")
        (d / f"{r.resname}.md").write_text(readable(conv), encoding="utf-8")
        scripts.update(scripts_used(conv))
        n += 1
    (a.out / "scripts_to_port.json").write_text(json.dumps(
        [{"kind": k_, "script": s, "uses": c} for (k_, s), c in scripts.most_common()], indent=1), encoding="utf-8")
    (a.out / "dialogue_failed.json").write_text(json.dumps(failed, indent=1), encoding="utf-8")
    cat = _load(a.out, "catalog.json") if (a.out / "catalog.json").exists() else None
    if cat:
        (a.out / "quests.json").write_text(json.dumps(journal_to_quests(cat["journal"]), indent=1), encoding="utf-8")
    print(json.dumps({"conversations": n, "failed": len(failed), "scripts_to_port": len(scripts), "quests": len(cat["journal"]) if cat else None}))


def cmd_characters(a):
    from .characters import build
    cat = _load(a.out, "catalog.json")
    convs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((a.out / "dialogue").glob("*.json"))}
    if not convs:
        sys.exit("run `dialogue` first")
    res = build(cat, convs)
    (a.out / "characters.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    top = [(c["name"], c["tag"], len(c["lines"]), c["voiced_lines"]) for c in res["characters"] if c["lines"]][:25]
    print(json.dumps({"characters": len(res["characters"]), "unassigned_lines": res["unassigned_lines"],
                      "most_lines": top}, indent=1))


def cmd_voice(a):
    from .voice import export
    res = export(a.kotor2, _load(a.out, "characters.json"), a.out, ffmpeg=a.ffmpeg,
                 only=set(a.only.lower().split(",")) if a.only else None, limit=a.limit)
    print(json.dumps(res, indent=1))


def cmd_maps(a):
    from .maps import export_area, module_areas
    k = _install(a)
    mods = [a.module.lower()] if a.module else sorted({m["module"] for m in _load(a.out, "catalog.json")["modules"]})
    for m in mods:
        for area in module_areas(k, m):
            r = export_area(k, m, area, a.out / "maps" / m / area, geometry=not a.no_geometry)
            print(f"{m}/{area}: {r.get('name', '')!r} rooms={len(r['rooms'])} placements={len(r['placements'])}")


def cmd_models(a):
    from .catalog import item_model
    from .models import export_model, export_texture
    k = _install(a)
    names = set(a.names.lower().split(",")) if a.names else set()
    if not names:
        names = {item_model(it) for it in _load(a.out, "catalog.json")["items"]
                 if it["class"] in ("lightsaber", "melee", "ranged") and item_model(it)}
    textures = set()
    for n in sorted(names):
        r = export_model(k, n, a.out / "models")
        textures.update(r.get("textures", []))
        print(json.dumps(r))
    for t in sorted(textures):
        export_texture(k, t, a.out / "models" / "textures")


def cmd_meshes(a):
    from .meshes import build, install_mod
    res = build(_install(a), _load(a.out, "arsenal.json"), a.skyrim_data, a.out,
                only=set(a.only.lower().split(",")) if a.only else None)
    print(json.dumps({k: v for k, v in res.items() if k != "skipped"} | {"skipped": len(res["skipped"])}, indent=1))
    if a.install:
        files = install_mod(a.out, a.skyrim_data)
        (a.out / "installed_files.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
        print(f"copied {len(files)} files into {a.skyrim_data} (list: {a.out / 'installed_files.txt'})")


def cmd_area(a):
    from .area import UNITS, build
    from .esp import Plugin
    from .maps import export_area, module_areas
    from .npc import actor_ref, make_npc
    from .skyrim import MasterSet
    k = _install(a)
    module = a.module.lower()
    masters = ["Skyrim.esm", "Update.esm", "Dawnguard.esm"]
    ms = MasterSet(a.skyrim_data, masters, types={"NPC_", "LIGH", "OTFT", "STAT", "ARMO", "WEAP", "VTYP"})
    plugin = Plugin(f"KotOR2_{module.upper()}.esp", masters, author="kotor2skyrim",
                    description=f"KOTOR 2 {module.upper()} converted locally from your own install")
    results = []
    for area in module_areas(k, module):
        layout = export_area(k, module, area, a.out / "maps" / module / area, geometry=False)
        res = build(k, module, area, layout, a.skyrim_data, a.out, plugin, ms, {}, {})
        cell = next(r for r in plugin.records if r.sig == "CELL" and r.edid == res["cell"])
        wps = {p.get("tag", "").lower(): p for p in layout["placements"] if p["kind"] == "waypoint"}
        cast = {"kreia": "wp_kreia_spawn1"}
        npcs = {}
        for p in layout["placements"]:
            if p["kind"] == "creature" and p.get("template", "").lower() == "p_atton":
                cast["atton"] = p
        for tag, where in cast.items():
            spot = wps.get(where) if isinstance(where, str) else where
            if not spot:
                continue
            npc = make_npc(plugin, ms, tag, f"K2_{tag.capitalize()}")
            npcs[tag] = npc
            x, y, z = (c * UNITS for c in spot["pos"])
            cell.persistent.append(actor_ref(plugin, npc.formid, (x, y, z + 5),
                                             spot.get("skyrim", {}).get("rot_z", 0.0), f"K2_{tag.capitalize()}Ref"))
            res.setdefault("characters", []).append(tag)
        # conversations: (dlg, speaker tag, starting entry, topic prefix, quest EditorID)
        talks = [("101kreia", "kreia", 44, "K2KR", "K2Kreia101")] if module == "101per" else []
        for dlg, tag, start, prefix, quest in talks:
            if tag not in npcs:
                continue
            from .talk import Converter, export_voice
            import struct as _s
            conv = json.loads((a.out / "dialogue" / f"{dlg}.json").read_text(encoding="utf-8"))
            c = Converter(plugin, conv, npcs[tag].formid, quest, prefix, f"KOTOR 2: {dlg}")
            info = c.build(start)
            vt_fid = _s.unpack("<I", npcs[tag].get("VTCK"))[0]
            vt = next(r.edid for gid, r, pf in ms.records("VTYP") if ms.local_formid(gid, plugin) == vt_fid)
            folder = a.out / "mod" / "sound" / "voice" / plugin.name.lower() / vt.lower()
            info["voice"] = export_voice(a.kotor2, c.voice, folder, ffmpeg=a.ffmpeg)
            info["voice_type"] = vt
            seq = a.out / "mod" / "seq"
            seq.mkdir(parents=True, exist_ok=True)
            (seq / plugin.name.replace(".esp", ".seq")).write_bytes(_s.pack("<I", c.quest.formid & 0xFFFFFF))
            res.setdefault("dialogue", []).append(info)
        results.append(res)
    out = plugin.write(a.out / plugin.name)
    print(json.dumps({"plugin": str(out), "areas": results}, indent=1, default=str))
    if a.install:
        from .meshes import install_mod
        import shutil
        files = install_mod(a.out, a.skyrim_data)
        shutil.copy2(out, Path(a.skyrim_data) / plugin.name)
        print(f"installed {len(files)} files and {plugin.name}")


def cmd_inspect(a):
    from .esp import read_plugin, read_zstring
    pf = read_plugin(a.plugin)
    print(f"{pf.name}: masters={pf.masters} flags=0x{pf.flags:X} records={pf.num_records}")
    for sig, recs in pf.records.items():
        print(f"== {sig} ({len(recs)})")
        for r in recs[: a.limit]:
            full = r.get("FULL")
            print(f"  {r.formid:08X} {r.edid:<40} {read_zstring(full) if full and not pf.localized else ''}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="k2s", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def step(name, fn, kotor=False):
        s = sub.add_parser(name, help=fn.__name__[4:])
        s.add_argument("--out", type=Path, required=name != "inspect", help="private output folder")
        if kotor:
            s.add_argument("--kotor2", required=True, help="KOTOR 2 folder (holds chitin.key and swkotor2.exe)")
        s.set_defaults(fn=fn)
        return s

    step("catalog", cmd_catalog, kotor=True)
    s = step("arsenal", cmd_arsenal)
    s.add_argument("--skyrim-data", required=True, help="Skyrim Special Edition's Data folder")
    s.add_argument("--masters", help="comma-separated masters (default Skyrim.esm,Update.esm,Dawnguard.esm)")
    s.add_argument("--no-esl", action="store_true", help="write a regular plugin instead of a light one")
    s.add_argument("--use-meshes", action="store_true",
                   help="point items at Data/meshes/kotor2/<model>.nif where it exists (from blender/obj_to_nif.py)")
    s = step("console", cmd_console)
    s.add_argument("--prefix", required=True, help="in-game ID prefix: FE001 for light plugin slot 001, or 5A")
    step("dialogue", cmd_dialogue, kotor=True)
    step("characters", cmd_characters)
    s = step("voice", cmd_voice, kotor=True)
    s.add_argument("--ffmpeg", default="ffmpeg")
    s.add_argument("--only", help="comma-separated character tags (e.g. kreia,atton)")
    s.add_argument("--limit", type=int, help="stop after this many lines (a quick test)")
    s = step("maps", cmd_maps, kotor=True)
    s.add_argument("--module", help="one module, e.g. 101per; default all")
    s.add_argument("--no-geometry", action="store_true", help="layout.json only")
    s = step("models", cmd_models, kotor=True)
    s.add_argument("--names", help="comma-separated model resrefs; default every weapon's model")
    s = step("meshes", cmd_meshes, kotor=True)
    s.add_argument("--skyrim-data", required=True, help="Skyrim Special Edition's Data folder (vanilla templates)")
    s.add_argument("--only", help="comma-separated model resrefs (e.g. w_lghtsbr_002)")
    s.add_argument("--install", action="store_true", help="also copy the mod folder into the Data folder")
    s = step("area", cmd_area, kotor=True)
    s.add_argument("--module", required=True, help="e.g. 101per")
    s.add_argument("--skyrim-data", required=True)
    s.add_argument("--install", action="store_true", help="copy meshes, textures and the plugin into Data")
    s.add_argument("--ffmpeg", default="ffmpeg")
    s = sub.add_parser("inspect", help="list a plugin's records")
    s.add_argument("plugin", type=Path)
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_inspect)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
