"""Skyrim SE weapon NIFs (20.2.0.7, user version 12, BS version 100) built on a vanilla template.

The template is a vanilla weapon mesh read from the user's own archives (steel sword, greatsword,
dagger, mace). Its root BSFadeNode, BSX flags, the `Prn` string that says where the weapon hangs, and its
Havok collision are kept; its BSTriShapes and their shader blocks are dropped and replaced by the converted
KOTOR parts:
- `mesh` parts: BSTriShape + BSLightingShaderProperty (default shader) + BSShaderTextureSet.
- `blade` parts: BSTriShape + BSEffectShaderProperty (the crystal texture, additive, unlit) + NiAlphaProperty.
  KOTOR's blade textures are colour on black, which additive blending turns into a glow.

Layouts were read off vanilla meshes (see tests and MODLOG) and nif.xml:
- BSTriShape (SSE): NiAVObject (name, extra list, controller, flags u32, translation, 3x3 rotation, scale,
  collision ref), bounding sphere (4 floats), skin/shader/alpha refs, vertex desc u64, triangles u16,
  vertices u16, data size u32, vertex data, triangles (3 x u16), particle data size u32.
- vertex desc: low nibble = vertex size / 4; attribute n's offset / 4 in nibble n+1 (UV n=1, normal n=3,
  tangent n=4); attribute flags << 44 (vertex 0x1, UV 0x2, normal 0x8, tangent 0x10). SSE positions are
  always 3 floats plus the bitangent's X as a float; UVs are half floats; normal and tangent are 3 bytes each
  (-1..1 mapped to 0..255) with the bitangent's Y and Z in the fourth byte.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

HEADER = b"Gamebryo File Format, Version 20.2.0.7\n"
NIF_VERSION, USER_VERSION, BS_VERSION = 0x14020007, 12, 100
SHAPE_TYPES = {"BSTriShape", "NiTriShape", "BSLightingShaderProperty", "BSEffectShaderProperty",
               "BSShaderTextureSet", "NiAlphaProperty", "NiTriShapeData", "NiSkinInstance", "NiSkinData",
               "NiSkinPartition", "BSDismemberSkinInstance"}

# Hilt: vanilla steel sword's SLSF1 (0x82400381) without Environment_Mapping (0x80), and its SLSF2
# (0x00008021) without Vertex_Colors (0x20): KOTOR meshes carry neither a cube map nor vertex colours.
LIGHTING_FLAGS1 = 0x82400301
LIGHTING_FLAGS2 = 0x00008001
# Blade: SLSF1 ZBuffer_Test (0x80000000) | Own_Emit (0x00400000); SLSF2 Double_Sided (0x10).
EFFECT_FLAGS1 = 0x80400000
EFFECT_FLAGS2 = 0x00000010
ALPHA_ADDITIVE = 0x0001  # blending on, src ONE, dst ONE
ALPHA_BLEND = 0x00ED     # blending on, src SRC_ALPHA, dst INV_SRC_ALPHA
ALPHA_TEST = 0x1200      # alpha test on, GREATER than the threshold
ALPHA_MODES = {"additive": (ALPHA_ADDITIVE, 0), "blend": (ALPHA_BLEND, 0), "test": (ALPHA_TEST, 128)}


@dataclass
class Nif:
    header_strings: list[bytes]   # author, process script, export script
    strings: list[str]
    blocks: list[tuple[str, bytes]]
    roots: list[int]

    def string_index(self, s: str) -> int:
        if s not in self.strings:
            self.strings.append(s)
        return self.strings.index(s)


def read(data: bytes) -> Nif:
    i = data.index(b"\n") + 1
    ver, _endian, user, nblocks, bsver = struct.unpack_from("<IBIII", data, i)
    if ver != NIF_VERSION or user != USER_VERSION or bsver != BS_VERSION:
        raise ValueError(f"not a Skyrim SE NIF (version {ver:#x}, user {user}, bs {bsver})")
    i += 17
    hs = []
    for _ in range(3):
        n = data[i]
        hs.append(data[i + 1:i + n])
        i += 1 + n
    (ntypes,) = struct.unpack_from("<H", data, i)
    i += 2
    types = []
    for _ in range(ntypes):
        (n,) = struct.unpack_from("<I", data, i)
        types.append(data[i + 4:i + 4 + n].decode("latin-1"))
        i += 4 + n
    idx = struct.unpack_from(f"<{nblocks}H", data, i)
    i += 2 * nblocks
    sizes = struct.unpack_from(f"<{nblocks}I", data, i)
    i += 4 * nblocks
    nstr, _ = struct.unpack_from("<II", data, i)
    i += 8
    strings = []
    for _ in range(nstr):
        (n,) = struct.unpack_from("<I", data, i)
        strings.append(data[i + 4:i + 4 + n].decode("latin-1"))
        i += 4 + n
    (ngroups,) = struct.unpack_from("<I", data, i)
    i += 4 + 4 * ngroups
    blocks = []
    for k in range(nblocks):
        blocks.append((types[idx[k] & 0x7FFF], data[i:i + sizes[k]]))
        i += sizes[k]
    (nroots,) = struct.unpack_from("<I", data, i)
    roots = list(struct.unpack_from(f"<{nroots}i", data, i + 4))
    return Nif(hs, strings, blocks, roots)


def write(nif: Nif) -> bytes:
    types: list[str] = []
    for t, _ in nif.blocks:
        if t not in types:
            types.append(t)
    out = bytearray(HEADER)
    out += struct.pack("<IBIII", NIF_VERSION, 1, USER_VERSION, len(nif.blocks), BS_VERSION)
    for s in nif.header_strings:
        out += bytes([len(s) + 1]) + s + b"\0"
    out += struct.pack("<H", len(types))
    for t in types:
        out += struct.pack("<I", len(t)) + t.encode("latin-1")
    out += struct.pack(f"<{len(nif.blocks)}H", *(types.index(t) for t, _ in nif.blocks))
    out += struct.pack(f"<{len(nif.blocks)}I", *(len(b) for _, b in nif.blocks))
    out += struct.pack("<II", len(nif.strings), max((len(s) for s in nif.strings), default=0))
    for s in nif.strings:
        out += struct.pack("<I", len(s)) + s.encode("latin-1")
    out += struct.pack("<I", 0)
    for _, b in nif.blocks:
        out += b
    out += struct.pack(f"<I{len(nif.roots)}i", len(nif.roots), *nif.roots)
    return bytes(out)


# ------------------------------------------------------------------ blocks
def _sized(s: str) -> bytes:
    b = s.encode("latin-1")
    return struct.pack("<I", len(b)) + b


def _avobject(name: int, flags: int = 0x0E) -> bytes:
    return struct.pack("<iIiI3f9ffi", name, 0, -1, flags, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0, -1)


def _unit_byte(x: float) -> int:
    return max(0, min(255, int(round((x + 1.0) * 127.5))))


def _tangents(verts, uvs, normals, faces):
    """Per-vertex tangent and bitangent from UVs (Lengyel); falls back to any vector perpendicular to n."""
    n = len(verts)
    tan = [[0.0, 0.0, 0.0] for _ in range(n)]
    bit = [[0.0, 0.0, 0.0] for _ in range(n)]
    for a, b, c in faces:
        p0, p1, p2 = verts[a], verts[b], verts[c]
        u0, u1, u2 = uvs[a], uvs[b], uvs[c]
        e1 = [p1[k] - p0[k] for k in range(3)]
        e2 = [p2[k] - p0[k] for k in range(3)]
        du1, dv1, du2, dv2 = u1[0] - u0[0], u1[1] - u0[1], u2[0] - u0[0], u2[1] - u0[1]
        r = du1 * dv2 - du2 * dv1
        if abs(r) < 1e-12:
            continue
        r = 1.0 / r
        t = [(e1[k] * dv2 - e2[k] * dv1) * r for k in range(3)]
        s = [(e2[k] * du1 - e1[k] * du2) * r for k in range(3)]
        for v in (a, b, c):
            for k in range(3):
                tan[v][k] += t[k]
                bit[v][k] += s[k]

    def norm(v, fallback):
        m = math.sqrt(sum(x * x for x in v))
        return [x / m for x in v] if m > 1e-9 else fallback

    out_t, out_b = [], []
    for i in range(n):
        nrm = normals[i]
        t = tan[i]
        d = sum(t[k] * nrm[k] for k in range(3))
        t = norm([t[k] - nrm[k] * d for k in range(3)], [1.0, 0.0, 0.0] if abs(nrm[0]) < 0.9 else [0.0, 1.0, 0.0])
        b = norm(bit[i], [nrm[1] * t[2] - nrm[2] * t[1], nrm[2] * t[0] - nrm[0] * t[2], nrm[0] * t[1] - nrm[1] * t[0]])
        out_t.append(t)
        out_b.append(b)
    return out_t, out_b


def tri_shape(name: int, verts, uvs, normals, faces, shader: int, alpha: int) -> bytes:
    """A BSTriShape with position, UV, normal and tangent data (28 bytes per vertex)."""
    if len(verts) > 0xFFFF or len(faces) > 0xFFFF:
        raise ValueError("too many vertices or triangles for one BSTriShape")
    if len(normals) != len(verts):
        normals = [(0.0, 0.0, 1.0)] * len(verts)
    if len(uvs) != len(verts):
        uvs = [(0.0, 0.0)] * len(verts)
    tangents, bitangents = _tangents(verts, uvs, normals, faces)
    cx = [sum(v[k] for v in verts) / max(1, len(verts)) for k in range(3)]
    radius = max((math.dist(v, cx) for v in verts), default=0.0)
    desc = 7 | (4 << 8) | (5 << 16) | (6 << 20) | (0x1B << 44)
    vdata = bytearray()
    for v, uv, nrm, t, b in zip(verts, uvs, normals, tangents, bitangents):
        vdata += struct.pack("<4f", v[0], v[1], v[2], b[0])
        vdata += struct.pack("<2e", uv[0], uv[1])
        vdata += bytes([_unit_byte(nrm[0]), _unit_byte(nrm[1]), _unit_byte(nrm[2]), _unit_byte(b[1])])
        vdata += bytes([_unit_byte(t[0]), _unit_byte(t[1]), _unit_byte(t[2]), _unit_byte(b[2])])
    tris = b"".join(struct.pack("<3H", *f) for f in faces)
    return (_avobject(name) + struct.pack("<4f", *cx, radius) + struct.pack("<3i", -1, shader, alpha)
            + struct.pack("<QHHI", desc, len(faces), len(verts), len(vdata) + len(tris)) + vdata + tris
            + struct.pack("<I", 0))


def lighting_shader(texture_set: int) -> bytes:
    """Default (type 0) BSLightingShaderProperty, values as vanilla weapons use them."""
    return (struct.pack("<IiIi", 0, -1, 0, -1) + struct.pack("<II", LIGHTING_FLAGS1, LIGHTING_FLAGS2)
            + struct.pack("<4f", 0, 0, 1, 1) + struct.pack("<i", texture_set)
            + struct.pack("<3ff", 0, 0, 0, 1.0) + struct.pack("<I", 3)
            + struct.pack("<fff3ffff", 1.0, 0.0, 80.0, 1.0, 1.0, 1.0, 1.0, 0.3, 2.0))


def texture_set(diffuse: str, normal: str) -> bytes:
    paths = [diffuse, normal] + [""] * 7
    return struct.pack("<I", 9) + b"".join(_sized(p) for p in paths)


def effect_shader(texture: str, emissive=(1.0, 1.0, 1.0, 1.0), multiple: float = 1.5) -> bytes:
    """BSEffectShaderProperty for a self-lit blade, laid out as vanilla's 118-byte EdgeBlood shader (SSE has
    no environment/normal/mask textures here; those are Fallout 4's)."""
    return (struct.pack("<iIi", -1, 0, -1) + struct.pack("<II", EFFECT_FLAGS1, EFFECT_FLAGS2)
            + struct.pack("<4f", 0, 0, 1, 1) + _sized(texture)
            + bytes([3, 255, 0, 0]) + struct.pack("<4f", 1.0, 1.0, 1.0, 1.0)
            + struct.pack("<4f", *emissive) + struct.pack("<ff", multiple, 100.0) + _sized(""))


