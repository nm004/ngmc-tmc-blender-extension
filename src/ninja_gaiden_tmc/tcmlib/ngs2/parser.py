# Ninja Gaiden Model Importer by Nozomi Miyamori is under the public domain
# and also marked with CC0 1.0. This file is a part of Ninja Gaiden Model Importer.

from __future__ import annotations

from ..parser import ContainerParser

from typing import NamedTuple
from enum import IntEnum
from operator import indexOf
import struct

class TMCParser(ContainerParser):
    def __init__(self, data, ldata = b''):
        super().__init__(b'TMC', data)

        a = struct.unpack_from('< HH4xI4x I4x8x 16s', self._metadata)
        self.metadata = TMCMetaData(*a[:-1], a[-1].partition(b'\0')[0])

        o = 0xc0
        p = o+4*len(self._chunks)
        tbl = self._metadata[o:p].cast('I')
        i = indexOf(tbl, 0x8000_0020)
        self.lheader = LHeaderParser(self._chunks[i], ldata)

        for t, c in zip(tbl, self._chunks):
            if not c:
                continue

            match t:
                case 0x8000_0001:
                    self.mdlgeo = MdlGeoParser(c)
                case 0x8000_0002:
                    self.ttdm = TTDMParser(c, ldata and self.lheader.ttdl)
                case 0x8000_0003:
                    self.vtxlay = VtxLayParser(c, ldata and self.lheader.vtxlay)
                case 0x8000_0004:
                    self.idxlay = IdxLayParser(c, ldata and self.lheader.idxlay)
                case 0x8000_0005:
                    self.mtrcol = MtrColParser(c)
                case 0x8000_0006:
                    self.mdlinfo = MdlInfoParser(c)
                case 0x8000_0010:
                    self.hielay = HieLayParser(c)
                case 0x8000_0030:
                    self.nodelay = NodeLayParser(c)
                case 0x8000_0040:
                    self.glblmtx = GlblMtxParser(c)
                case 0x8000_0050:
                    self.bnofsmtx = BnOfsMtxParser(c)
                case 0x0000_0000:
                    obj_type_info_head = c
                case 0x0000_0001:
                    obj_type_info = c
                case 0x0000_0005:
                    self.mtrlchng = MTRLCHNGParser(c)

        try:
            self.obj_type_info = OBJ_TYPE_INFOParser(obj_type_info_head, obj_type_info)
        except NameError:
            pass

    def close(self):
        super().close()
        self.lheader.close()
        self.mdlgeo.close()
        self.ttdm.close()
        self.vtxlay.close()
        self.idxlay.close()
        self.mtrcol.close()
        self.mdlinfo.close()
        self.hielay.close()
        self.nodelay.close()
        self.glblmtx.close()
        self.bnofsmtx.close()
        if x := getattr(self, 'mtrlchng', None): x.close()

class TMCMetaData(NamedTuple):
    unknown0x0: int
    unknown0x2: int
    unknown0x8: int
    general_chunk_count: int
    #addr0x18
    name: bytes

class MdlGeoParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'MdlGeo', data)
        self.chunks = tuple( ObjGeoParser(c) for c in self._chunks )

    def close(self):
        super().close()
        for c in self.chunks:
            c.close()

class ObjGeoParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'ObjGeo', data)
        a = struct.unpack_from('< HHiII 8x8x 16s', self._metadata)
        self.metadata = ObjGeoMetaData(*a[:-1], a[-1].partition(b'\0')[0])
        self.sub_container = GeoDeclParser(self._sub_container)
        self.chunks = tuple( ObjGeoParser._make_chunk(c) for c in self._chunks )

    @staticmethod
    def _make_chunk(c):
        a = struct.unpack_from(f'< iiII', c)
        texture_count = a[3]
        assert texture_count <= 4
        b = struct.unpack_from('< II8x III4x IIII II8x 8xII I?3xII IIII'
                                'IIII ffff IIII IIII IIII', c, 0x20)
        I = ( c[o:] for o in struct.unpack_from(f'< {texture_count}I', c, 0x10) )
        return ObjGeoChunk(*a[:-1], *b, tuple( ObjGeoParser._make_texture_info(i) for i in I ))

    @staticmethod
    def _make_texture_info(i):
        x = struct.unpack_from('< IIII IIII IIii I', i)
        return TextureInfo(x[0], TextureUsage(x[1]), *x[2:],
                           *struct.unpack_from('IIII IIII IIII ffff I', i, 0x38-4*bool(x[-1])))

    def close(self):
        super().close()
        self.sub_container.close()

