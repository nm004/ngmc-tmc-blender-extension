# Ninja Gaiden Model Importer for Blender by Nozomi Miyamori is under the public domain
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
        a = struct.unpack_from('< HH12x 16x 16s', self._metadata)
        self.metadata = TMCMetaData(*a[:-1], a[-1].partition(b'\0')[0])

        if ldata:
            ldata = memoryview(ldata)
            self.vtxlay = v = VtxLayParser(ldata)
            self.idxlay = IdxLayParser(ldata[v._data.nbytes:])
            ldata.release()

        o = 0x60
        p = o+4*len(self._chunks)
        tbl = self._metadata[o:p].cast('I')

        for t, c in zip(tbl, self._chunks):
            if not c:
                continue

            match t:
                case 0x8000_0001:
                    self.mdlgeo = MdlGeoParser(c)
                case 0x8000_0002:
                    #self.ttg = TTGParser(c)
                    pass
                case 0x8000_0005:
                    self.mtrcol = MtrColParser(c)
                case 0x8000_0006:
                    self.mdlinfo = MdlInfoParser(c)
                case 0x8000_0010:
                    self.hielay = HieLayParser(c)
                case 0x0000_0001:
                    self.obj_type_info = OBJ_TYPE_INFOParser(c)
                case 0x0000_0015:
                    self.extmcol = EXTMCOLParser(c)

    def close(self):
        super().close()
        if x := getattr(self, 'vtxlay', None): x.close()
        if x := getattr(self, 'idxlay', None): x.close()
        self.mdlgeo.close()
        self.mtrcol.close()
        self.mdlinfo.close()
        self.hielay.close()
        if x := getattr(self, 'extmcol', None): x.close()

class TMCMetaData(NamedTuple):
    unknown0x0: int
    unknown0x2: int
    #address0x10?
    #address0x18?
    name: bytes

class MdlGeoParser(ContainerParser):
    def __init__(self, data, ldata = b''):
        super().__init__(b'MdlGeo', data)
        self.chunks = tuple( ObjGeoParser(c) for c in self._chunks )

    def close(self):
        super().close()
        for c in self.chunks:
            c.close()

class ObjGeoParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'ObjGeo', data)
        a = struct.unpack_from('< HHiII 16s', self._metadata)
        self.metadata = ObjGeoMetaData(*a[:-1], a[-1].partition(b'\0')[0])
        self.sub_container = GeoDeclParser(self._sub_container)
        self.chunks = tuple( ObjGeoParser._make_chunk(c) for c in self._chunks )

    @staticmethod
    def _make_chunk(c):
        a = struct.unpack_from(f'< iiiI IIII', c)
        texture_count = a[6]
        assert texture_count <= 4
        b = struct.unpack_from('< IIBBBBI 8x8x IIII IIII', c, 0x40)
        I = ( c[o:] for o in struct.unpack_from(f'< {texture_count}I', c, 0x20) )
        return ObjGeoChunk(*a[:6], a[7], *b, tuple( ObjGeoParser._make_texture_info(i) for i in I ))

    @staticmethod
    def _make_texture_info(i):
        x = struct.unpack_from('< IIiI IIII IIII IIII IIII IIII IfII', i)
        return TextureInfo(x[0], TextureUsage(x[1]), *x[2:])

    def close(self):
        super().close()
        self.sub_container.close()

class ObjGeoMetaData(NamedTuple):
    unknown0x0: int # == 0
    unknown0x2: int # == 9
    obj_index: int
    unknown0x8: int
    unknown0xc: int # == 2
    name: bytes
    
class ObjGeoChunk(NamedTuple):
    objgeo_chunk_index: int
    mtrcol_chunk_index: int
    geodecl_chunk_index: int
    unknown0xc: int # padding?

    first_index_index: int
    index_count: int
    #texture_count0x1c: int
    unknown0x1c: int # padding?

    #texture_info_offset_table: tuple

    #address0x30?
    #address0x38?

    first_vertex_index: int
    vertex_count: int
    unknown0x48: int # == bitmask?
    unknown0x49: int # == bitmask?
    unknown0x4a: int # == 0x20
    unknown0x4b: int # == 0x22 or 0x23
    unknown0x4c: int # == 1

    #address0x50?
    #address0x58?

    unknown0x60: int
    unknown0x64: int # == 1
    unknown0x68: int
    unknown0x6c: int # == 4

    unknown0x70: int # == 5
    unknown0x74: int # == 1
    unknown0x78: int # == 1
    unknown0x7c: int
    texture_info_table: tuple[TextureInfo]