def alpha_property(flags: int = ALPHA_ADDITIVE, threshold: int = 0) -> bytes:
    return struct.pack("<iIiHB", -1, 0, -1, flags, threshold)


# ------------------------------------------------------------------ weapon assembly
def _node_children(block: bytes) -> tuple[int, list[int], int]:
    """(offset of the children count, children, end) in a NiNode/BSFadeNode block."""
    (nextra,) = struct.unpack_from("<I", block, 4)
    i = 8 + 4 * nextra + 4 + 4 + 12 + 36 + 4 + 4
    (n,) = struct.unpack_from("<I", block, i)
    return i, list(struct.unpack_from(f"<{n}i", block, i + 4)), i + 4 + 4 * n


def weapon(template: bytes, parts: list[dict], textures: dict[str, str], normal_map: str) -> bytes:
    """Replace a vanilla weapon's shapes with `parts` (from k2s.models, already in Skyrim units/axes).

    `textures` maps a KOTOR texture resref to its Data-relative DDS path."""
    nif = read(template)
    first_shape = next((k for k, (t, _) in enumerate(nif.blocks) if t in SHAPE_TYPES), len(nif.blocks))
    if any(t in SHAPE_TYPES for t, _ in nif.blocks[first_shape:]) is False or \
            any(t not in SHAPE_TYPES for t, _ in nif.blocks[first_shape:]):
        raise ValueError("template must keep all non-shape blocks before its first shape")
    blocks = nif.blocks[:first_shape]
    new_children = []
    for p in parts:
        tex = textures.get(p["texture"], "")
        base = len(blocks)
        name = nif.string_index(p["name"] or f"part{base}")
        if p["kind"] == "blade":
            blocks.append(("BSTriShape", tri_shape(name, p["verts"], p["uvs"], p["normals"], p["faces"],
                                                   base + 1, base + 2)))
            blocks.append(("BSEffectShaderProperty", effect_shader(tex)))
            blocks.append(("NiAlphaProperty", alpha_property()))
        else:
            blocks.append(("BSTriShape", tri_shape(name, p["verts"], p["uvs"], p["normals"], p["faces"],
                                                   base + 1, -1)))
            blocks.append(("BSLightingShaderProperty", lighting_shader(base + 2)))
            blocks.append(("BSShaderTextureSet", texture_set(tex, normal_map)))
        new_children.append(base)
    root_t, root = blocks[0]
    at, _old, end = _node_children(root)
    root = root[:at] + struct.pack(f"<I{len(new_children)}i", len(new_children), *new_children) + root[end:]
    blocks[0] = (root_t, root)
    nif.blocks = blocks
    nif.header_strings = [b"kotor2skyrim", b"", b""]
    return write(nif)


