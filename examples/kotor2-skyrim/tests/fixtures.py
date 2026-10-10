"""Synthetic stand-ins for the two installs, made with PyKotor's writers and this package's own plugin writer.

No game data: every name, number and line here is invented for the tests. The KOTOR side is a real
install layout (chitin.key + BIFs, modules, override, dialog.tlk, StreamVoice) as PyKotor writes it;
the Skyrim side is three small masters shaped like Skyrim.esm / Update.esm / Dawnguard.esm.
"""
from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

from pykotor.common.language import LocalizedString
from pykotor.common.misc import Game, ResRef
from pykotor.resource.formats.gff import GFF, GFFContent, GFFList, bytes_gff
from pykotor.resource.formats.lyt import LYT, bytes_lyt
from pykotor.resource.formats.lyt.lyt_data import LYTRoom
from pykotor.resource.formats.twoda import TwoDA, bytes_2da
from pykotor.resource.type import ResourceType
from pykotor.tools.create_installation import create_installation
from utility.common.geometry import Vector3

from k2s.esp import Plugin, Record, zstring

TLK = ["Bad Strref",                      # 0
       "Lightsaber", "Double-Bladed Lightsaber", "Short Lightsaber", "Blaster Pistol", "Blaster Rifle",  # 1-5
       "Vibroblade", "Combat Suit", "Heavy Battle Armor", "Jedi Robe", "Claw", "Medpac",                   # 6-11
       "Damage Bonus", "Energy", "1d6", "2d6",                                                            # 12-15
       "Test Saber of Testing", "Kreia Test", "Vrook Test",                                               # 16-18
       "You are awake.", "Who are you?", "A teacher.", "Peragus Test Station", "Find a way out.",          # 19-23
       "The station is quiet.", "Wake Up"]                                                                # 24-25


def twoda(cols: list[str], rows: list[dict]) -> bytes:
    t = TwoDA(cols)
    for i, r in enumerate(rows):
        t.add_row(str(i), {c: str(r.get(c, "****")) for c in cols})
    return bytes_2da(t)


BASEITEMS = [
    {"label": "Lightsaber", "name": 1, "equipableslots": "0x00030", "numdice": 2, "dietoroll": 8, "critthreat": 2, "crithitmult": 2, "defaultmodel": "w_lghtsbr_001"},
    {"label": "Double_Bladed_Lightsaber", "name": 2, "equipableslots": "0x00010", "numdice": 2, "dietoroll": 10, "critthreat": 2, "crithitmult": 2, "defaultmodel": "w_dblsbr_001"},
    {"label": "Short_Lightsaber", "name": 3, "equipableslots": "0x00030", "numdice": 1, "dietoroll": 8, "critthreat": 2, "crithitmult": 2, "defaultmodel": "w_shrtsbr_001"},
    {"label": "Blaster_Pistol", "name": 4, "equipableslots": "0x00030", "rangedweapon": 1, "numdice": 1, "dietoroll": 6, "critthreat": 1, "crithitmult": 2, "defaultmodel": "w_blstrpstl_001"},
    {"label": "Blaster_Rifle", "name": 5, "equipableslots": "0x00010", "rangedweapon": 1, "numdice": 1, "dietoroll": 10, "critthreat": 1, "crithitmult": 2, "defaultmodel": "w_blstrrfl_001"},
    {"label": "Vibroblade", "name": 6, "equipableslots": "0x00030", "numdice": 1, "dietoroll": 8, "critthreat": 2, "crithitmult": 2, "defaultmodel": "w_vbroswrd_001"},
    {"label": "Armor_Class_4", "name": 7, "equipableslots": "0x00002", "baseac": 4},
    {"label": "Armor_Class_8", "name": 8, "equipableslots": "0x00002", "baseac": 8},
    {"label": "Jedi_Robe", "name": 9, "equipableslots": "0x00002", "baseac": 1},
    {"label": "Creature_Claw", "name": 10, "equipableslots": "0x00030", "numdice": 1, "dietoroll": 4},
    {"label": "Medpac", "name": 11, "equipableslots": "0x00000"},
]


