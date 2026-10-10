"""End-to-end tests on synthetic installs. Run from examples/kotor2-skyrim:

    uv run --with pykotor==2.3.12 --with pytest pytest -q tests
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import make_kotor2, make_skyrim_data  # noqa: E402

from k2s import arsenal, characters, dialogue, esp, stats, voice  # noqa: E402
from k2s.catalog import Catalog  # noqa: E402
from k2s.kotor import K2Install  # noqa: E402
from k2s.skyrim import MasterSet  # noqa: E402


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("k2s")
    k = K2Install(make_kotor2(root / "kotor2"))
    data = make_skyrim_data(root / "Skyrim" / "Data")
    cat = Catalog(k).build()
    return {"root": root, "k": k, "data": data, "cat": cat, "out": root / "out"}


# ---------------------------------------------------------------- plugin format

def test_plugin_round_trip_and_xxxx(tmp_path):
    p = esp.Plugin("T.esp", ["Skyrim.esm"], esl=True)
    r = p.new_record("WEAP", "K2Test")
    r.add("DESC", b"x" * 70000 + b"\0")  # needs the XXXX escape
    r.add("DATA", struct.pack("<IfH", 1, 2.0, 3))
    p.write(tmp_path / "T.esp")
    pf = esp.read_plugin(tmp_path / "T.esp")
    assert pf.masters == ["Skyrim.esm"] and pf.flags & esp.FLAG_ESL
    assert pf.num_records == 2  # one group + one record
    w = pf.records["WEAP"][0]
    assert w.formid == 0x01000800 and w.edid == "K2Test"
    assert len(w.get("DESC")) == 70001 and w.get("DATA") == struct.pack("<IfH", 1, 2.0, 3)


def test_compressed_records_are_read(tmp_path):
    import zlib
    body = esp.Subrecord("EDID", esp.zstring("Packed")).to_bytes()
    comp = struct.pack("<I", len(body)) + zlib.compress(body)
    rec = b"KYWD" + struct.pack("<IIIIHH", len(comp), esp.FLAG_COMPRESSED, 0x123, 0, 44, 0) + comp
    grp = b"GRUP" + struct.pack("<I", 24 + len(rec)) + b"KYWD" + struct.pack("<iII", 0, 0, 0) + rec
    hdr = esp.Record("TES4", 0).add("HEDR", struct.pack("<fII", 1.71, 2, 0x800)).to_bytes()
    (tmp_path / "C.esm").write_bytes(hdr + grp)
    assert esp.read_plugin(tmp_path / "C.esm").records["KYWD"][0].edid == "Packed"


def test_esl_overflow():
    p = esp.Plugin("T.esp", [], esl=True)
    for _ in range(2048):
        p.new_formid()
    with pytest.raises(OverflowError):
        p.new_formid()


# ---------------------------------------------------------------- KOTOR side

def test_catalog_classifies_items(world):
    items = {i["resref"]: i for i in world["cat"]["items"]}
    assert items["g_w_lghtsbr01"]["class"] == "lightsaber" and items["g_w_lghtsbr01"]["name"] == "Lightsaber"
    assert items["g_w_lghtsbr01"]["colour"] == "blue" and items["g_w_lghtsbr02"]["colour"] == "red"
    assert items["g_w_dblsbr01"]["kind"] == "double" and items["g_w_dblsbr01"]["hands"] == 2
    assert items["g_w_shortsbr01"]["kind"] == "short"
    assert items["g_w_blstrpstl001"]["class"] == "ranged" and items["g_w_blstrpstl001"]["kind"] == "pistol"
    assert items["g_w_blstrrfl001"]["kind"] == "rifle"
    assert items["g_w_vbroblde01"]["class"] == "melee"
    assert items["g_a_class4001"]["class"] == "armor" and items["g_a_class4001"]["armor_class"] == 4
    assert items["g_a_class8001"]["armor_class"] == 8
    assert items["g_a_jedirobe01"]["class"] == "robe"
    assert items["g_w_crclaw01"]["class"] == "creature_weapon"
    assert items["g_i_medeqpmnt01"]["class"] == "misc"
    # Damage Bonus: Energy 2d6 read through itempropdef -> iprp_costtable -> iprp_damagecost
    best = items["g_w_lghtsbr99"]
    assert best["damage_bonus_avg"] == 7.0 and best["dice"] == [2, 8]
    assert "Damage Bonus: Energy 2d6" in best["properties"][0]["text"]


def test_catalog_other_content(world):
    cat = world["cat"]
    assert {c["tag"] for c in cat["creatures"]} == {"kreia", "vrook"}
    assert cat["journal"][0]["tag"] == "wakeup" and [e["id"] for e in cat["journal"][0]["entries"]] == [10, 20]
    mod = next(m for m in cat["modules"] if m["module"] == "101per")
    assert mod["name"] == "Peragus Test Station" and mod["areas"] == ["101pera"]
    assert cat["dialogues"] == ["kreia"]


def test_dialogue_tree_and_scripts(world):
    conv = dialogue.conversation(world["k"], "kreia")
    assert conv["entries"][0]["text"] == "You are awake." and conv["entries"][0]["vo_resref"] == "kreia_vo01"
    assert conv["entries"][0]["next"][0] == {"to": 0, "active": "c_has_saber"}
    assert conv["replies"][0]["text"] == "Who are you?"
    used = dialogue.scripts_used(conv)
    assert used[("condition", "c_has_saber")] == 1 and used[("action", "a_give_saber")] == 1
    assert used[("action", "k_end_kreia")] == 1
    md = dialogue.readable(conv)
    assert "**PLAYER** #0" in md and "[if c_has_saber]" in md and "journal wakeup#10" in md
    q = dialogue.journal_to_quests(world["cat"]["journal"])[0]
    assert q["editor_id"] == "K2Q_Wakeup" and q["stages"][1]["completes"]


def test_characters_and_voice(world, tmp_path):
    convs = {"kreia": dialogue.conversation(world["k"], "kreia")}
    res = characters.build(world["cat"], convs)
    kreia = res["characters"][0]
    assert kreia["tag"] == "kreia" and kreia["companion"] and kreia["voice_type"] == "K2VoiceKreiaTest"
    assert [l["vo"] for l in kreia["lines"]] == ["kreia_vo01", "kreia_vo02"]
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not on PATH")
    out = voice.export(world["k"].path, res, tmp_path)
    assert out["lines"] == 2 and out["missing_audio"] == 0
    import wave
    for m in json.loads((tmp_path / "voice" / "manifest.json").read_text()):
        with wave.open(str(tmp_path / "voice" / m["wav"])) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 44100)
    assert "xWMAEncode.exe" in (tmp_path / "voice" / "encode_voice.bat").read_text()


def test_fuz_round_trip():
    lip, xwm = voice.unpack_fuz(voice.pack_fuz(b"XWMA-data", b"LIP"))
    assert (lip, xwm) == (b"LIP", b"XWMA-data")


def test_maps_layout(world, tmp_path):
    from k2s.maps import export_area, module_areas
    assert module_areas(world["k"], "101per") == ["101pera"]
    r = export_area(world["k"], "101per", "101pera", tmp_path, geometry=False)
    assert [room["model"] for room in r["rooms"]] == ["101pera_01a", "101pera_01b"]
    assert r["rooms"][1]["skyrim"]["pos"] == [1400.0, 0.0, 0.0]
    kreia = next(p for p in r["placements"] if p["template"] == "p_kreia")
    assert kreia["kind"] == "creature" and kreia["skyrim"]["rot_z"] == pytest.approx(0.0, abs=1e-6)  # facing north
    box = next(p for p in r["placements"] if p["kind"] == "placeable")
    assert box["skyrim"]["pos"] == [70.0, 140.0, 35.0]
    assert box["skyrim"]["rot_z"] == pytest.approx(1.570796, abs=1e-5)  # facing east
    assert json.loads((tmp_path / "layout.json").read_text())["name"] == "Peragus Test Station"


def test_model_export(world, tmp_path):
    from k2s.models import export_model
    r = export_model(world["k"], "w_lghtsbr_001", tmp_path)
    assert r["parts"] == 2 and r["textures"] == ["w_blade_blu", "w_hilt01"]
    obj = (tmp_path / "w_lghtsbr_001.obj").read_text().splitlines()
    verts = [tuple(round(float(x), 4) for x in l.split()[1:]) for l in obj if l.startswith("v ")]
    # hilt: rotated 90 degrees about Z, then lifted 1 m by its parent
    assert verts == [(0.0, 0.0, 1.0), (0.0, 1.0, 1.0), (-1.0, 0.0, 1.0)]
    assert "f 1/1/1 2/2/2 3/3/3" in obj and "mtllib w_lghtsbr_001.mtl" in obj
    blade = (tmp_path / "w_lghtsbr_001_blade.obj").read_text()
    assert "usemtl w_blade_blu" in blade and "v 0.000000 0.000000 0.300000" in blade
    assert "map_Kd textures/w_hilt01.dds" in (tmp_path / "w_lghtsbr_001.mtl").read_text()


# ---------------------------------------------------------------- stats

def test_stats_follow_skyrim_curve():
    weak = {"class": "lightsaber", "kind": "standard", "dice": [2, 8], "cost": 2000}
    strong = {"class": "lightsaber", "kind": "standard", "dice": [2, 8], "damage_bonus_avg": 7.0, "cost": 9000}
    rng = stats.ranges([weak, strong], stats.archetype_key, stats.weapon_power)
    a, b = stats.weapon_stats(weak, rng), stats.weapon_stats(strong, rng)
    assert (a["damage"], b["damage"]) == stats.ARCHETYPES["lightsaber/standard"].damage
    assert a["ignores_resistance"] and a["anim"] == stats.ANIM_ONE_HAND_SWORD and b["value"] == 900


# ---------------------------------------------------------------- the arsenal plugin

def test_arsenal_plugin(world):
    ms = MasterSet(world["data"])
    s = arsenal.build(world["cat"], ms, world["out"])
    pf = esp.read_plugin(s["plugin"])
    assert pf.masters == ["Skyrim.esm", "Update.esm", "Dawnguard.esm"] and pf.flags & esp.FLAG_ESL
    weaps = {r.edid: r for r in pf.records["WEAP"]}
    armos = {r.edid: r for r in pf.records["ARMO"]}
    # 9 lightsaber/melee/ranged templates minus one duplicate pistol; the claw is not loot
    assert len(weaps) == 8 and "K2W_GWCrclaw01" not in weaps
    assert set(armos) == {"K2A_GAClass4001", "K2A_GAClass8001", "K2A_GAJedirobe01"}

    def full(r):
        return esp.read_zstring(r.get("FULL"))

    saber = weaps["K2W_GWLghtsbr01"]
    assert full(saber) == "Lightsaber (blue)"
    dnam = saber.get("DNAM")
    assert dnam[0] == 1 and struct.unpack_from("<ff", dnam, 4) == pytest.approx((1.15, 1.0))
    assert struct.unpack_from("<H", dnam, 12)[0] & 0x1  # ignores normal weapon resistance
    value, weight, dmg = struct.unpack("<IfH", saber.get("DATA"))
    assert dmg == 12 and value == 200
    best = weaps["K2W_GWLghtsbr99"]
    assert struct.unpack("<IfH", best.get("DATA"))[2] == 18
    # template data comes from Update.esm's override of SteelSword; its keyword stays a Skyrim.esm FormID
    kws = struct.unpack("<2I", saber.get("KWDA"))
    assert kws[0] == 0x0001E711 and kws[1] >> 24 == 3 and saber.get("MODL").startswith(b"Weapons\\Steel")
    assert saber.get("SNAM") is None  # Update.esm's override has no attack sound; the override wins
    # blasters: the Dawnguard crossbow, its own FormIDs remapped from index 01 (in Dawnguard) to 02 (here)
    pistol = weaps["K2W_GWBlstrpstl001"]
    assert pistol.get("DNAM")[0] == 9 and pistol.get("MODL").startswith(b"DLC01")
    assert struct.unpack("<I", pistol.get("ETYP"))[0] == 0x00013F45
    assert struct.unpack("<I", pistol.get("SNAM"))[0] == 0x000A0010
    cell = pf.records["AMMO"][0]
    assert cell.edid == "K2PowerCell" and struct.unpack_from("<I", cell.get("DATA"))[0] == 0x02000800
    double = weaps["K2W_GWDblsbr01"]
    assert double.get("DNAM")[0] == 5
    # armour: BODT (LE-style) template rewritten as BOD2, armature FormIDs kept
    heavy = armos["K2A_GAClass8001"]
    assert struct.unpack("<II", heavy.get("BOD2")) == (0x4, 1)
    assert struct.unpack("<i", heavy.get("DNAM"))[0] == 3800  # the only heavy armour: middle of 28-49
    robe = armos["K2A_GAJedirobe01"]
    assert struct.unpack("<II", robe.get("BOD2")) == (0x4, 0) and struct.unpack("<I", robe.get("MODL"))[0] == 0x000A0100
    # footlocker holds everything
    box = pf.records["CONT"][0]
    assert struct.unpack("<I", box.get("COCT"))[0] == 1 + 8 + 3
    # with --use-meshes, a converted saber mesh replaces the template's model and 1st-person object
    meshes = world["root"] / "meshes"
    meshes.mkdir(exist_ok=True)
    (meshes / "w_lghtsbr_001.nif").write_bytes(b"")
    s2 = arsenal.build(world["cat"], ms, world["root"] / "out2", meshes=meshes)
    w2 = {r.edid: r for r in esp.read_plugin(s2["plugin"]).records["WEAP"]}
    assert w2["K2W_GWLghtsbr01"].get("MODL") == b"kotor2\\w_lghtsbr_001.nif\0"
    assert w2["K2W_GWLghtsbr01"].get("WNAM") is None and w2["K2W_GWLghtsbr02"].get("MODL").startswith(b"Weapons")
    lines = arsenal.console_batch(json.loads((world["out"] / "arsenal.json").read_text()), "FE001")
    box_obj = box.formid & 0xFFF
    assert lines.startswith(f"player.placeatme FE001{box_obj:03X} 1")