class TextureInfo(NamedTuple):
    info_index: int
    usage: TextureUsage
    texture_index: int
    unknown0xc: int # padding?
    color_usage: int
    unknown0x14: int
    unknown0x18: int
    unknown0x1c: int

    unknown0x20: int
    unknown0x24: int
    unknown0x28: int
    unknown0x2c: int

    unknown0x30: int
    unknown0x34: int
    unknown0x38: int
    unknown0x3c: int

    unknown0x40: int
    unknown0x44: int
    unknown0x48: int
    unknown0x4c: int # == 1

    unknown0x50: int # == 1
    unknown0x54: int # == 1
    unknown0x58: int
    unknown0x5c: int

    unknown0x60: int # == 12
    unknown0x64: float # == -1.0
    unknown0x68: int
    unknown0x6c: int

class TextureUsage(IntEnum):
    Albedo = 0
    Normal = 1
    Smoothness = 2
    AlphaBlend = 3

class GeoDeclParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'GeoDecl', data)
        self.chunks = tuple( GeoDeclParser._make_chunk(c) for c in self._chunks )

    @staticmethod
    def _make_chunk(c):
        a = struct.unpack_from('< IIII II', c)
        vertex_info_offset = a[0]
        b = struct.unpack_from('< III', c, vertex_info_offset)
        vertex_element_count = b[2]
        # vertex_info_offset + 0x20 == vertex_element_info_table
        # vertex_element_info_table's entry has data that is similar
        # to D3DVERTEXELEMENT9, but the structure is different.
        o = vertex_info_offset + 0x20 + vertex_element_count * 0x10 + 0x10
        E = ( c[o:] for o in range(o, 8*vertex_element_count+o, 8) )
        return GeoDeclChunk(*a[1:], *b[0:2], tuple( GeoDeclParser._make_d3dvertexelement9(e) for e in E))

    @staticmethod
    def _make_d3dvertexelement9(e):
        a = struct.unpack_from('< hhBBBB', e)
        return D3DVERTEXELEMENT9(*a[:2], D3DDECLTYPE(a[2]), a[3], D3DDECLUSAGE(a[4]), a[5])

class GeoDeclChunk(NamedTuple):
    #vertex_info_offset0x0
    unknown0x4: int # == 1
    index_buffer_index: int
    index_count: int

    vertex_count: int
    unknown0x14: int # == 0, 1, 2, 3 or 4
    #padding0x1c?
    #address0x1c?
    #address0x20?
    #address0x28?

    # skip to [vertex_info_offset]

    vertex_buffer_index: int
    vertex_nbytes: int
    #vertex_element_count0x8
    #address0x10?
    #address0x18?
    #vertex_info: tuple
    #vertex_element_count1: int == vertex_element_count0x8
    #vertex_nbytes1: int == vertex_nbytes
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

class VtxLayParser(ContainerParser):
    def __init__(self, data, ldata = b''):
        super().__init__(b'VtxLay', data, ldata)

class IdxLayParser(ContainerParser):
    def __init__(self, data, ldata = b''):
        super().__init__(b'IdxLay', data, ldata)
        # Index size of an index buffer s is depends on the number of elements in the corresponding 
        # vertex buffer N, i.e., if N < 1<<16 then s is 2 bytes, otherwise it's 4 bytes.

class MtrColParser(ContainerParser):
    def __init__(self, data, ldata = b''):
        super().__init__(b'MtrCol', data)
        self.chunks = tuple( MtrColParser._make_chunk(c) for c in self._chunks )

    @staticmethod
    def _make_chunk(c):
        xref_count, = struct.unpack_from('< I', c, 0x54)
        xrefs = struct.unpack_from(f'<' + xref_count*'iI', c, 0x58)
        return MtrColChunk(
                struct.unpack_from('< 4f', c),
                struct.unpack_from('< 4f', c, 0x10),
                (*struct.unpack_from('< 3f', c, 0x20), *struct.unpack_from('< f', c, 0x40)),
                struct.unpack_from('< 3f', c, 0x30),
                *struct.unpack_from('< 4f i', c, 0x40),
                tuple(xrefs[i:i+2] for i in range(0, len(xrefs), 2))
        )