def uti(name_ref: int, base: int, *, cost: int = 1000, variation: int = 1, damage_cost: int | None = None,
        name_text: str = "") -> bytes:
    g = GFF(GFFContent.UTI)
    r = g.root
    r.set_resref("TemplateResRef", ResRef(""))
    r.set_int32("BaseItem", base)
    loc = LocalizedString(name_ref)
    if name_text:
        loc = LocalizedString.from_english(name_text)
    r.set_locstring("LocalizedName", loc)
    r.set_locstring("DescIdentified", LocalizedString(-1))
    r.set_string("Tag", "")
    r.set_uint32("Cost", cost)
    r.set_uint8("ModelVariation", variation)
    props = r.set_list("PropertiesList", GFFList())
    if damage_cost is not None:
        p = props.add(0)
        p.set_uint16("PropertyName", 0)
        p.set_uint16("Subtype", 0)
        p.set_uint8("CostTable", 0)
        p.set_uint16("CostValue", damage_cost)
        p.set_uint8("Param1", 255)
        p.set_uint8("Param1Value", 0)
        p.set_uint8("ChanceAppear", 100)
    return bytes_gff(g, ResourceType.UTI)


def utc(tag: str, name_ref: int, conversation: str) -> bytes:
    g = GFF(GFFContent.UTC)
    r = g.root
    r.set_string("Tag", tag)
    r.set_locstring("FirstName", LocalizedString(name_ref))
    r.set_locstring("LastName", LocalizedString(-1))
    r.set_uint16("Appearance_Type", 0)
    r.set_uint8("Gender", 1)
    r.set_int16("MaxHitPoints", 120)
    r.set_resref("Conversation", ResRef(conversation))
    r.set_list("Equip_ItemList", GFFList())
    return bytes_gff(g, ResourceType.UTC)


def dlg() -> bytes:
    g = GFF(GFFContent.DLG)
    r = g.root
    entries = r.set_list("EntryList", GFFList())
    e0 = entries.add(0)
    e0.set_locstring("Text", LocalizedString(19))
    e0.set_string("Speaker", "")
    e0.set_resref("VO_ResRef", ResRef("kreia_vo01"))
    e0.set_resref("Script", ResRef(""))
    e0.set_string("Quest", "wakeup")
    e0.set_uint32("QuestEntry", 10)
    rl = e0.set_list("RepliesList", GFFList())
    link = rl.add(0)
    link.set_uint32("Index", 0)
    link.set_resref("Active", ResRef("c_has_saber"))
    link.set_uint8("IsChild", 0)
    e1 = entries.add(1)
    e1.set_locstring("Text", LocalizedString(21))
    e1.set_string("Speaker", "")
    e1.set_resref("VO_ResRef", ResRef("kreia_vo02"))
    e1.set_resref("Script", ResRef("a_give_saber"))
    e1.set_list("RepliesList", GFFList())
    replies = r.set_list("ReplyList", GFFList())
    p0 = replies.add(0)
    p0.set_locstring("Text", LocalizedString(20))
    el = p0.set_list("EntriesList", GFFList())
    el.add(0).set_uint32("Index", 1)
    starts = r.set_list("StartingList", GFFList())
    starts.add(0).set_uint32("Index", 0)
    r.set_resref("EndConversation", ResRef("k_end_kreia"))
    return bytes_gff(g, ResourceType.DLG)


def jrl() -> bytes:
    g = GFF(GFFContent.JRL)
    cats = g.root.set_list("Categories", GFFList())
    c = cats.add(0)
    c.set_locstring("Name", LocalizedString(25))
    c.set_string("Tag", "wakeup")
    c.set_uint32("Priority", 1)
    el = c.set_list("EntryList", GFFList())
    e = el.add(0)
    e.set_uint32("ID", 10)
    e.set_locstring("Text", LocalizedString(23))
    e.set_uint16("End", 0)
    e2 = el.add(1)
    e2.set_uint32("ID", 20)
    e2.set_locstring("Text", LocalizedString(24))
    e2.set_uint16("End", 1)
    return bytes_gff(g, ResourceType.JRL)


def ifo() -> bytes:
    g = GFF(GFFContent.IFO)
    r = g.root
    r.set_locstring("Mod_Name", LocalizedString(22))
    r.set_resref("Mod_Entry_Area", ResRef("101pera"))
    r.set_single("Mod_Entry_X", 1.0)
    r.set_single("Mod_Entry_Y", 2.0)
    r.set_single("Mod_Entry_Z", 0.0)
    al = r.set_list("Mod_Area_list", GFFList())
    al.add(6).set_resref("Area_Name", ResRef("101pera"))
    return bytes_gff(g, ResourceType.IFO)


def are() -> bytes:
    g = GFF(GFFContent.ARE)
    g.root.set_locstring("Name", LocalizedString(22))
    g.root.set_string("Tag", "101PERA")
    g.root.set_resref("OnEnter", ResRef("a_101_enter"))
    return bytes_gff(g, ResourceType.ARE)