class ObjGeoMetaData(NamedTuple):
    unknown0x0: int # == 3
    unknown0x2: int # == 1
    obj_index: int
    unknown0x8: int # padding?
    unknown1xc: int # padding?
    #objinfo_address0x10
    #address0x18
    name: bytes
    
class ObjGeoChunk(NamedTuple):
    objgeo_chunk_index: int
    mtrcol_chunk_index: int
    unknown0x8: int # padding?
    #texture_count: int

    #texture_info_offset_table: tuple

    unknown0x20: int
    unknown0x24: int
    #mtrcol_address0x28

    unknown0x30: int
    unknown0x34: int
    #geodecl_chunk_address0x38
    geodecl_chunk_index: int

    unknown0x40: int
    unknown0x44: int
    unknown0x48: int
    unknown0x4c: int

    unknown0x50: int
    unknown0x54: int
    #objinfo_chunk_address0x58

    #address0x60
    unknown0x68: int # == 1
    unknown0x6c: int # == 5

    unknown0x70: int # == 1
    show_backface: bool
    first_index_index: int
    index_count: int

    first_vertex_index: int
    vertex_count: int
    unknown0x88: int
    unknown0x8c: int

    unknown0x90: int
    unknown0x94: int
    unknown0x98: int
    unknown0x9c: int

    unknown0xa0: float # == 1.0
    unknown0xa4: float # == 0.0
    unknown0xa8: float # == 1.0
    unknown0xac: float # == 1.0

    unknown0xb0: int
    unknown0xb4: int
    unknown0xb8: int # == 1
    unknown0xbc: int # == 1

    unknown0xc0: int
    unknown0xc4: int
    unknown0xc8: int
    unknown0xcc: int

    unknown0xd0: int
    unknown0xd4: int
    unknown0xd8: int
    unknown0xdc: int
    texture_info_table: tuple[TextureInfo]

class TextureInfo(NamedTuple):
    info_index: int
    usage: TextureUsage
    texture_index: int
    unknown0xc: int # padding?

    color_usage: int
    unknown0x14: int # == 1
    unknown0x18: int
    unknown0x1c: int

    unknown0x20: int
    unknown0x24: int
    unknown0x28: int
    unknown0x2c: int

    unknown0x30: int

    unknown0x0_1: int
    unknown0x4_1: int
    unknown0x8_1: int
    unknown0xc_1: int

    unknown0x10_1: int
    unknown0x14_1: int # == 1
    unknown0x18_1: int # == 1
    unknown0x1c_1: int # == 1

    unknown0x20_1: float
    unknown0x24_1: float
    unknown0x28_1: float # == 12.0
    unknown0x2c_1: float # == -1.0

    unknown0x30_1: int
    unknown0x34_1: int
    unknown0x38_1: int
    unknown0x3c_1: int

    unknown0x40_1: int # == 2

class TextureUsage(IntEnum):
    Albedo = 0
    Normal = 1
    Smoothness = 2
    Add = 3

class GeoDeclParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'GeoDecl', data)
        self.chunks = tuple( GeoDeclParser._make_chunk(c) for c in self._chunks )

    @staticmethod
    def _make_chunk(c):
        a = struct.unpack_from('< IIII IIII', c)
        vertex_info_offset = a[1]
        b = struct.unpack_from('< II III', c, vertex_info_offset)
        vertex_element_count = b[2]
        o = vertex_info_offset + 0x18
        E = ( c[o:] for o in range(o, 8*vertex_element_count+o, 8) )
        return GeoDeclChunk(a[0], *a[2:], *b[0:2], *b[3:],
                            tuple( GeoDeclParser._make_d3dvertexelement9(e) for e in E ))

    @staticmethod
    def _make_d3dvertexelement9(e):
        a = struct.unpack_from('< hhBBBB', e)
        return D3DVERTEXELEMENT9(*a[:2], D3DDECLTYPE(a[2]), a[3], D3DDECLUSAGE(a[4]), a[5])

class GeoDeclChunk(NamedTuple):
    unknown0x0: int # == 0
    #vertex_info_offset0x4 # == 0x38
    unknown0x8: int # == 1
    index_buffer_index: int

    index_count: int
    vertex_count: int
    unknown0x18: int # == 0, 1, 2, 3 or 4
    unknown0x1c: int # padding?

    #address0x20
    #address0x28
    #vtxlay_chunk_address0x30

    # skip to [vertex_info_offset]

    vertex_buffer_index: int
    vertex_nbytes: int

    #vertex_element_count0x8
    vertex_info_unknown0xc: int # padding?
    vertex_info_unknown0x10: int # padding?
    #address0x48
    vertex_elements: tuple[D3DVERTEXELEMENT9]

class D3DVERTEXELEMENT9(NamedTuple):
    stream: int
    offset: int
    d3d_decl_type: D3DDECLTYPE
    method: int
    usage: D3DDECLUSAGE
    usage_index: int

class D3DDECLTYPE(IntEnum):
    FLOAT1     = 0
    FLOAT2     = 1
    FLOAT3     = 2
    FLOAT4     = 3
    D3DCOLOR   = 4
    UBYTE4     = 5
    SHORT2     = 6
    SHORT4     = 7
    UBYTE4N    = 8
    SHORT2N    = 9
    SHORT4N    = 10
    USHORT2N   = 11
    USHORT4N   = 12
    UDEC3      = 13
    DEC3N      = 14
    FLOAT16_2  = 15
    FLOAT16_4  = 16
    UNUSED     = 17

class D3DDECLUSAGE(IntEnum):
    POSITION      = 0
    BLENDWEIGHT   = 1
    BLENDINDICES  = 2
    NORMAL        = 3
    PSIZE         = 4
    TEXCOORD      = 5
    TANGENT       = 6
    BINORMAL      = 7
    TESSFACTOR    = 8
    POSITIONT     = 9
    COLOR         = 10
    FOG           = 11
    DEPTH         = 12
    SAMPLE        = 13

class TTDMParser(ContainerParser):
    def __init__(self, data, ldata):
        super().__init__(b'TTDM', data)
        self.metadata = TTDHParser(self._metadata)
        self.sub_container = TTDLParser(self._sub_container, ldata)

    def close(self):
        super().close()
        self.metadata.close()
        self.sub_container.close()

class TTDHParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'TTDH', data)
        self.chunks = tuple( TTDHChunk(*struct.unpack_from('< ?3xi', c)) for c in self._chunks )

class TTDHChunk(NamedTuple):
    # If in_ttdl is true, the index points to TTDL, otherwise it points to TTDM.
    # Although, all data seems be in TTDL when it comes to NGS2 TMC.
    in_ttdl: bool
    chunk_index: int

class TTDLParser(ContainerParser):
    def __init__(self, data, ldata):
        super().__init__(b'TTDL', data, ldata)

class VtxLayParser(ContainerParser):
    def __init__(self, data, ldata = b''):
        super().__init__(b'VtxLay', data, ldata)

