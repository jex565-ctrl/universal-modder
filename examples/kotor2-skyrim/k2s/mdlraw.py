"""A minimal KOTOR binary model (.mdl + .mdx) reader for geometry: the node tree, each node's transform,
and each mesh's vertices, normals, UVs, faces and textures.

Why not PyKotor's reader: on the Steam (Aspyr-updated) TSL, PyKotor 2.3.12 reads the K2 trimesh header
with its later fields shifted (MDX offsets come out as values like 3,210,014,051 in an 11,936-byte MDX),
so hilts and blaster bodies lose every vertex. This reader follows the layout MDLOps and xoreos document:

- file: 12-byte prefix (0, MDL size, MDX size); every offset below is relative to the end of the prefix.
- geometry header (80): 2 function pointers, name[32], root node offset @40, node count @44, ...
- model header follows it; the names array (offset, count) is at geometry+180 relative to the model start.
- node header (80): type flags u16 @0, node index u16 @2, name index u16 @4, position @16 (3 floats),
  orientation @28 (w, x, y, z), children array (offset u32, count u32) @44.
- trimesh header right after the node header (K1 332 bytes, K2 340): faces array @8, texture0 name @88,
  MDX row size @252, MDX bitmap @256, MDX offsets for vertex/normal/colour/uv0/uv1 @260/264/268/272/276,
  vertex count u16 @304, render u8 @313; K2 adds 8 bytes (dirt and hologram fields) after @314, so the MDX
  data offset is @324 (K1) or @332 (K2) and the MDL vertex array offset @328 or @336.
- face (32 bytes): normal, distance, surface, 3 adjacent u16, then 3 vertex indices u16 @26.
- saber nodes (flag 0x800) keep their 176 vertices in the MDL (the offset in the saber header @+0).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

NODE_MESH, NODE_SKIN, NODE_DANGLY, NODE_AABB, NODE_SABER = 0x20, 0x40, 0x100, 0x200, 0x800
NODE_HEADER = 80
K1_TRIMESH, K2_TRIMESH = 332, 340
MDX_VERTEX, MDX_TEX0, MDX_NORMAL = 0x1, 0x2, 0x20


@dataclass
class RawMesh:
    texture: str
    render: bool
    verts: list[tuple[float, float, float]]
    normals: list[tuple[float, float, float]]
    uvs: list[tuple[float, float]]
    faces: list[tuple[int, int, int]]
    bb_min: tuple[float, float, float]
    bb_max: tuple[float, float, float]


@dataclass
class RawNode:
    name: str
    flags: int
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]  # x, y, z, w
    mesh: RawMesh | None = None
    children: list["RawNode"] = field(default_factory=list)

    @property
    def is_saber(self) -> bool:
        return bool(self.flags & NODE_SABER)

    @property
    def is_aabb(self) -> bool:
        return bool(self.flags & NODE_AABB)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("latin-1")


class RawModel:
    def __init__(self, mdl: bytes, mdx: bytes | None, k2: bool = True):
        self.d = mdl[12:]
        self.x = mdx or b""
        self.trimesh_size = K2_TRIMESH if k2 else K1_TRIMESH
        self.name = _cstr(self.d[8:40])
        root = self.u32(40)
        names_off, names_n = self.u32(180 + 4), self.u32(180 + 8)
        self.names = [_cstr(self.d[o:o + 64]) for o in (self.u32(names_off + 4 * i) for i in range(names_n))]
        self.root = self.node(root, 0)

    def u32(self, o: int) -> int:
        return struct.unpack_from("<I", self.d, o)[0]

    def u16(self, o: int) -> int:
        return struct.unpack_from("<H", self.d, o)[0]

    def f(self, o: int, n: int) -> tuple[float, ...]:
        return struct.unpack_from(f"<{n}f", self.d, o)

    def node(self, off: int, depth: int) -> RawNode:
        if depth > 64:
            raise ValueError("node tree too deep (bad offset?)")
        flags, name_i = self.u16(off), self.u16(off + 4)
        w, x, y, z = self.f(off + 28, 4)
        n = RawNode(self.names[name_i] if name_i < len(self.names) else f"node{name_i}", flags,
                    self.f(off + 16, 3), (x, y, z, w))
        if flags & NODE_MESH and not flags & NODE_AABB:
            n.mesh = self.trimesh(off + NODE_HEADER, flags)
        child_off, child_n = self.u32(off + 44), self.u32(off + 48)
        for i in range(child_n):
            n.children.append(self.node(self.u32(child_off + 4 * i), depth + 1))
        return n

    def trimesh(self, t: int, flags: int) -> RawMesh:
        k2_extra = self.trimesh_size - K1_TRIMESH
        faces_off, faces_n = self.u32(t + 8), self.u32(t + 12)
        texture = _cstr(self.d[t + 88:t + 120])
        row, bitmap = self.u32(t + 252), self.u32(t + 256)
        o_vert, o_norm, o_uv = self.u32(t + 260), self.u32(t + 264), self.u32(t + 272)
        vcount = self.u16(t + 304)
        render = bool(self.d[t + 313])
        mdx_off = self.u32(t + 324 + k2_extra)
        mdl_verts = self.u32(t + 328 + k2_extra)
        verts, normals, uvs = [], [], []
        faces = []
        for i in range(faces_n):
            a, b, c = struct.unpack_from("<3H", self.d, faces_off + 32 * i + 26)
            faces.append((a, b, c))
        if flags & NODE_SABER:
            # saber header follows the trimesh header: vertex, uv and normal arrays in the MDL
            s = t + self.trimesh_size
            # skin/dangly headers never combine with sabers, so the saber header is next
            sv, suv, sn = self.u32(s), self.u32(s + 4), self.u32(s + 8)
            verts = [self.f(sv + 12 * i, 3) for i in range(vcount)]
            uvs = [self.f(suv + 8 * i, 2) for i in range(vcount)]
            normals = [self.f(sn + 12 * i, 3) for i in range(vcount)]
        elif self.x and row and mdx_off + row * vcount <= len(self.x):
            for i in range(vcount):
                base = mdx_off + row * i
                if bitmap & MDX_VERTEX:
                    verts.append(struct.unpack_from("<3f", self.x, base + o_vert))
                if bitmap & MDX_NORMAL:
                    normals.append(struct.unpack_from("<3f", self.x, base + o_norm))
                if bitmap & MDX_TEX0:
                    uvs.append(struct.unpack_from("<2f", self.x, base + o_uv))
        if not verts and mdl_verts and mdl_verts + 12 * vcount <= len(self.d):
            verts = [self.f(mdl_verts + 12 * i, 3) for i in range(vcount)]
        return RawMesh(texture, render, verts, normals, uvs, faces, self.f(t + 20, 3), self.f(t + 32, 3))
