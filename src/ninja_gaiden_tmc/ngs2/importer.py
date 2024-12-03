# NINJA GAIDEN Model Importer by Nozomi Miyamori is under the public domain
# and also marked with CC0 1.0. This file is a part of NINJA GAIDEN SIGMA 2 TMC Importer.

from .. import tcmlib
from ..tcmlib.ngs2 import (
    TextureUsage, D3DDECLUSAGE, D3DDECLTYPE, OBJ_TYPE
)
import bpy
import bmesh
from bpy_extras.io_utils import axis_conversion
from mathutils import Matrix, Vector

import math
import os, tempfile
import struct

def import_tmc(context, tmc):
    tmc_name = tmc.metadata.name.decode()
    collection_top = bpy.data.collections.new(tmc_name)
    context.collection.children.link(collection_top)

    # We form an armature.
    a = bpy.data.armatures.new(tmc_name)
    armature_obj = bpy.data.objects.new(a.name, a)
    collection_top.objects.link(armature_obj)
    a.collections.new('MOT').is_solo = True
    a.collections.new('NML')
    a.collections.new('OPT')
    a.collections.new('SUP')
    a.collections.new('WGT')
    a.collections.new('WPB')

    offset_matrices = len(tmc.hielay.chunks) * [None]
    M = tuple( Matrix((c.matrix[0:4], c.matrix[4:8], c.matrix[8:12], c.matrix[12:16])) for c in tmc.hielay.chunks )
    for k, c in enumerate(tmc.hielay.chunks):
        i = k
        m = M[i]
        while (i := tmc.hielay.chunks[i].parent) > -1:
            m = m @ M[i]
        offset_matrices[k] = m
    #offset_matrices = tuple( Matrix((c[0:4], c[4:8], c[8:12], c[12:16])) for c in tmc.glblmtx.chunks )
    for m in offset_matrices:
        m.transpose()

    active_obj_saved = context.view_layer.objects.active
    armature_obj.matrix_basis = axis_conversion(from_forward='-Z', from_up='Y').to_4x4()
    context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')
    bone_names = []
    for n, mat, i in zip(tmc.nodelay.chunks, offset_matrices, tmc.obj_type_info.table):
        b = a.edit_bones.new(n.metadata.name.decode())
        bone_names.append(b.name)
        b.transform(mat)
        # We temporalily set obj type attribute for set_bones_tail function.
        b['obj_type'] = i[0]

    R = []
    for c, b in zip(tmc.hielay.chunks, a.edit_bones):
        pi = c.parent
        if pi > -1:
            b.parent = a.edit_bones[pi]
        else:
            R.append(b)
    for r in R:
        set_bones_tail(r)
    bpy.ops.object.mode_set(mode='OBJECT')
    context.view_layer.objects.active = active_obj_saved

    for b in a.bones:
        try:
            x = OBJ_TYPE(b['obj_type']).name
            a.collections[x].assign(b)
        except KeyError:
            # Not categorized bone
            pass
        finally:
            del b['obj_type']

    # Let's add the mesh objects.
    collection_base = bpy.data.collections.new(tmc_name)
    collection_top.children.link(collection_base)
    mesh_objs = len(tmc.mdlgeo.chunks) * [None]
    for n, mat, objtype in zip(tmc.nodelay.chunks, offset_matrices, tmc.obj_type_info.table):
        objtype = objtype[0]
        # We use NodeObj's name because names in ObjGeo are omitted, although NodeObj has a full name.
        try:
            name = n.metadata.name.decode()
            n = n.chunks[0]
        except IndexError:
            continue
        objgeo = tmc.mdlgeo.chunks[n.obj_index]
        m = bpy.data.meshes.new(name)
        mesh_objs[n.obj_index] = mesh_obj = bpy.data.objects.new(m.name, m)
        collection_base.objects.link(mesh_obj)
        mesh_obj.parent = armature_obj
        mesh_obj.matrix_basis = mat
        t = tmc.obj_type_info.table[n.node_index]
        #mesh_obj.hide_set(t[:2] == (OBJ_TYPE.OPT, 1) or t[:2] == (OBJ_TYPE.OPT, 3))
        #mesh_obj.visible_camera = mesh_obj.visible_shadow = not mesh_obj.hide_select

        if objtype == OBJ_TYPE.SUP or objtype == OBJ_TYPE.WGT:
            for i in n.node_group:
                mesh_obj.vertex_groups.new(name=bone_names[i])
        else:
            mesh_obj.vertex_groups.new(name=bone_names[n.node_index])
        mesh_obj.modifiers.new('', 'ARMATURE').object = armature_obj

        for _ in range(len(objgeo.chunks)):
            m.materials.append(None)

        bm = bmesh.new(use_operators=False)
        uv_layers = (
                bm.loops.layers.uv.new('UVMap'),
                bm.loops.layers.uv.new('UVMap.001'),
                bm.loops.layers.uv.new('UVMap.002'),
                bm.loops.layers.uv.new('UVMap.003')
        )
        deform_layer = bm.verts.layers.deform.verify()
        
        for geodecl_chunk_index, c in enumerate(objgeo.sub_container.chunks):
            mesh_obj.vertex_groups.new(name="")
            VE = c.vertex_elements
            vbuf = tmc.vtxlay.chunks[c.vertex_buffer_index]

            # We assume that the first element is of D3DDECLUSAGE.POSITION.
            e = VE[0]
            if e.d3d_decl_type != D3DDECLTYPE.FLOAT3:
                raise Exception(f'Not supported vert decl type for position: {repr(x)}')

            O = range(e.offset, c.vertex_count*c.vertex_nbytes, c.vertex_nbytes)
            BV = c.vertex_count * [None]
            n = len(mesh_obj.vertex_groups)-1
            for i, o in enumerate(O):
                BV[i] = v = bm.verts.new(struct.unpack_from('< 3f', vbuf, o))
                v[deform_layer][n] = 0

            x = (c.vertex_count < 2**16 and 'H') or 'I'
            ibuf = tmc.idxlay.chunks[c.index_buffer_index].cast(x)
            BF = []
            for c in objgeo.chunks:
                if c.geodecl_chunk_index == geodecl_chunk_index:
                    g, h = lambda x: x, reversed
                    for i in range(c.first_index_index, c.first_index_index + c.index_count - 2):
                        try:
                            f = bm.faces.new( BV[i] for i in g(ibuf[i:i+3]) )
                        except ValueError:
                            pass
                        else:
                            f.material_index = c.objgeo_chunk_index
                            BF.append(f)
                        g, h = h, g

            bm.verts.index_update()
            BW = BI = ()
            for e in VE[1:]:
                O = range(e.offset, O.stop, O.step)
                t = e.d3d_decl_type
                match e.usage:
                    case D3DDECLUSAGE.BLENDWEIGHT:
                        # The type is not actually UDEC3, but UBYTE4.
                        if t != D3DDECLTYPE.UDEC3:
                            raise Exception(f'Not supported vert decl type for blendweight: {repr(t)}')
                        BW = ( struct.unpack_from('< BBBB', vbuf, o) for o in O )
                    case D3DDECLUSAGE.BLENDINDICES:
                        if t != D3DDECLTYPE.UBYTE4:
                            raise Exception(f'Not supported vert decl type for blendindices: {repr(t)}')
                        BI = ( struct.unpack_from('< BBBB', vbuf, o) for o in O )
                    case D3DDECLUSAGE.NORMAL:
                        if t != D3DDECLTYPE.FLOAT3:
                            raise Exception(f'Not supported vert decl type for normal: {repr(t)}')
                        for v, o in zip(BV, O):
                            v.normal = struct.unpack_from('< 3f', vbuf, o)
                    case D3DDECLUSAGE.TEXCOORD:
                        # They are not "short", but actually "float16".
                        if all((t != D3DDECLTYPE.USHORT2N, t != D3DDECLTYPE.SHORT4N)):
                            raise Exception(f'Not supported vert decl type for texcoord: {repr(t)}')
                        if e.usage_index > 1:
                            raise Exception(f'Not supported usage index for texcoord: {repr(x)}')

                        v0 = len(bm.verts) - len(BV)
                        i = 2*e.usage_index
                        if t == D3DDECLTYPE.USHORT2N:
                            for f in BF:
                                for lo in f.loops:
                                    x = struct.unpack_from('< 4e', vbuf, O[lo.vert.index - v0])
                                    lo[uv_layers[i]].uv = x[0], 1-x[1]
                                    lo[uv_layers[i+1]].uv = x[2], 1-x[3]
                        else:
                            for f in BF:
                                for lo in f.loops:
                                    x = struct.unpack_from('< 2e', vbuf, O[lo.vert.index - v0])
                                    lo[uv_layers[i]].uv = x[0], 1-x[1]
                    case D3DDECLUSAGE.TANGENT:
                        pass
                    case D3DDECLUSAGE.COLOR:
                        pass
                    case x:
                        raise Exception(f'Not supported vert decl usage: {repr(x)}')

            # Let's assign vertices which has blend weight to corresponding vertex groups
            for v, I, W in zip(BV, BI, BW):
                dl = v[deform_layer]
                y = 0
                for i, w in zip(I, W):
                    dl[i] = w/0xff
                    y += w
                    if y == 0xff:
                        break

        if objtype != OBJ_TYPE.SUP and objtype != OBJ_TYPE.WGT:
            for v in bm.verts:
                v[deform_layer][0] = 1

        bm.to_mesh(mesh_obj.data)
        mesh_obj.data.normals_split_custom_set_from_vertices(tuple(v.normal for v in bm.verts))
        bm.free()

    # We load textures
    # TODO: Use delete_on_close=False instead of delete=False when Blender has begun to ship Python 3.12
    images = []
    with tempfile.NamedTemporaryFile(delete=False) as t:
        t.close()
        for i, c in enumerate(tmc.ttdm.metadata.chunks):
            with open(t.name, t.file.mode) as f:
                if c.in_ttdl:
                    x = tmc.ttdm.sub_container.chunks[c.chunk_index]
                else:
                    x = tmc.ttdm.chunks[c.chunk_index]
                f.write(x)
            x = bpy.data.images.load(t.name)
            x.name = tmc_name
            x.pack()
            x.filepath_raw = ''
            images.append(x)
    os.remove(t.name)

    # We add material slots for each OBJGEO chunk
    objgeo_params_to_material = {}
    for i, objgeo in enumerate(tmc.mdlgeo.chunks):
        for c, ms in zip(objgeo.chunks, mesh_objs[i].material_slots):
            ms.link = 'OBJECT'
            t = (c.mtrcol_chunk_index, c.show_backface, *c.texture_info_table)
            try:
                # We use an existing material as long as possible.
                ms.material = m = objgeo_params_to_material[t]
                continue
            except KeyError:
                pass
            mtrcol_chunk = tmc.mtrcol.chunks[c.mtrcol_chunk_index]

            m = bpy.data.materials.new(tmc_name)
            m['mtrcol'] = mtrcol_chunk.mtrcol_chunk_index
            objgeo_params_to_material[t] = ms.material = m
            m.preview_render_type = 'FLAT'
            m.use_nodes = True
            m.use_backface_culling = m.use_backface_culling_shadow = not c.show_backface

            shader_frame = m.node_tree.nodes.new('NodeFrame')
            pbsdf = m.node_tree.nodes["Principled BSDF"]
            pbsdf.parent = shader_frame
            pbsdf.distribution = 'GGX'
            pbsdf.inputs['Coat Roughness'].default_value = .5
            pbsdf.inputs['Sheen Weight'].default_value = .125

            base_spec_mix = m.node_tree.nodes.new('ShaderNodeMix')
            base_spec_mix.name = 'mtrcol_base_spec'
            base_spec_mix.parent = shader_frame
            base_spec_mix.data_type = 'RGBA'
            base_spec_mix.blend_type = 'MULTIPLY'
            base_spec_mix.inputs[0].default_value = 1
            m.node_tree.links.new(base_spec_mix.outputs['Result'], pbsdf.inputs['Base Color'])

            base_color_mix = m.node_tree.nodes.new('ShaderNodeMix')
            base_color_mix.name = 'mtrcol_base_color'
            base_color_mix.parent = shader_frame
            base_color_mix.data_type = 'RGBA'
            base_color_mix.blend_type = 'SCREEN'
            m.node_tree.links.new(base_color_mix.outputs['Result'], base_spec_mix.inputs['A'])

            spec_mix = m.node_tree.nodes.new('ShaderNodeMix')
            spec_mix.name = 'mtrcol_specular'
            spec_mix.parent = shader_frame
            spec_mix.data_type = 'RGBA'
            spec_mix.blend_type = 'MULTIPLY'
            spec_mix.inputs['Factor'].default_value = 1
            m.node_tree.links.new(spec_mix.outputs['Result'], pbsdf.inputs['Specular Tint'])

            set_material_parameters(m, mtrcol_chunk)

            uv_idx = 0
            uvnames = [ 'UVMap', 'UVMap.001', 'UVMap.002', 'UVMap.003' ]

            textures_frame = m.node_tree.nodes.new('NodeFrame')
            textures_frame.label = 'Textures'
            for t in c.texture_info_table:
                ti = m.node_tree.nodes.new('ShaderNodeTexImage')
                try:
                    ti.image = images[t.texture_index]
                except IndexError:
                    assert t.texture_index == -1
                    m.node_tree.nodes.remove(ti)
                    continue
                frame = m.node_tree.nodes.new('NodeFrame')
                frame.parent = textures_frame
                ti.parent = frame

                uv = m.node_tree.nodes.new('ShaderNodeUVMap')
                uv.uv_map = uvnames[uv_idx]
                uv_idx += 1
                uv.parent = frame
                m.node_tree.links.new(uv.outputs['UV'], ti.inputs['Vector'])

                match t.usage:
                    case TextureUsage.Albedo:
                        if t.color_usage == 0 or t.color_usage == 1:
                            albedo_mix = m.node_tree.nodes.new('ShaderNodeMix')
                            albedo_mix.parent = textures_frame
                            albedo_mix.data_type = 'RGBA'
                            albedo_mix.blend_type = 'ADD'
                            albedo_mix.inputs['B'].default_value = 4*(0,)
                            m.node_tree.links.new(base_color_albedo.outputs['Color'], albedo_mix.inputs['Factor'])
                            m.node_tree.links.new(base_color_albedo.outputs['Color'], albedo_mix.inputs['A'])
                            m.node_tree.links.new(ti.outputs['Color'], albedo_mix.inputs['B'])
                            m.node_tree.links.new(albedo_mix.outputs['Result'], base_color_mix.inputs['Factor'])
                            m.node_tree.links.new(albedo_mix.outputs['Result'], base_color_mix.inputs['A'])
                        else:
                            if not base_color_mix.inputs['A'].is_linked:
                                m.node_tree.links.new(ti.outputs['Color'], base_color_mix.inputs['Factor'])
                                m.node_tree.links.new(ti.outputs['Color'], base_color_mix.inputs['A'])
                                base_color_albedo = ti
                                base_color_albedo_uv = uv.uv_map

                        if t.color_usage == 0:
                            ti.label = frame.label = 'Diffuse Texture (Light)'
                            albedo_mix.blend_type = 'LINEAR_LIGHT'
                        elif t.color_usage == 1:
                            ti.label = frame.label = 'Diffuse Texture (Screen)'
                            albedo_mix.blend_type = 'SCREEN'
                        elif t.color_usage == 3:
                            ti.label = frame.label = 'Diffuse Texture (Shadow)'
                            m.node_tree.links.new(ti.outputs['Color'], pbsdf.inputs['Alpha'])
                            is_shadow = True
                        elif t.color_usage == 5:
                            ti.label = frame.label = 'Diffuse Texture'
                            m.node_tree.links.new(ti.outputs['Alpha'], pbsdf.inputs['Alpha'])
                            is_shadow = False
                        else:
                            raise Exception(f'Not supported albedo texture type: {repr(t.color_usage)}')
                    case TextureUsage.Normal:
                        ti.label = frame.label = 'Normal Texture'
                        ti.image.colorspace_settings.name = 'Non-Color'
                        nml = m.node_tree.nodes.new('ShaderNodeNormalMap')
                        nml.parent = frame
                        nml.uv_map = uv.uv_map
                        curv = m.node_tree.nodes.new('ShaderNodeRGBCurve')
                        curv.parent = frame
                        curv.mapping.curves[1].points[0].location = (0, 1)
                        curv.mapping.curves[1].points[1].location = (1, 0)
                        m.node_tree.links.new(nml.outputs['Normal'], pbsdf.inputs['Normal'])
                        m.node_tree.links.new(curv.outputs['Color'], nml.inputs['Color'])
                        m.node_tree.links.new(ti.outputs['Color'], curv.inputs['Color'])
                    case TextureUsage.Smoothness:
                        ti.label = frame.label = 'Smoothness Texture'
                        ti.image.colorspace_settings.name = 'Non-Color'
                        inv = m.node_tree.nodes.new('ShaderNodeInvert')
                        inv.parent = frame
                        inv.inputs['Fac'].default_value = .5
                        m.node_tree.links.new(inv.outputs['Color'], pbsdf.inputs['Roughness'])
                        m.node_tree.links.new(ti.outputs['Color'], inv.inputs['Color'])
                    case TextureUsage.Add:
                        ti.label = frame.label = 'Additive Texture'
                        uv.uv_map = base_color_albedo_uv
                        mix = m.node_tree.nodes.new('ShaderNodeMix')
                        mix.parent = textures_frame
                        mix.data_type = 'RGBA'
                        mix.blend_type = 'ADD'
                        mix.inputs['Factor'].default_value = 0
                        m.node_tree.links.new(ti.outputs['Color'], mix.inputs['Factor'])
                        if is_shadow:
                            mul = m.node_tree.nodes.new('ShaderNodeMath')
                            mul.operation = 'MULTIPLY'
                            m.node_tree.links.new(ti.outputs['Color'], mul.inputs[0])
                            m.node_tree.links.new(ti.outputs['Alpha'], mul.inputs[1])
                            m.node_tree.links.new(mul.outputs[0], pbsdf.inputs['Alpha'])
                            m.node_tree.links.new(base_color_albedo.outputs['Alpha'], mix.inputs['A'])
                            m.node_tree.links.new(base_color_albedo.outputs['Color'], mix.inputs['Factor'])
                        else:
                            m.node_tree.links.new(base_color_albedo.outputs['Color'], mix.inputs['A'])
                        m.node_tree.links.new(ti.outputs['Color'], mix.inputs['B'])
                        m.node_tree.links.new(mix.outputs['Result'], base_color_mix.inputs['Factor'])
                        m.node_tree.links.new(mix.outputs['Result'], base_color_mix.inputs['A'])
                    case x:
                        raise Exception(f'Not supported texture map usage: {repr(x)}')

    try:
        V = tmc.mtrlchng.color_variants
    except AttributeError:
        pass
    else:
        for var in V:
            C = bpy.data.collections.new(tmc_name)
            collection_top.children.link(C)
            M = { m: m.copy() for m in objgeo_params_to_material.values() }
            for m in M.values():
                set_material_parameters(m, var[m["mtrcol"]])
            for i, mo in enumerate(mesh_objs):
                o = mo.copy()
                C.objects.link(o)
                o.parent = armature_obj
                for j, ms in enumerate(o.material_slots):
                    ms.material = M[ms.material]