# Cf. EXTMCOL
class MtrColChunk(NamedTuple):
    emission: tuple[float]
    specular: tuple[float]
    specular_power: tuple[float]
    unknown0x30: tuple[float]
    # 0x40-0x44 is ior in MtrCol, 0x2c-0x30 is ior in EXTMCOL,
    # but the game move ior in MtrCol to 0x2c-0x30 after loading the data.
    ior: float
    specular_glow_power: float
    diffuse_glow_power: float
    unknown0x4c: float
    mtrcol_chunk_index: int
    #xref_count0x54
    # Each tuple has (objindex, count)
    # that means the mtrcol is used by "objindex" "count" times
    xrefs: tuple[tuple[int, int]]

class MdlInfoParser(ContainerParser):
    def __init__(self, data, ldata = b''):
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
                *struct.unpack_from('< HHIII', self._metadata),
                ObjInfoChunk(*struct.unpack_from('< IIII IIII', self._metadata, 0x10),
                             struct.unpack_from('< 4f', self._metadata, 0x30),
                             struct.unpack_from('< 4f', self._metadata, 0x40),
                             struct.unpack_from('< 3f', self._metadata, 0x50))
        )
        self.chunks = tuple(
                ObjInfoChunk(*struct.unpack_from('< IIII IIII', c),
                             struct.unpack_from('< 4f', c, 0x20),
                             struct.unpack_from('< 4f', c, 0x30),
                             struct.unpack_from('< 3f', c, 0x40))
                for c in self._chunks
        )

class ObjInfoMetaData(NamedTuple):
    unknown0x0: int
    unknown0x2: int # == 9
    obj_index: int
    unknown0x8: int # padding?
    weighted_node_count: int

    chunk: ObjInfoChunk

class ObjInfoChunk(NamedTuple):
    objinfo_chunk_index: int
    unknown0x4: int # == 1
    unknown0x8: int # == 2
    unknown0xc: int # == 2 or 0xa

    unknown0x10: int
    unknown0x14: int # == 1
    unknown0x18: int
    unknown0x1c: int

    unknown0x20: tuple[float]
    unknown0x30: tuple[float]
    unknown0x40: tuple[float]

class HieLayParser(ContainerParser):
    def __init__(self, data, ldata = b''):
        super().__init__(b'HieLay', data)
        self.chunks = tuple( HieLayParser._make_chunk(c) for c in self._chunks )
        self.sub_container = tuple( HieLaySubContainer(*struct.unpack_from('< I12x I', c)) for c in self._chunks )

    @staticmethod
    def _make_chunk(c):
        *matrix, parent, child_count = struct.unpack_from('< 16f iI', c)
        children = struct.unpack_from(f'< {child_count}i', c, 0x50)
        return HieLayChunk(matrix, parent, children)

class HieLaySubContainer(NamedTuple):
    unknown0x0: int # == 1
    unknown0x10: int # == 2

class HieLayChunk(NamedTuple):
    matrix: tuple[float]

    parent: int
    #child_count0x4
    #address0x8?
    children: tuple[int]

# NGS1 specific data below.

class OBJ_TYPE_INFOParser:
    def __init__(self, data):
        (
                table1_pos, table1_count, table2_pos, table2_count,
                table3_pos
        ) = struct.unpack_from('< IIII I', data, 0x20)
        self.table2 = tuple( OBJ_TYPE(i) for i in struct.unpack_from(f'< {table2_count}I', data, table2_pos) )

class OBJ_TYPE(IntEnum):
    NML = 0
    MOT = 1
    WGT = 3
    SUP = 4
    OPT = 5
    WPB = 7

class EXTMCOLParser(ContainerParser):
    def __init__(self, data):
        super().__init__(b'EXTMCOL', data)
        self.metadata = EXTMCOLMetaData(*struct.unpack_from('< II', self._metadata))
        m = self.metadata.variant_count
        n = self.metadata.element_count
        self.chunks = tuple(
                MtrColChunk(
                        struct.unpack_from('< 4f', c),
                        struct.unpack_from('< 4f', c, 0x10),
                        struct.unpack_from('< 4f', c, 0x20),
                        struct.unpack_from('< 4f', c, 0x30),
                        *struct.unpack_from('< 4f i', c, 0x40),
                        tuple()
                ) for c in self._chunks
        )
        self.color_variants = tuple( self.chunks[i*n:(i+1)*n] for i in range(m) )

class EXTMCOLMetaData(NamedTuple):
    variant_count: int
    element_count: int