def git() -> bytes:
    g = GFF(GFFContent.GIT)
    cl = g.root.set_list("Creature List", GFFList())
    c = cl.add(4)
    c.set_resref("TemplateResRef", ResRef("p_kreia"))
    c.set_single("XPosition", 10.0)
    c.set_single("YPosition", 0.0)
    c.set_single("ZPosition", 0.0)
    c.set_single("XOrientation", 0.0)
    c.set_single("YOrientation", 1.0)
    pl = g.root.set_list("Placeable List", GFFList())
    p = pl.add(9)
    p.set_resref("TemplateResRef", ResRef("footlker001"))
    p.set_single("X", 1.0)
    p.set_single("Y", 2.0)
    p.set_single("Z", 0.5)
    p.set_single("Bearing", 0.0)
    return bytes_gff(g, ResourceType.GIT)


def lyt() -> bytes:
    lay = LYT()
    lay.rooms.append(LYTRoom("101pera_01a", Vector3(0.0, 0.0, 0.0)))
    lay.rooms.append(LYTRoom("101pera_01b", Vector3(20.0, 0.0, 0.0)))
    return bytes_lyt(lay)


def tone_wav(seconds: float = 0.2, rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(int(seconds * rate))))
    return buf.getvalue()


def saber_mdl() -> bytes:
    """A two-node model: a hilt rotated 90 degrees about Z under a translated parent, and a blade.
    Returns (mdl, mdx) bytes."""
    from pykotor.resource.formats.mdl import MDL, write_mdl
    from pykotor.resource.formats.mdl.mdl_data import MDLFace, MDLMesh, MDLNode
    from pykotor.resource.formats.mdl.mdl_types import MDLNodeType
    from utility.common.geometry import Vector2, Vector4

    def mesh_node(name, texture, pos, rot):
        n = MDLNode()
        n.name, n.node_type = name, MDLNodeType.TRIMESH
        n.position, n.orientation = Vector3(*pos), Vector4(*rot)
        me = MDLMesh()
        me.texture_1 = texture
        me.vertex_positions = [Vector3(0, 0, 0), Vector3(1, 0, 0), Vector3(0, 1, 0)]
        me.vertex_normals = [Vector3(0, 0, 1)] * 3
        me.vertex_uv1 = [Vector2(0, 0), Vector2(1, 0), Vector2(0, 1)]
        f = MDLFace()
        f.v1, f.v2, f.v3 = 0, 1, 2
        me.faces = [f]
        n.mesh = me
        return n

    m = MDL()
    m.name = m.root.name = "w_lghtsbr_001"
    parent = MDLNode()
    parent.name, parent.position = "base", Vector3(0, 0, 1)
    s = math.sqrt(0.5)
    parent.children.append(mesh_node("hilt", "w_hilt01", (0, 0, 0), (0, 0, s, s)))
    m.root.children.append(parent)
    m.root.children.append(mesh_node("blade_01", "w_blade_blu", (0, 0, 0.3), (0, 0, 0, 1)))
    mdl, mdx = bytearray(), bytearray()
    write_mdl(m, mdl, target_ext=mdx)
    return bytes(mdl), bytes(mdx)