# ------------------------------------------------------------------ textures
def flat_normal_dds(size: int = 4, specular: int = 40) -> bytes:
    """An uncompressed 32-bit DDS of a flat normal map (128,128,255) with `specular` in alpha."""
    hdr = struct.pack("<4sIIIIIII44x", b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x8, size, size, size * 4, 0, 1)
    pf = struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    caps = struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    pixel = bytes([255, 128, 128, specular])  # B, G, R, A
    return hdr + pf + caps + pixel * (size * size)


# ------------------------------------------------------------------ statics (rooms) with Havok collision
HAVOK_SCALE = 69.99124  # Skyrim units per Havok unit
STATIC_MATERIAL = 0xDF02F237  # the stone material vanilla's ms11unholyaltar.nif collision uses
CHUNK = 200  # convex shapes per bhkListShape; larger rooms get more collision nodes


def _node(name: int, children: list[int], extra: list[int] = (), collision: int = -1, flags: int = 0x0E) -> bytes:
    return (struct.pack(f"<iI{len(extra)}i", name, len(extra), *extra) + struct.pack("<iI3f9ffi", -1, flags, 0, 0, 0,
            1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0, collision) + struct.pack(f"<I{len(children)}iI", len(children), *children, 0))


def _plane(a, b, c, inside):
    """Plane through a, b, c as (nx, ny, nz, d) with n·p + d <= 0 on the side of `inside`."""
    u = [b[k] - a[k] for k in range(3)]
    v = [c[k] - a[k] for k in range(3)]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    m = math.sqrt(sum(x * x for x in n))
    if m < 1e-12:
        return None
    n = [x / m for x in n]
    d = -sum(n[k] * a[k] for k in range(3))
    if sum(n[k] * inside[k] for k in range(3)) + d > 0:
        n, d = [-x for x in n], -d
    return (*n, d)