class IdxLayParser(ContainerParser):
    def __init__(self, data, ldata = b''):
        super().__init__(b'IdxLay', data, ldata)
        # Index size of an index buffer s is depends on the number of elements in the corresponding 
        # vertex buffer N, i.e., if N < 1<<16 then s is 2 bytes, otherwise it's 4 bytes.

class MtrColParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'MtrCol', data)
        self.chunks = tuple( MtrColParser._make_chunk(c) for c in self._chunks )

    @staticmethod
    def _make_chunk(c):
        xref_count, = struct.unpack_from('< I', c, 0xd4)
        xrefs = struct.unpack_from(f'<' + xref_count*'iI', c, 0xd8)
        return MtrColChunk(
                struct.unpack_from('< 4f', c),
                struct.unpack_from('< 4f', c, 0x10),
                struct.unpack_from('< 4f', c, 0x20),
                struct.unpack_from('< 4f', c, 0x30),
                struct.unpack_from('< 4f', c, 0x40),
                struct.unpack_from('< 4f', c, 0x50),
                *struct.unpack_from('< ff', c, 0x68),
                struct.unpack_from('< 4f', c, 0x70),
                struct.unpack_from('< 4f', c, 0x80),
                struct.unpack_from('< 4f', c, 0x90),
                struct.unpack_from('< 4f', c, 0xa0),
                struct.unpack_from('< 4f', c, 0xb0),
                struct.unpack_from('< 4f', c, 0xc0),
                *struct.unpack_from('< i', c, 0xd0),
                tuple(xrefs[i:i+2] for i in range(0, len(xrefs), 2))
        )

class MtrColChunk(NamedTuple):
    emission: tuple[float]
    specular: tuple[float]
    specular_power: tuple[float]
    unknown0x30: tuple[float]
    unknown0x40: tuple[float]
    unknown0x50: tuple[float]
    # address0x60
    specular_glow_power: float
    diffuse_glow_power: float
    unknown0x70: tuple[float]

    coat: tuple[float]
    sheen: tuple[float]
    unknown0xa0: tuple[float]
    unknown0xb0: tuple[float]
    unknown0xc0: tuple[float]
    mtrcol_chunk_index: int
    # Each tuple has (objindex, count)
    # that means the mtrcol is used by "objindex" "count" times
    xrefs: tuple[tuple[int, int]]

class MdlInfoParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'MdlInfo', data)
        self.chunks = tuple( ObjInfoParser(c) for c in self._chunks )

    def close(self):
        super().close()
        for c in self.chunks:
            c.close()

class ObjInfoParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'ObjInfo', data)
        self.metadata = ObjInfoMetaData(
                *struct.unpack_from('< HHIII IIII IIII IIII IIII IIII ffff', self._metadata),
                ()
        )
        self.chunks = ()

class ObjInfoMetaData(NamedTuple):
    unknown0x0: int # == 3
    unknown0x2: int # == 2
    obj_index: int
    unknown0x8: int
    weighted_node_count: int

    unknown0x10: int
    unknown0x14: int # == 2
    unknown0x18: int
    unknown0x1c: int

    unknown0x20: int
    unknown0x24: int
    unknown0x28: int
    unknown0x2c: int

    unknown0x30: int
    unknown0x34: int
    unknown0x38: int # == 1
    unknown0x3c: int # == 1

    unknown0x40: int # == 1
    unknown0x44: int
    unknown0x48: int
    unknown0x4c: int

    unknown0x50: int # == 1
    unknown0x54: int
    unknown0x58: int
    unknown0x5c: int

    unknown0x60: float
    unknown0x64: float
    unknown0x68: float
    unknown0x6c: float # == 1.0

    chunk: ObjInfoChunk

class ObjInfoChunk(NamedTuple):
    pass

class HieLayParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'HieLay', data)
        self.chunks = tuple( HieLayParser._make_chunk(c) for c in self._chunks )

    @staticmethod
    def _make_chunk(c):
        *matrix, parent, child_count, level = struct.unpack_from('< 16f iII', c)
        children = struct.unpack_from(f'< {child_count}i', c, 0x50)
        return HieLayChunk(matrix, parent, level, children)