def make_kotor2(root: Path) -> Path:
    two_das = {
        "baseitems.2da": twoda(["label", "name", "equipableslots", "rangedweapon", "numdice", "dietoroll", "critthreat",
                                "crithitmult", "baseac", "defaultmodel"], BASEITEMS),
        "itempropdef.2da": twoda(["label", "name", "subtyperesref", "costtableresref"],
                                 [{"label": "Damage_Bonus", "name": 12, "subtyperesref": "iprp_damagetype"}]),
        "iprp_costtable.2da": twoda(["label", "name"], [{"label": "IPRP_DAMAGECOST", "name": "iprp_damagecost"}]),
        "iprp_damagecost.2da": twoda(["label", "name", "numdice", "die"],
                                     [{"label": "none", "name": 0, "numdice": 0, "die": 0},
                                      {"label": "1d6", "name": 14, "numdice": 1, "die": 6},
                                      {"label": "2d6", "name": 15, "numdice": 2, "die": 6}]),
        "iprp_damagetype.2da": twoda(["label", "name"], [{"label": "Energy", "name": 13}]),
    }
    templates = {
        "g_w_lghtsbr01.uti": uti(1, 0, cost=2000, variation=1),
        "g_w_lghtsbr02.uti": uti(1, 0, cost=2000, variation=2),
        "g_w_lghtsbr99.uti": uti(16, 0, cost=9000, variation=3, damage_cost=2),
        "g_w_dblsbr01.uti": uti(2, 1, cost=4000),
        "g_w_shortsbr01.uti": uti(3, 2, cost=1500),
        "g_w_blstrpstl001.uti": uti(4, 3, cost=200),
        "g_w_blstrpstl002.uti": uti(4, 3, cost=200),   # an exact duplicate: deduped
        "g_w_blstrrfl001.uti": uti(5, 4, cost=500, damage_cost=1),
        "g_w_vbroblde01.uti": uti(6, 5, cost=300),
        "g_a_class4001.uti": uti(7, 6, cost=400),
        "g_a_class8001.uti": uti(8, 7, cost=3000),
        "g_a_jedirobe01.uti": uti(9, 8, cost=800),
        "g_w_crclaw01.uti": uti(10, 9, cost=0),
        "g_i_medeqpmnt01.uti": uti(11, 10, cost=50),
        "p_kreia.utc": utc("kreia", 17, "kreia"),
        "n_vrook.utc": utc("vrook", 18, ""),
        "kreia.dlg": dlg(),
    }
    templates["w_lghtsbr_001.mdl"], templates["w_lghtsbr_001.mdx"] = saber_mdl()
    module = {"module.ifo": ifo(), "101pera.are": are(), "101pera.git": git(), "101pera.lyt": lyt()}
    create_installation(root, Game.K2, bif_resources={"templates.bif": templates}, override_resources=two_das,
                        modules_resources={"101per.rim": module}, dialog_entries=TLK)
    (root / "override" / "global.jrl").write_bytes(jrl())
    voice = root / "StreamVoice" / "AVO" / "kreia"
    voice.mkdir(parents=True, exist_ok=True)
    (voice / "kreia_vo01.wav").write_bytes(tone_wav())
    (voice / "kreia_vo02.wav").write_bytes(b"\xff\xf3\x60\xc4" + b"\0" * 466 + tone_wav())  # 470-byte SFX header
    return root


# ---------------------------------------------------------------- Skyrim side

def _rec(sig: str, formid: int, edid: str, **subs: bytes) -> Record:
    r = Record(sig, formid)
    r.add("EDID", zstring(edid))
    for k, v in subs.items():
        r.add(k, v)
    return r


def weapon_dnam(anim: int, speed: float = 1.0, reach: float = 1.0, skill: int = 6) -> bytes:
    d = bytearray(100)
    d[0] = anim
    struct.pack_into("<ff", d, 4, speed, reach)
    d[25] = 0xFF
    struct.pack_into("<i", d, 76, skill)
    struct.pack_into("<i", d, 88, -1)
    return bytes(d)


def _write_master(path: Path, masters: list[str], records: list[Record]):
    p = Plugin(path.name, masters, esm=True)
    p.records = records
    p.write(path)