def prism(top: list, depth_vec) -> tuple[list, list]:
    """A convex prism from a convex polygon `top` (3 or 4 points, Havok units) swept by `depth_vec`:
    its vertices and its outward planes."""
    bottom = [tuple(p[k] + depth_vec[k] for k in range(3)) for p in top]
    verts = list(top) + bottom
    centre = [sum(v[k] for v in verts) / len(verts) for k in range(3)]
    planes = [_plane(top[0], top[1], top[2], centre), _plane(bottom[0], bottom[1], bottom[2], centre)]
    n = len(top)
    for i in range(n):
        planes.append(_plane(top[i], top[(i + 1) % n], bottom[i], centre))
    return verts, [p for p in planes if p]


def convex_shape(verts, planes, radius: float = 0.01) -> bytes:
    out = struct.pack("<If", STATIC_MATERIAL, radius) + struct.pack("<3I", 0, 0, 0x80000000) * 2
    out += struct.pack("<I", len(verts)) + b"".join(struct.pack("<4f", *v, 0.0) for v in verts)
    out += struct.pack("<I", len(planes)) + b"".join(struct.pack("<4f", *p) for p in planes)
    return out


def list_shape(children: list[int]) -> bytes:
    return (struct.pack(f"<I{len(children)}i", len(children), *children) + struct.pack("<I", STATIC_MATERIAL)
            + struct.pack("<3I", 0, 0, 0x80000000) * 2 + struct.pack(f"<I{len(children)}I", len(children),
                                                                      *([0] * len(children))))


