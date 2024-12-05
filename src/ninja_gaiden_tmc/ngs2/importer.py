# NINJA GAIDEN Model Importer by Nozomi Miyamori is under the public domain
# and also marked with CC0 1.0. This file is a part of NINJA GAIDEN SIGMA 2 TMC Importer.

from .. import tcmlib
from ..tcmlib.ngs2 import (
    TextureUsage, D3DDECLUSAGE, D3DDECLTYPE, OBJ_TYPE
)
import bpy
import bmesh
from mathutils import Matrix, Vector, Euler

import math
import os, tempfile
import struct

def import_tmc(context, tmc):
    tmc_name = tmc.metadata.name.decode()
    collection_top = bpy.data.collections.new(tmc_name)
    context.collection.children.link(collection_top)

    yup_to_zup = Euler((.5 * math.pi, 0, 0)).to_matrix().to_4x4()

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
    context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')
    bone_names = []
    for n, mat, i in zip(tmc.nodelay.chunks, offset_matrices, tmc.obj_type_info.table):
        b = a.edit_bones.new(n.metadata.name.decode())
        bone_names.append(b.name)
        b.transform(mat)
        # We temporalily set obj type attribute for set_bones_tail function.
        b['obj_type'] = i[0]

    a.transform(yup_to_zup)

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

        mesh_obj.matrix_basis = mat
        mesh_obj.location = mesh_obj.location.xzy * Vector((1, -1, 1))
        r = mesh_obj.rotation_euler
        mesh_obj.rotation_euler = Euler((r.x, -r.z, r.y))
        mesh_obj.data.transform(yup_to_zup)

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
            #x.colorspace_settings.is_data = True
            x.name = tmc_name
            x.colorspace_settings.is_data = True
            x.pack()
            x.filepath_raw = ''
            images.append(x)
    os.remove(t.name)

    # We add material slots for each OBJGEO chunk
    objgeo_params_to_material = {}
    for i, objgeo in enumerate(tmc.mdlgeo.chunks):
        for c, ms in zip(objgeo.chunks, mesh_objs[i].material_slots):
            ms.link = 'OBJECT'
            t = (c.mtrcol_chunk_index, c.colored_transparency, c.show_backface, *c.texture_info_table)
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
            # TODO: set BLENDED for materials that causes black face issue.
            #if c.colored_transparency:
                #m.surface_render_method = 'BLENDED'
                #m.use_transparency_overlap = False

            shader_frame = m.node_tree.nodes.new('NodeFrame')
            pbsdf = m.node_tree.nodes["Principled BSDF"]
            pbsdf.parent = shader_frame
            pbsdf.inputs['Alpha'].default_value = 0
            pbsdf.distribution = 'GGX'
            pbsdf.inputs['Coat Weight'].default_value = .125
            pbsdf.inputs['Sheen Weight'].default_value = .125

            ao = m.node_tree.nodes.new('ShaderNodeAmbientOcclusion')
            ao.parent = shader_frame
            m.node_tree.links.new(ao.outputs['Color'], pbsdf.inputs['Base Color'])

            gam = m.node_tree.nodes.new('ShaderNodeGamma')
            gam.parent = shader_frame
            gam.inputs['Gamma'].default_value = 2.2
            m.node_tree.links.new(gam.outputs['Color'], ao.inputs['Color'])

            mul_add = m.node_tree.nodes.new('ShaderNodeVectorMath')
            mul_add.name = 'mtrcol_multiply_add'
            mul_add.parent = shader_frame
            mul_add.operation = 'MULTIPLY_ADD'
            m.node_tree.links.new(mul_add.outputs['Vector'], gam.inputs['Color'])

            set_material_parameters(m, mtrcol_chunk)

            uv_idx = 0
            uvnames = [ 'UVMap', 'UVMap.001', 'UVMap.002', 'UVMap.003' ]

            for t in c.texture_info_table:
                imgtex = m.node_tree.nodes.new('ShaderNodeTexImage')
                try:
                    imgtex.image = images[t.texture_index]
                except IndexError:
                    assert t.texture_index == -1
                    m.node_tree.nodes.remove(imgtex)
                    continue
                frame = m.node_tree.nodes.new('NodeFrame')
                imgtex.parent = frame

                uv = m.node_tree.nodes.new('ShaderNodeUVMap')
                uv.uv_map = uvnames[uv_idx]
                uv_idx += 1
                uv.parent = frame
                m.node_tree.links.new(uv.outputs['UV'], imgtex.inputs['Vector'])

                # We assume that "Colored with alpha" or "Alpha only" texture come first.
                match t.usage:
                    case TextureUsage.Albedo:
                        if t.color_usage not in { 0, 1, 3, 5 }:
                            raise Exception(f'Not supported albedo texture type: {repr(t.color_usage)}')

                        if t.color_usage == 0 or t.color_usage == 1:
                            mix = m.node_tree.nodes.new('ShaderNodeMix')
                            mix.parent = frame
                            mix.data_type = 'RGBA'
                            mix.inputs['Factor'].default_value = 1
                            m.node_tree.links.new(albedo_out, mix.inputs['A'])
                            m.node_tree.links.new(imgtex.outputs['Color'], mix.inputs['B'])
                            m.node_tree.links.new(mix.outputs['Result'], mul_add.inputs['Vector'])
                            if t.color_usage == 0:
                                frame.label = 'Black and White'
                                mix.blend_type= 'MULTIPLY'
                            elif t.color_usage == 1:
                                frame.label = 'Light'
                                mix.blend_type= 'LINEAR_LIGHT'
                        else:
                            if not mul_add.inputs['Vector'].is_linked:
                                vecm = m.node_tree.nodes.new('ShaderNodeVectorMath')
                                vecm.parent = frame
                                vecm.operation = 'MULTIPLY_ADD'
                                m.node_tree.links.new(vecm.outputs['Vector'], mul_add.inputs['Vector'])
                                albedo_uv = uv.uv_map
                                albedo_out = vecm.outputs['Vector']
                            if t.color_usage == 3:
                                frame.label = 'Alpha only'
                                m.node_tree.links.new(imgtex.outputs['Color'], vecm.inputs[0])
                                m.node_tree.links.new(imgtex.outputs['Alpha'], vecm.inputs[1])
                                m.node_tree.links.new(vecm.outputs[0], pbsdf.inputs['Alpha'])
                                albedo_in = vecm.inputs[0]
                            elif t.color_usage == 5:
                                if not vecm.inputs[0].is_linked:
                                    frame.label = 'Colored with alpha'
                                    m.node_tree.links.new(imgtex.outputs['Color'], vecm.inputs[0])
                                    m.node_tree.links.new(imgtex.outputs['Alpha'], vecm.inputs[1])
                                    m.node_tree.links.new(imgtex.outputs['Alpha'], pbsdf.inputs['Alpha'])
                                    albedo_in = vecm.inputs[2]
                                else:
                                    frame.label = 'Unused overlay'
                    case TextureUsage.Normal:
                        frame.label = 'Normal'
                        nml = m.node_tree.nodes.new('ShaderNodeNormalMap')
                        nml.parent = frame
                        nml.uv_map = uv.uv_map
                        vecm = m.node_tree.nodes.new('ShaderNodeVectorMath')
                        vecm.parent = frame
                        vecm.operation = 'MULTIPLY_ADD'
                        vecm.inputs[1].default_value = (1, -1, 1)
                        vecm.inputs[2].default_value = (0, 1, 0)
                        m.node_tree.links.new(nml.outputs['Normal'], pbsdf.inputs['Normal'])
                        m.node_tree.links.new(vecm.outputs['Vector'], nml.inputs['Color'])
                        m.node_tree.links.new(imgtex.outputs['Color'], vecm.inputs['Vector'])
                    case TextureUsage.Smoothness:
                        frame.label = 'Smoothness'
                        inv = m.node_tree.nodes.new('ShaderNodeVectorMath')
                        inv.parent = frame
                        inv.operation = 'SUBTRACT'
                        inv.inputs[0].default_value = (1, 1, 1)
                        grad = m.node_tree.nodes.new('ShaderNodeTexGradient')
                        grad.parent = frame
                        grad.gradient_type = 'LINEAR'
                        m.node_tree.links.new(imgtex.outputs['Color'], inv.inputs[1])
                        m.node_tree.links.new(inv.outputs[0], grad.inputs['Vector'])
                        m.node_tree.links.new(grad.outputs['Color'], pbsdf.inputs['Roughness'])
                    case TextureUsage.AlphaBlend:
                        frame.label = 'Alpha Blend'
                        uv.uv_map = albedo_uv
                        mul = m.node_tree.nodes.new('ShaderNodeMath')
                        mul.parent = frame
                        mul.operation = 'MULTIPLY'
                        m.node_tree.links.new(imgtex.outputs['Color'], mul.inputs[0])
                        m.node_tree.links.new(imgtex.outputs['Alpha'], mul.inputs[1])
                        m.node_tree.links.new(mul.outputs[0], albedo_in)
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
    n = material.node_tree.nodes['mtrcol_multiply_add']
    n.inputs[1].default_value = 1.375 * Vector(mtrcol_chunk.specular[:3])
    n.inputs[2].default_value = .375 * Vector(mtrcol_chunk.emission[:3])

    n = material.node_tree.nodes['Principled BSDF']
    v = Vector( mtrcol_chunk.specular_power[:3] )
    n.inputs['Metallic'].default_value = max(1 - v.normalized().length / (v.length + 1e-38), 0)
    n.inputs['IOR'].default_value = min(max(math.log10(1e-38+mtrcol_chunk.specular_power[3]), 1), 6)
    n.inputs['Specular Tint'].default_value = Vector( v**.454 for v in Vector(mtrcol_chunk.specular) * Vector(mtrcol_chunk.specular_power) )
    n.inputs['Coat Roughness'].default_value = mtrcol_chunk.coat[3]
    n.inputs['Coat Tint'].default_value = Vector( v**.454 for v in Vector(mtrcol_chunk.specular) * Vector(mtrcol_chunk.coat) )
    n.inputs['Sheen Roughness'].default_value = .5 * mtrcol_chunk.sheen[3]
    n.inputs['Sheen Tint'].default_value = Vector( v**.454 for v in Vector(mtrcol_chunk.specular) * Vector(mtrcol_chunk.sheen) )

def set_bones_tail(b):
    C = tuple( c for c in b.children if c['obj_type'] == OBJ_TYPE.MOT )
    n = len(C)
    if n == 0:
        try:
            x = b.parent.length if b['obj_type'] == OBJ_TYPE.MOT else 0.01
            b.tail = b.head + b.parent.matrix.to_3x3() @ Vector((0, x, 0))
        except AttributeError:
            b.tail = (0, .01, 0)
    else:
        H = tuple( c.head for c in C )
        b.tail = sum(H, Vector()) / len(H)

    if b.length < 0.01:
        try:
            b.tail = b.head + b.parent.matrix.to_3x3() @ Vector((0, 0.01, 0))
        except AttributeError:
            b.tail = (0, .01, 0)

    for c in b.children:
        set_bones_tail(c)