def make_skyrim_data(data: Path) -> Path:
    data.mkdir(parents=True, exist_ok=True)
    kw = lambda *ids: struct.pack(f"<{len(ids)}I", *ids)  # noqa: E731
    obnd = struct.pack("<6h", -5, -5, 0, 5, 5, 90)
    crdt = struct.pack("<HHfB7xI4x", 3, 0, 1.0, 0, 0)
    skyrim = [
        _rec("KYWD", 0x01E711, "WeapTypeSword", CNAM=bytes(4)),
        _rec("KYWD", 0x01E713, "WeapTypeDagger", CNAM=bytes(4)),
        _rec("KYWD", 0x0A0001, "ArmorLight", CNAM=bytes(4)),
        _rec("SNDR", 0x0A0010, "WPNSwingBlade"),
        _rec("WEAP", 0x013989, "SteelSword", OBND=obnd, MODL=zstring("Weapons\\Steel\\SteelSword.nif"),
             ETYP=kw(0x013F44), KSIZ=struct.pack("<I", 1), KWDA=kw(0x01E711), SNAM=kw(0x0A0010),
             DATA=struct.pack("<IfH", 45, 10.0, 8), DNAM=weapon_dnam(1), CRDT=crdt, VNAM=struct.pack("<I", 1)),
        _rec("WEAP", 0x01398E, "SteelDagger", OBND=obnd, MODL=zstring("Weapons\\Steel\\SteelDagger.nif"),
             KSIZ=struct.pack("<I", 1), KWDA=kw(0x01E713), DATA=struct.pack("<IfH", 18, 2.5, 5),
             DNAM=weapon_dnam(2, 1.3, 0.7), CRDT=crdt),
        _rec("WEAP", 0x013988, "SteelMace", OBND=obnd, MODL=zstring("Weapons\\Steel\\SteelMace.nif"),
             DATA=struct.pack("<IfH", 65, 18.0, 10), DNAM=weapon_dnam(4, 0.8), CRDT=crdt),
        _rec("WEAP", 0x013987, "SteelGreatsword", OBND=obnd, MODL=zstring("Weapons\\Steel\\SteelGreatsword.nif"),
             DATA=struct.pack("<IfH", 90, 20.0, 17), DNAM=weapon_dnam(5, 0.75, 1.3, 7), CRDT=crdt),
        _rec("ARMO", 0x03619E, "ArmorLeatherCuirass", OBND=obnd, MOD2=zstring("Armor\\Leather\\CuirassGND.nif"),
             BODT=struct.pack("<IB3xI", 0x4, 0, 0), KSIZ=struct.pack("<I", 1), KWDA=kw(0x0A0001),
             DESC=zstring(""), MODL=kw(0x0A0100), DATA=struct.pack("<if", 125, 6.0), DNAM=struct.pack("<i", 2600)),
        _rec("ARMO", 0x013952, "ArmorSteelCuirassA", OBND=obnd, BOD2=struct.pack("<II", 0x4, 1),
             DESC=zstring(""), MODL=kw(0x0A0101), DATA=struct.pack("<if", 275, 35.0), DNAM=struct.pack("<i", 3100)),
        _rec("ARMO", 0x013953, "ArmorLeatherHelmet", OBND=obnd, BOD2=struct.pack("<II", 0x3, 0),
             DESC=zstring(""), MODL=kw(0x0A0102), DATA=struct.pack("<if", 60, 2.0), DNAM=struct.pack("<i", 1200)),
        _rec("ARMO", 0x013954, "ArmorLeatherGauntlets", OBND=obnd, BOD2=struct.pack("<II", 0x8, 0),
             DESC=zstring(""), MODL=kw(0x0A0103), DATA=struct.pack("<if", 25, 2.0), DNAM=struct.pack("<i", 700)),
        _rec("CONT", 0x0A0200, "TreasChestTest", OBND=obnd, MODL=zstring("Clutter\\Containers\\Chest01.nif"),
             DATA=struct.pack("<Bf", 0, 0.0), SNAM=kw(0x0A0010)),
    ]
    _write_master(data / "Skyrim.esm", [], skyrim)
    # Update.esm overrides SteelSword's damage (its FormID's index 00 = Skyrim.esm).
    upd = _rec("WEAP", 0x013989, "SteelSword", OBND=obnd, MODL=zstring("Weapons\\Steel\\SteelSword.nif"),
               KSIZ=struct.pack("<I", 1), KWDA=kw(0x01E711), DATA=struct.pack("<IfH", 45, 10.0, 9),
               DNAM=weapon_dnam(1), CRDT=crdt)
    _write_master(data / "Update.esm", ["Skyrim.esm"], [upd])
    # Dawnguard lists only Skyrim.esm as master, so its own records are index 01 inside it.
    dg = [
        _rec("PROJ", 0x01000800, "DLC1CrossbowBoltProjectile"),
        _rec("AMMO", 0x01000801, "DLC1SteelBolt", OBND=obnd, MODL=zstring("Weapons\\Bolt.nif"),
             KSIZ=struct.pack("<I", 1), KWDA=kw(0x01E711), DATA=struct.pack("<IIfIf", 0x01000800, 0, 10.0, 2, 0.0)),
        _rec("AMMO", 0x01000802, "DLC1IronArrowTest", DATA=struct.pack("<IIfIf", 0, 0x4, 8.0, 1, 0.0)),
        _rec("WEAP", 0x01000803, "DLC1Crossbow", OBND=obnd, MODL=zstring("DLC01\\Weapons\\Crossbow.nif"),
             ETYP=kw(0x013F45), KSIZ=struct.pack("<I", 1), KWDA=kw(0x01E711), SNAM=kw(0x0A0010),
             DATA=struct.pack("<IfH", 120, 14.0, 19), DNAM=weapon_dnam(9, 1.0, 1.0, 8), CRDT=crdt),
    ]
    _write_master(data / "Dawnguard.esm", ["Skyrim.esm"], dg)
    return data