def static(parts: list[dict], textures: dict[str, str], normal_map: str, convexes: list[tuple[list, list]],
           rigid_body_template: bytes) -> bytes:
    """A static NIF: render `parts` (Skyrim units) and collide with `convexes` (Havok units).

    `rigid_body_template` is a vanilla static bhkRigidBody (layer STATIC, fixed motion); only its shape
    reference (the first 4 bytes) is changed."""
    nif = Nif([b"kotor2skyrim", b"", b""], [], [], [0])
    blocks: list[tuple[str, bytes]] = [("BSFadeNode", b""), ("BSXFlags", struct.pack("<iI", nif.string_index("BSX"), 0x82))]
    children = []
    for c0 in range(0, len(convexes), CHUNK):
        chunk = convexes[c0:c0 + CHUNK]
        node = len(blocks)
        blocks.append(("NiNode", b""))
        first = len(blocks)
        for verts, planes in chunk:
            blocks.append(("bhkConvexVerticesShape", convex_shape(verts, planes)))
        lst = len(blocks)
        blocks.append(("bhkListShape", list_shape(list(range(first, lst)))))
        body = len(blocks)
        blocks.append(("bhkRigidBody", struct.pack("<i", lst) + rigid_body_template[4:]))
        col = len(blocks)
        blocks.append(("bhkCollisionObject", struct.pack("<iHi", node, 0x81, body)))
        blocks[node] = ("NiNode", _node(nif.string_index(f"Collision{c0 // CHUNK}"), [], collision=col))
        children.append(node)
    for p in parts:
        base = len(blocks)
        name = nif.string_index(p["name"] or f"part{base}")
        mode = ALPHA_MODES.get(p.get("alpha") or "")
        blocks.append(("BSTriShape", tri_shape(name, p["verts"], p["uvs"], p["normals"], p["faces"], base + 1,
                                               base + 3 if mode else -1)))
        blocks.append(("BSLightingShaderProperty", lighting_shader(base + 2)))
        blocks.append(("BSShaderTextureSet", texture_set(textures.get(p["texture"], ""), normal_map)))
        if mode:
            blocks.append(("NiAlphaProperty", alpha_property(*mode)))
        children.append(base)
    blocks[0] = ("BSFadeNode", _node(nif.string_index("Room"), children, extra=[1]))
    nif.blocks = blocks
    return write(nif)