class HieLaySubContainer(NamedTuple):
    unknown0x0: int # == 1
    unknown0x10: int # == 2

class HieLayChunk(NamedTuple):
    matrix: tuple[float]
    parent: int
    level: int
    children: tuple[int]

class LHeaderParser(ContainerParser):
    def __init__(self, data, ldata):
        super().__init__(b'LHeader', data, ldata)

        o1 = 0x20
        o2 = 0x20 + 4*len(self._chunks)
        chunk_type_id_table = self._metadata[o1:o2].cast('I')
        for c, t in zip(self._chunks, chunk_type_id_table):
            match t:
                case 0xC000_0002:
                    self.ttdl = c
                case 0xC000_0003:
                    self.vtxlay = c
                case 0xC000_0004:
                    self.idxlay = c

class NodeLayParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'NodeLay', data)
        self.chunks = tuple( NodeObjParser(c) for c in self._chunks )

    def close(self):
        super().close()
        for c in self.chunks:
            c.close()

class NodeLayMetaData(NamedTuple):
    unknown0x0: int # == 1
    unknown0x2: int # == 2

class NodeObjParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'NodeObj', data)
        n = self._metadata.nbytes - 0x10
        x = struct.unpack_from(f'< Iii4x {n}s', self._metadata)
        self.metadata = NodeObjMetaData(*x[:-1], x[-1].partition(b'\0')[0])
        if self._chunks:
            c = self._chunks[0]
            obj_index, node_count, node_index, *matrix = struct.unpack_from('< iIi4x 16f', c)
            node_group = struct.unpack_from(f'< {node_count}i', c, 0x50)
            self.chunks = (NodeObjChunk(obj_index, node_index, matrix, node_group),)

class NodeObjMetaData(NamedTuple):
    unknown0x0: int
    master: int
    node_index: int
    name: bytes

class NodeObjChunk(NamedTuple):
    obj_index: int
    node_index: int
    matrix: tuple[float]
    node_group: tuple[int]
    
class GlblMtxParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'GlblMtx', data)
        self.chunks = tuple( struct.unpack_from('< 16f', c) for c in self._chunks )

class BnOfsMtxParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'BnOfsMtx', data)
        self.chunks = tuple( struct.unpack_from('< 16f', c) for c in self._chunks )

# NGS2 specific data parsers below

class OBJ_TYPE_INFOParser:
    def __init__(self, table_head, table):
        X = struct.unpack_from('HH HH HH HH HH HH HH HH', table_head)
        X = [ (X[i], X[i+1]) for i in range(0, len(X), 2) ]
        X.sort(key=lambda x: x[0])
        n = sum( x[1] for x in X )
        O = struct.unpack_from(f'< {n}I', table)
        f = lambda x: (OBJ_TYPE(x[0]), *x[1:])
        self.table = tuple( f(struct.unpack_from('< III', table, o)) for p, n in X for o in O[p:p+n] )

class OBJ_TYPE(IntEnum):
    NML = 0
    MOT = 1
    WGT = 3
    SUP = 4
    OPT = 5
    WPB = 7

class MTRLCHNGParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'MTRLCHNG', data)
        self.metadata = MTRLCHNGMetaData(*struct.unpack_from('< HHIII', self._metadata))
        m = self.metadata.variant_count
        n = self.metadata.element_count
        C = tuple(
                MtrColParser._make_chunk(self._chunks[2][o:o+0xd0].tobytes() + bytes(0x10))
                for o in range(0, m*n*0xd0, 0xd0)
        )
        self.color_variants = tuple( C[i*n:(i+1)*n] for i in range(m) )

class MTRLCHNGMetaData(NamedTuple):
    unknown0x0: int
    unknown0x2: int
    unknown0x4: int
    variant_count: int
    element_count: int
