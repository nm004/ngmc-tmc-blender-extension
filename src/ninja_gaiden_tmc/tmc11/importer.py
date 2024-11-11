# NINJA GAIDEN SIGMA 2 TMC Importer by Nozomi Miyamori is under the public domain
# and also marked with CC0 1.0. This file is a part of NINJA GAIDEN SIGMA 2 TMC Importer.

from .parser import (
    TMCParser, TextureMapUsage, D3DDECLUSAGE, D3DDECLTYPE
)
import bpy
import bmesh
from bpy_extras.io_utils import axis_conversion
from mathutils import Matrix, Vector

from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, CollectionProperty
from bpy.types import Operator, OperatorFileListElement

import tempfile
import struct
import os
import os.path
import mmap

def import_tmc11(context, tmc):
    tmc_name = tmc.metadata.name.decode()

    # We load textures
    # TODO: Use delete_on_close=False instead of delete=False when Blender has begun to ship Python 3.12
    images = []
    format0 = len(str(len(tmc.ttdm.sub_container.chunks)))
    with tempfile.NamedTemporaryFile(delete=False) as t:
        for i,c in enumerate(tmc.ttdm.sub_container.chunks):
            t.close()
            with open(t.name, t.file.mode) as f:
                f.write(c)
            images.append(x := bpy.data.images.load(t.name))
            x.pack()
            x.name = str(tmc_name + f'_{i:0{format0}}')
            x.filepath_raw = ''
    os.remove(t.name)

    # We add materials
    materials = []
    texmapinfo_to_matindex = {}
    format0 = len(str(len(tmc.mtrcol.chunks)))
    #uvnames = [ 'UVMap0', 'UVMap1', 'UVMap2', 'UVMap3' ]
    uvnames = [ '', 'UVMap1', 'UVMap2', 'UVMap3' ]
    for i, c in enumerate(tmc.mtrcol.chunks):
        S = set()
        for x in c.xrefs:
            for oc in tmc.mdlgeo.chunks[x[0]].chunks:
                if oc.mtrcol_index == i:
                    S.add(oc.texture_map_info)

        format1 = len(str(len(S)))
        for i, T in enumerate(S):
            m = bpy.data.materials.new(tmc_name + f'_{c.index:0{format0}}_{i:0{format1}}')
            m.preview_render_type = 'FLAT'
            m.use_nodes = True
            materials.append(m)
            # We assume that each texture corresponds to just a single material.
            # The material slot 0 is for fallback.
            texmapinfo_to_matindex[T] = len(materials)
            pbsdf = m.node_tree.nodes["Principled BSDF"]
            #pbsdf.inputs['Metallic'].default_value =
            #pbsdf.inputs['IOR'].default_value =
            base_mix = m.node_tree.nodes.new('ShaderNodeMix')
            base_mix.data_type = 'RGBA'
            base_mix.blend_type = 'OVERLAY'
            m.node_tree.links.new(base_mix.outputs['Result'], pbsdf.inputs['Base Color'])
            uv_idx = 0
            for t in T:
                ti = m.node_tree.nodes.new('ShaderNodeTexImage')
                ti.image = images[t.texture_buffer_index]
                uvn = m.node_tree.nodes.new('ShaderNodeUVMap')
                uv_map = uvnames[uv_idx]
                uv_idx += 1
                uvn.uv_map = uv_map
                m.node_tree.links.new(uvn.outputs['UV'], ti.inputs['Vector'])
                match t.usage:
                    case TextureMapUsage.Albedo:
                        match t.tag1:
                            case 0:
                                #ti.image.colorspace_settings.name = 'Non-Color'
                                pass
                            case 1:
                                m.node_tree.links.new(ti.outputs['Color'], base_mix.inputs['B'])
                                m.node_tree.links.new(ti.outputs['Alpha'], base_mix.inputs['Factor'])
                            case 3 | 5:
                                if not base_mix.inputs['A'].is_linked:
                                    m.node_tree.links.new(ti.outputs['Color'], base_mix.inputs['A'])
                                    m.node_tree.links.new(ti.outputs['Alpha'], pbsdf.inputs['Alpha'])
                                else:
                                    m.node_tree.links.new(ti.outputs['Color'], base_mix.inputs['B'])
                                    m.node_tree.links.new(ti.outputs['Alpha'], base_mix.inputs['Factor'])
                            case x:
                                raise ValueError(f'Not supported albedo texture format: {repr(x)}')
                    case TextureMapUsage.Normal:
                        ti.image.colorspace_settings.name = 'Non-Color'
                        nml = m.node_tree.nodes.new('ShaderNodeNormalMap')
                        nml.uv_map = uv_map
                        curv = m.node_tree.nodes.new('ShaderNodeRGBCurve')
                        curv_p = curv.mapping.curves[1].points
                        curv_p[0].location = (0, 1)
                        curv_p[1].location = (1, 0)
                        m.node_tree.links.new(ti.outputs['Color'], curv.inputs['Color'])
                        m.node_tree.links.new(curv.outputs['Color'], nml.inputs['Color'])
                        m.node_tree.links.new(nml.outputs['Normal'], pbsdf.inputs['Normal'])
                    case TextureMapUsage.Specular:
                        m.node_tree.links.new(ti.outputs['Color'], pbsdf.inputs['Specular Tint'])
                    case TextureMapUsage.Emission:
                        uvn.uv_map = ''
                        m.node_tree.links.new(ti.outputs['Color'], pbsdf.inputs['Emission Color'])
                        m.node_tree.links.new(ti.outputs['Alpha'], pbsdf.inputs['Emission Strength'])
                    case x:
                        raise ValueError(f'Not supported texture map usage: {repr(x)}')

    # We form an armature
    a = bpy.data.armatures.new(tmc_name)
    armature_obj = bpy.data.objects.new(a.name, a)
    armature_obj.matrix_world  = axis_conversion(from_forward='-Z', from_up='Y').to_4x4()
    context.view_layer.layer_collection.collection.objects.link(armature_obj)

    active_obj_saved = context.view_layer.objects.active
    context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')
    for c in tmc.nodelay.chunks:
        b = armature_obj.data.edit_bones.new(c.metadata.name.decode())
        b.matrix = tmc.glblmtx.chunks[c.metadata.node_index]
    for c in tmc.nodelay.chunks:
        i = c.metadata.node_index
        EB = armature_obj.data.edit_bones
        pi = tmc.hielay.chunks[i].parent
        b = EB[i]
        if pi > -1:
            b.parent = EB[pi]
        else:
            r = b
    r.tail = (0, .075, 0)
    set_bone_tail(r)
    bpy.ops.object.mode_set(mode='OBJECT')
    context.view_layer.objects.active = active_obj_saved

    a = armature_obj.data
    a.collections.new('MOT').is_solo = True
    a.collections.new('SUP')
    a.collections.new('WGT')
    a.collections.new('OPT')
    a.collections.new('WPB')
    for b in a.bones:
        a.collections[b.name[:3]].assign(b)
    for c in a.collections.values():
        if not len(c.bones):
            a.collections.remove(c)

    # We form a mesh below
    m = bpy.data.meshes.new(tmc_name)
    m.materials.append(None)
    for ma in materials:
        m.materials.append(ma)
    mesh_obj = bpy.data.objects.new(m.name, m)
    mesh_obj.parent = armature_obj
    for noc in tmc.nodelay.chunks:
        mesh_obj.vertex_groups.new(name=noc.metadata.name.decode())
    context.view_layer.layer_collection.collection.objects.link(mesh_obj)
    md = mesh_obj.modifiers.new('', 'ARMATURE')
    md.object = armature_obj

    bm = bmesh.new(use_operators=False)
    bm.from_mesh(m)

    # We add vertices to the mesh and de-interleave vertex properties to set them later
    deform_layer = bm.verts.layers.deform.verify()
    blend_weights = []
    blend_indices = []
    vertex_normals = []
    uv0 = []
    uv1 = []
    uv2 = []
    uv3 = []
    for ndo in tmc.nodelay.chunks:
        try:
            objgeo = tmc.mdlgeo.chunks[ndo.chunks[0].obj_index]
        except IndexError:
            continue
        wgt = ndo.metadata.name.startswith(b'MOT')
        gm = Matrix(tmc.glblmtx.chunks[ndo.metadata.node_index])
        for decl_idx, c in enumerate(objgeo.sub_container.chunks):
            blend_weights.extend(c.vertex_count * ((0, 0, 0, 0), ))
            blend_indices.extend(c.vertex_count * ((0, 0, 0, 0), ))
            uv0.extend(c.vertex_count * (Vector((0,0)), ))
            uv1.extend(c.vertex_count * (Vector((0,0)), ))
            uv2.extend(c.vertex_count * (Vector((0,0)), ))
            uv3.extend(c.vertex_count * (Vector((0,0)), ))
            vertex_normals.extend(c.vertex_count * (Vector((0,0,0)), ))
            V = tmc.vtxlay.chunks[c.vertex_buffer_index]
            I = tmc.idxlay.chunks[c.index_buffer_index]
            R = range(0, c.vertex_count*c.vertex_size, c.vertex_size)
            n = len(bm.verts)
            for e in c.vertex_elements:
                VO = enumerate(range(e.offset, R.stop, R.step), n)
                match e.usage:
                    case D3DDECLUSAGE.POSITION:
                        match e.d3d_decl_type:
                            case D3DDECLTYPE.FLOAT3:
                                for _, o in VO:
                                    v = bm.verts.new(Vector(V[o:o+12].cast('f')) @ gm)
                                    v[deform_layer][ndo.metadata.node_index] = wgt
                                bm.verts.ensure_lookup_table()
                                for c in objgeo.chunks:
                                    mtrcol_index = texmapinfo_to_matindex[c.texture_map_info]
                                    if c.geodecl_index == decl_idx:
                                        g, h = lambda x: x, reversed
                                        for i in range(c.first_index_index, c.first_index_index + c.index_count - 2):
                                            if I[i] != I[i+1] and I[i+1] != I[i+2] and I[i+2] != I[i]:
                                                try:
                                                    f = bm.faces.new( bm.verts[i + n] for i in g(I[i:i+3]) )
                                                    f.material_index = mtrcol_index
                                                except ValueError:
                                                    pass
                                            g, h = h, g
                            case x:
                                raise ValueError(f'Not supported vert decl type for position: {repr(x)}')
                    case D3DDECLUSAGE.BLENDWEIGHT:
                        match e.d3d_decl_type:
                            # The type is not actually UDEC3, but UBYTE4.
                            case D3DDECLTYPE.UDEC3:
                                for i, o in VO:
                                    blend_weights[i] = V[o:o+4]
                            case x:
                                raise ValueError(f'Not supported vert decl type for blendweight: {repr(x)}')
                    case D3DDECLUSAGE.BLENDINDICES:
                        match e.d3d_decl_type:
                            case D3DDECLTYPE.UBYTE4:
                                for i, o in VO:
                                    blend_indices[i] = V[o:o+4]
                            case x:
                                raise ValueError(f'Not supported vert decl type for blendindices: {repr(x)}')
                    case D3DDECLUSAGE.NORMAL:
                        match e.d3d_decl_type:
                            case D3DDECLTYPE.FLOAT3:
                                for i, o in VO:
                                    vertex_normals[i] = V[o:o+12].cast('f')
                            case x:
                                raise ValueError(f'Not supported vert decl type for normal: {repr(x)}')
                    case D3DDECLUSAGE.TEXCOORD:
                        match e.usage_index:
                            case 0:
                                # They are not "short", but actually "float16".
                                match e.d3d_decl_type:
                                    case D3DDECLTYPE.USHORT2N:
                                        for i, o in VO:
                                            uv0[i] = struct.unpack('ee', V[o:o+4])
                                            uv1[i] = struct.unpack('ee', V[o+4:o+8])
                                    case D3DDECLTYPE.SHORT4N:
                                        for i, o in VO:
                                            uv0[i] = struct.unpack('ee', V[o:o+4])
                                    case x:
                                        raise ValueError(f'Not supported vert decl type for texcoord: {repr(x)}')
                            case 1:
                                match e.d3d_decl_type:
                                    case D3DDECLTYPE.USHORT2N:
                                        for i, o in VO:
                                            uv2[i] = struct.unpack('ee', V[o:o+4])
                                            uv3[i] = struct.unpack('ee', V[o+4:o+8])
                                    case D3DDECLTYPE.SHORT4N:
                                        for i, o in VO:
                                            uv2[i] = struct.unpack('ee', V[o:o+4])
                                    case x:
                                        raise ValueError(f'Not supported vert decl type for texcoord: {repr(x)}')
                            case x:
                                raise ValueError(f'Not supported usage index for texcoord: {repr(x)}')
                    case D3DDECLUSAGE.TANGENT:
                        pass
                    case x:
                        raise ValueError(f'Not supported vert decl usage: {repr(x)}')

    bm.verts.index_update()

    # Let's assign vertices which has blend weight to corresponding vertex groups
    for v in bm.verts:
        vd = v[deform_layer]
        ng = tmc.nodelay.chunks[vd.keys()[0]].chunks[0].node_group
        for i, w in zip(blend_indices[v.index], blend_weights[v.index]):
            if w > 0:
                vd[ng[i]] = w/0xff

    # We add UVs
    l0 = bm.loops.layers.uv.new('UVMap0')
    l1 = bm.loops.layers.uv.new('UVMap1')
    l2 = bm.loops.layers.uv.new('UVMap2')
    l3 = bm.loops.layers.uv.new('UVMap3')
    for f in bm.faces:
        for lo in f.loops:
            uv = uv0[lo.vert.index]
            lo[l0].uv = (uv[0], 1-uv[1])
            uv = uv1[lo.vert.index]
            lo[l1].uv = (uv[0], 1-uv[1])
            uv = uv2[lo.vert.index]
            lo[l2].uv = (uv[0], 1-uv[1])
            uv = uv3[lo.vert.index]
            lo[l3].uv = (uv[0], 1-uv[1])

    # Custom normals still have to be set by calling normals_split_custom_set{_from_vertices}.
    for v in bm.verts:
        v.normal = vertex_normals[v.index]        

    #bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0000001)
    bm.to_mesh(mesh_obj.data)
    mesh_obj.data.normals_split_custom_set_from_vertices(tuple(v.normal for v in bm.verts))

    return {'FINISHED'}