def set_material_parameters(material, mtrcol_chunk):
    n = material.node_tree.nodes['Principled BSDF']
    n.inputs['Metallic'].default_value = min(math.log10(1+Vector(mtrcol_chunk.specular_power[:3]).length), 1)
    n.inputs['IOR'].default_value = max(min(.5*math.log(1+mtrcol_chunk.specular_power[3]), 4), 1)
    n.inputs['Coat Tint'].default_value = mtrcol_chunk.coat
    n.inputs['Coat Weight'].default_value = mtrcol_chunk.coat[3]
    n.inputs['Sheen Tint'].default_value = mtrcol_chunk.sheen
    n.inputs['Sheen Roughness'].default_value = mtrcol_chunk.sheen[3]

    n = material.node_tree.nodes['mtrcol_base_spec']
    n.inputs['B'].default_value = mtrcol_chunk.specular

    n = material.node_tree.nodes['mtrcol_base_color']
    n.inputs['B'].default_value = mtrcol_chunk.emission

    n = material.node_tree.nodes['mtrcol_specular']
    n.inputs['A'].default_value = mtrcol_chunk.specular
    n.inputs['B'].default_value = mtrcol_chunk.specular_power

def set_bones_tail(b):
    C = tuple( c for c in b.children if c['obj_type'] == OBJ_TYPE.MOT )
    n = len(C)
    if n == 0:
        try:
            x = b.parent.length if b['obj_type'] == OBJ_TYPE.MOT else 0.01
            b.tail = b.head + b.parent.matrix.to_3x3() @ Vector((0, x, 0))
        except AttributeError:
            b.tail = (0, .01, 0)
    elif n == 1:
        b.tail = b.children[0].head
    else:
        H = tuple( c.head for c in C )
        b.tail = sum(H, Vector()) / len(H)

    for c in b.children:
        set_bones_tail(c)