def set_bone_tail(b):
    for c in b.children:
        if c.name.startswith('MOT'):
            match sum( 1 for cc in c.children if cc.name.startswith('MOT')):
                case 0:
                    c.tail = c.head + c.parent.matrix.to_3x3() @ Vector((0, .075, 0))
                case 1:
                    for cc in c.children:
                        if cc.name.startswith('MOT'):
                            c.tail = c.head + .075 * (cc.head - c.head).normalized()
                            break
                case x:
                    c.tail = c.head + c.parent.matrix.to_3x3() @ Vector((0, .075, 0))
            set_bone_tail(c)
        else:
            c.tail = c.head + c.parent.matrix.to_3x3() @ Vector((0, .075, 0))

class ImportTMC11(Operator, ImportHelper):
    '''Load a TMC file and a TMCL file (NGS2)'''
    bl_idname = 'ninja_gaiden_tmc.import_tmc11'
    bl_label = 'Import TMC/TMCL'

    filter_glob: StringProperty(
        default="*.tmc;*.tmcl;*.dat",
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    directory: bpy.props.StringProperty(
        subtype='FILE_PATH',
        options={'SKIP_SAVE', 'HIDDEN'}
    )
    files: CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'SKIP_SAVE', 'HIDDEN'}
    )

    def execute(self, context):
        if len(self.files) < 2:
            self.report({'ERROR'}, 'Select both a TMC file and a TMCL file')
            return {'CANCELLED'}

        f0 = os.path.join(self.directory, self.files[0].name)
        f1 = os.path.join(self.directory, self.files[1].name)
        with (open(f0, 'rb') as f0, open(f1, 'rb') as f1):
            m_f0 = mmap.mmap(f0.fileno(), 0, access=mmap.ACCESS_READ)
            m_f1 = mmap.mmap(f1.fileno(), 0, access=mmap.ACCESS_READ)
            tmc = TMCParser(m_f0, m_f1) if m_f0[:4] == b'TMC\x00' else TMCParser(context, m_f1, m_f0)
            return import_tmc11(context, tmc)
