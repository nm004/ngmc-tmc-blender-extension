# NINJA GAIDEN SIGMA 2 TMC Importer by Nozomi Miyamori is under the public domain
# and also marked with CC0 1.0. This file is a part of NINJA GAIDEN SIGMA 2 TMC Importer.

from . import tcmlib
from .tcmlib.ngs2 import (
    TextureUsage, D3DDECLUSAGE, D3DDECLTYPE, MTRLCHNGParser
)
import bpy
import bmesh
from bpy_extras.io_utils import axis_conversion
from mathutils import Matrix, Vector

import os, tempfile
import struct

def import_ngs2_tmc(context, tmc):
    new_collection = bpy.data.collections.new(tmc.metadata.name.decode())
    context.collection.children.link(new_collection)

    # We form an armature first
    a = bpy.data.armatures.new(new_collection.name)
    armature_obj = bpy.data.objects.new(a.name, a)
    armature_obj.matrix_world  = axis_conversion(from_forward='-Z', from_up='Y').to_4x4()
    new_collection.objects.link(armature_obj)

    active_obj_saved = context.view_layer.objects.active
    context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')
    for c in tmc.nodelay.chunks:
        gm = tmc.glblmtx.chunks[c.metadata.node_index]
        b = a.edit_bones.new(c.metadata.name.decode())
        b.matrix = (gm[0:4], gm[4:8], gm[8:12], gm[12:16])

    R = []
    for c in tmc.nodelay.chunks:
        i = c.metadata.node_index
        pi = tmc.hielay.chunks[i].parent
        if pi > -1:
            a.edit_bones[i].parent = a.edit_bones[pi]
        else:
            R.append(a.edit_bones[i])
    for r in R:
        set_bones_tail(r)
    bpy.ops.object.mode_set(mode='OBJECT')
    context.view_layer.objects.active = active_obj_saved

    a = armature_obj.data
    a.collections.new('MOT').is_solo = True
    a.collections.new('NML')
    a.collections.new('OPT')
    a.collections.new('SUP')
    a.collections.new('WGT')
    a.collections.new('WPB')
    for b in a.bones:
        try:
            a.collections[b.name[:3]].assign(b)
        except KeyError:
            # Not categorized bone
            pass
    for c in a.collections.values():
        if not len(c.bones):
            a.collections.remove(c)

    # We form a mesh below
    m = bpy.data.meshes.new(armature_obj.name)
    mat = bpy.data.materials.new(m.name)
    m.materials.append(mat)
    mat.preview_render_type = 'FLAT'
    mat.use_nodes = True
    mat.use_backface_culling = True
    mat.use_backface_culling_lightprobe_volume = True
    mat.use_backface_culling_shadow = True
    n = mat.node_tree.nodes["Principled BSDF"]
    n.inputs['Alpha'].default_value = 0
    mat.node_tree.links.new(n.outputs[0], mat.node_tree.nodes["Material Output"].inputs[0])

    mesh_obj = bpy.data.objects.new(m.name, m)
    mesh_obj.parent = armature_obj
    new_collection.objects.link(mesh_obj)

    for noc in tmc.nodelay.chunks:
        mesh_obj.vertex_groups.new(name=noc.metadata.name.decode())
    md = mesh_obj.modifiers.new('', 'ARMATURE')
    md.object = armature_obj

    for c in tmc.mtrcol.chunks:
        s = f'MtrCol{c.mtrcol_index:02} '
        mesh_obj[s + 'Mix'] = c.mix
        mesh_obj[s + 'Diffuse'] = c.diffuse
        mesh_obj[s + 'Specular'] = c.specular
        mesh_obj[s + 'Emission Power'] = c.diffuse_emission_power
        mesh_obj[s + 'Coat'] = c.coat
        mesh_obj[s + 'Sheen'] = c.sheen

    try:
        mtrlchng = MTRLCHNGParser(tmc._chunks[13+5])
    except (IndexError, tcmlib.ParserError):
        pass
    else:
        m = mesh_obj.data
        with mtrlchng:
            for V in mtrlchng.color_variants:
                mo = mesh_obj.copy()
                new_collection.objects.link(mo)
                for i, c in enumerate(V):
                    s = f'MtrCol{i:02} '
                    mo[s + 'Mix'] = c.mix
                    mo[s + 'Diffuse'] = c.diffuse
                    mo[s + 'Specular'] = c.specular
                    mo[s + 'Emission Power'] = c.diffuse_emission_power
                    mo[s + 'Coat'] = c.coat
                    mo[s + 'Sheen'] = c.sheen

    # We load textures
    # TODO: Use delete_on_close=False instead of delete=False when Blender has begun to ship Python 3.12
    images = []
    with tempfile.NamedTemporaryFile(delete=False) as t:
        for i, c in enumerate(tmc.ttdm.metadata.chunks):
            t.close()
            with open(t.name, t.file.mode) as f:
                if c.in_ttdl:
                    f.write(tmc.ttdm.sub_container.chunks[c.chunk_index])
                else:
                    f.write(tmc.ttdm.chunks[c.chunk_index])
            x = bpy.data.images.load(t.name)
            images.append(x)
            x.pack()
            x.name = mesh_obj.data.name.translate(str.maketrans('.', '_'))
            x.filepath_raw = ''
    os.remove(t.name)

    # We add material slots for each OBJGEO chunk
    uvnames = [ 'UVMap', 'UVMap.001', 'UVMap.002', 'UVMap.003' ]
    matindex = 1
    objchunk_to_matindex = [ [] for _ in range(len(tmc.mdlgeo.chunks)) ]
    mtrcol_texture_to_matindex = {}
    # We use NODEOBJs because names in OBJGEO are omitted, although NODEOBJ has a full name.
    for c in tmc.nodelay.chunks:
        try:
            objgeo = tmc.mdlgeo.chunks[c.chunks[0].obj_index]
        except IndexError:
            continue
        objname = c.metadata.name.decode()
        for c in objgeo.chunks:
            if c.vertex_count < 3 or not len(c.texture_info_table):
                objchunk_to_matindex[objgeo.metadata.obj_index].append(0)
                continue

            t = (c.mtrcol_index,) + c.texture_info_table
            try:
                i = mtrcol_texture_to_matindex[t]
            except KeyError:
                objchunk_to_matindex[objgeo.metadata.obj_index].append(matindex)
                mtrcol_texture_to_matindex[t] = matindex
            else:
                # We use an existing material
                objchunk_to_matindex[objgeo.metadata.obj_index].append(i)
                m = mesh_obj.data.materials[i]
                m.name += ' ' + objname + '.' + str(c.objgeo_chunk_index)
                mesh_obj.data.materials.append(m)
                continue
            finally:
                matindex += 1

            m = bpy.data.materials.new(mesh_obj.data.name + ' ' + objname + '.' + str(c.objgeo_chunk_index))
            mesh_obj.data.materials.append(m)
            m.preview_render_type = 'FLAT'
            m.use_nodes = True
            m.use_backface_culling = not c.show_backface
            m.use_backface_culling_lightprobe_volume = True
            m.use_backface_culling_shadow = not c.show_backface

            pbsdf = m.node_tree.nodes["Principled BSDF"]
            pbsdf.inputs['Coat Roughness'].default_value = .5
            pbsdf.inputs['Sheen Weight'].default_value = 1

            A = lambda x: f'["MtrCol{c.mtrcol_index:02} {x}"]'

            f = m.node_tree.nodes.new('NodeFrame')
            f.label = 'Coat'
            mul = m.node_tree.nodes.new('ShaderNodeMath')
            mul.parent = f
            mul.operation = 'MULTIPLY'
            mul.inputs[0].default_value = .25
            coat_input = m.node_tree.nodes.new('ShaderNodeAttribute')
            coat_input.parent = f
            coat_input.attribute_type = 'OBJECT'
            coat_input.attribute_name = A('Coat')
            m.node_tree.links.new(coat_input.outputs['Alpha'], mul.inputs[1])
            m.node_tree.links.new(mul.outputs[0], pbsdf.inputs['Coat Weight'])
            m.node_tree.links.new(coat_input.outputs['Color'], pbsdf.inputs['Coat Tint'])

            f = m.node_tree.nodes.new('NodeFrame')
            f.label = 'Sheen'
            mul = m.node_tree.nodes.new('ShaderNodeMath')
            mul.parent = f
            mul.operation = 'MULTIPLY'
            mul.inputs[0].default_value = .25
            sheen_input = m.node_tree.nodes.new('ShaderNodeAttribute')
            sheen_input.parent = f
            sheen_input.attribute_type = 'OBJECT'
            sheen_input.attribute_name = A('Sheen')
            m.node_tree.links.new(sheen_input.outputs['Alpha'], mul.inputs[1])
            m.node_tree.links.new(mul.outputs[0], pbsdf.inputs['Sheen Weight'])
            m.node_tree.links.new(sheen_input.outputs['Color'], pbsdf.inputs['Sheen Tint'])

            f = m.node_tree.nodes.new('NodeFrame')
            f.label = 'Emission'
            mul = m.node_tree.nodes.new('ShaderNodeMath')
            mul.parent = f
            mul.operation = 'MULTIPLY'
            mul.inputs[0].default_value = .5
            emission_input = m.node_tree.nodes.new('ShaderNodeAttribute')
            emission_input.parent = f
            emission_input.attribute_type = 'OBJECT'
            emission_input.attribute_name = A('Emission Power')
            m.node_tree.links.new(emission_input.outputs['Fac'], mul.inputs[1])
            m.node_tree.links.new(mul.outputs[0], pbsdf.inputs['Emission Strength'])


            f = m.node_tree.nodes.new('NodeFrame')
            f.label = 'Mix'
            diffuse_mix = m.node_tree.nodes.new('ShaderNodeMix')
            diffuse_mix.parent = f
            diffuse_mix.data_type = 'RGBA'
            diffuse_mix.blend_type = 'MIX'
            diffuse_mix.inputs['Factor'].default_value = .125
            m.node_tree.links.new(diffuse_mix.outputs['Result'], pbsdf.inputs['Base Color'])
            m.node_tree.links.new(diffuse_mix.outputs['Result'], pbsdf.inputs['Emission Color'])

            diffuse_mix_input = m.node_tree.nodes.new('ShaderNodeAttribute')
            diffuse_mix_input.parent = f
            diffuse_mix_input.attribute_type = 'OBJECT'
            diffuse_mix_input.attribute_name = A('Mix')
            m.node_tree.links.new(diffuse_mix_input.outputs['Color'], diffuse_mix.inputs['B'])

            f = m.node_tree.nodes.new('NodeFrame')
            f.label = 'Diffuse'
            diffuse_multiply = m.node_tree.nodes.new('ShaderNodeMix')
            diffuse_multiply.parent = f
            diffuse_multiply.data_type = 'RGBA'
            diffuse_multiply.blend_type = 'MULTIPLY'
            diffuse_multiply.inputs[0].default_value = 1
            m.node_tree.links.new(diffuse_multiply.outputs['Result'], diffuse_mix.inputs['A'])
            m.node_tree.links.new(diffuse_multiply.outputs['Result'], pbsdf.inputs['Specular Tint'])

            diffuse_multiply_input = m.node_tree.nodes.new('ShaderNodeAttribute')
            diffuse_multiply_input.parent = f
            diffuse_multiply_input.attribute_type = 'OBJECT'
            diffuse_multiply_input.attribute_name = A('Diffuse')
            m.node_tree.links.new(diffuse_multiply_input.outputs['Color'], diffuse_multiply.inputs['B'])


            f = m.node_tree.nodes.new('NodeFrame')
            f.label = 'Specular'
            specular_scale = m.node_tree.nodes.new('ShaderNodeVectorMath')
            specular_scale.parent = f
            specular_scale.name = 'specular'
            specular_scale.operation = 'SCALE'
            specular_scale.inputs['Scale'].default_value = 0.5
            m.node_tree.links.new(specular_scale.outputs[0], pbsdf.inputs['Metallic'])

            mul = m.node_tree.nodes.new('ShaderNodeVectorMath')
            mul.parent = f
            mul.operation = 'SCALE'
            mul.inputs['Scale'].default_value = .5
            specular_scale_input = m.node_tree.nodes.new('ShaderNodeAttribute')
            specular_scale_input.parent = f
            specular_scale_input.attribute_type = 'OBJECT'
            specular_scale_input.attribute_name = A('Specular')
            m.node_tree.links.new(specular_scale_input.outputs['Color'], mul.inputs['Vector'])
            m.node_tree.links.new(mul.outputs[0], specular_scale.inputs['Vector'])

            add = m.node_tree.nodes.new('ShaderNodeMath')
            add.parent = f
            add.operation = 'ADD'
            add.inputs[1].default_value = 1e-10
            div = m.node_tree.nodes.new('ShaderNodeMath')
            div.parent = f
            div.operation = 'DIVIDE'
            div.inputs[0].default_value = 1
            m.node_tree.links.new(specular_scale_input.outputs['Alpha'], pbsdf.inputs['IOR'])
            m.node_tree.links.new(specular_scale_input.outputs['Alpha'], add.inputs[0])
            m.node_tree.links.new(add.outputs[0], div.inputs[1])
            m.node_tree.links.new(div.outputs[0], pbsdf.inputs['Specular IOR Level'])


            texture_mix = m.node_tree.nodes.new('ShaderNodeMix')
            texture_mix.data_type = 'RGBA'
            texture_mix.blend_type = 'ADD'
            texture_mix.inputs['Factor'].default_value = 1
            texture_mix.inputs['A'].default_value = 4*(0,)
            texture_mix.inputs['B'].default_value = 4*(1,)
            m.node_tree.links.new(texture_mix.outputs['Result'], diffuse_multiply.inputs['A'])

            uv_idx = 0
            for t in c.texture_info_table:
                frame = m.node_tree.nodes.new('NodeFrame')
                ti = m.node_tree.nodes.new('ShaderNodeTexImage')
                ti.image = images[t.texture_index]
                ti.parent = frame

                uv = m.node_tree.nodes.new('ShaderNodeUVMap')
                uv.uv_map = uvnames[uv_idx]
                uv_idx += 1
                uv.parent = frame
                m.node_tree.links.new(uv.outputs['UV'], ti.inputs['Vector'])

                match t.usage:
                    case TextureUsage.Albedo:
                        match t.color_usage:
                            case 0:
                                ti.label = frame.label = 'Metalness Texture'
                                m.node_tree.links.new(ti.outputs['Color'], specular_scale.inputs['Scale'])
                            case 1:
                                ti.label = frame.label = 'Smoothness Texture'
                                inv = m.node_tree.nodes.new('ShaderNodeInvert')
                                inv.parent = frame
                                m.node_tree.links.new(inv.outputs['Color'], pbsdf.inputs['Roughness'])
                                m.node_tree.links.new(ti.outputs['Color'], inv.inputs['Color'])
                            case 3:
                                ti.label = frame.label = 'Shadow Texture'
                                texture_mix.parent = frame
                                mul = m.node_tree.nodes.new('ShaderNodeMath')
                                mul.operation = 'MULTIPLY'
                                m.node_tree.links.new(texture_mix.outputs['Result'], mul.inputs[0])
                                m.node_tree.links.new(ti.outputs['Alpha'], mul.inputs[1])
                                m.node_tree.links.new(mul.outputs[0], pbsdf.inputs['Alpha'])
                            case 5:
                                ti.label = frame.label = 'Diffuse Texture'
                                texture_mix.inputs['Factor'].default_value = 0
                                # It always uses first uv.
                                uv.uv_map = uvnames[0]
                                if not texture_mix.inputs['A'].is_linked:
                                    texture_mix.parent = frame
                                    m.node_tree.links.new(ti.outputs['Color'], texture_mix.inputs['A'])
                                    m.node_tree.links.new(ti.outputs['Alpha'], pbsdf.inputs['Alpha'])
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
                    case TextureUsage.Multiply:
                        ti.label = frame.label = 'Multiplicative Texture'
                        texture_mix.blend_type = 'MULTIPLY'
                        gam = m.node_tree.nodes.new('ShaderNodeGamma')
                        gam.parent = frame
                        gam.inputs['Gamma'].default_value = 2.2
                        m.node_tree.links.new(gam.outputs['Color'], texture_mix.inputs['Factor'])
                        m.node_tree.links.new(ti.outputs['Color'], gam.inputs['Color'])
                        m.node_tree.links.new(ti.outputs['Color'], texture_mix.inputs['B'])
                    case TextureUsage.Add:
                        ti.label = frame.label = 'Additive Texture'
                        # It always uses first uv
                        uv.uv_map = uvnames[0]
                        texture_mix.blend_type = 'ADD'
                        m.node_tree.links.new(ti.outputs['Alpha'], texture_mix.inputs['Factor'])
                        m.node_tree.links.new(ti.outputs['Color'], texture_mix.inputs['B'])
                    case x:
                        raise Exception(f'Not supported texture map usage: {repr(x)}')

    bm = bmesh.new(use_operators=False)
    bm.from_mesh(mesh_obj.data)

    # We add vertices to the mesh and de-interleave vertex properties to set them later
    deform_layer = bm.verts.layers.deform.verify()
    blend_weights = []
    blend_indices = []
    vertex_normals = []
    uv0 = []
    uv1 = []
    uv2 = []
    uv3 = []
    for c in tmc.nodelay.chunks:
        try:
            objgeo = tmc.mdlgeo.chunks[c.chunks[0].obj_index]
        except IndexError:
            continue
        nidx = c.metadata.node_index
        wgt = c.metadata.name.startswith(b'MOT') or c.metadata.name.startswith(b'OPT')
        gm = tmc.glblmtx.chunks[nidx]
        gm = Matrix((gm[0:4], gm[4:8], gm[8:12], gm[12:16]))
        name = c.metadata.name
        for idx, c in enumerate(objgeo.sub_container.chunks):
            blend_weights.extend(c.vertex_count * ((0, 0, 0, 0), ))
            blend_indices.extend(c.vertex_count * ((0, 0, 0, 0), ))
            uv0.extend(c.vertex_count * (Vector((0,0)), ))
            uv1.extend(c.vertex_count * (Vector((0,0)), ))
            uv2.extend(c.vertex_count * (Vector((0,0)), ))
            uv3.extend(c.vertex_count * (Vector((0,0)), ))
            vertex_normals.extend(c.vertex_count * (Vector((0,0,0)), ))
            V = tmc.vtxlay.chunks[c.vertex_buffer_index]
            x = (c.vertex_count < 1<<16 and 'H') or 'I'
            I = tmc.idxlay.chunks[c.index_buffer_index].cast(x)
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
                                    v[deform_layer][nidx] = wgt
                                bm.verts.ensure_lookup_table()
                                for c in objgeo.chunks:
                                    material_index = objchunk_to_matindex[objgeo.metadata.obj_index][c.objgeo_chunk_index]
                                    if c.geodecl_chunk_index == idx:
                                        g, h = lambda x: x, reversed
                                        for i in range(c.first_index_index, c.first_index_index + c.index_count - 2):
                                            try:
                                                f = bm.faces.new( bm.verts[i + n] for i in g(I[i:i+3]) )
                                                f.material_index = material_index
                                            except ValueError:
                                                pass
                                            g, h = h, g
                            case x:
                                raise Exception(f'Not supported vert decl type for position: {repr(x)}')
                    case D3DDECLUSAGE.BLENDWEIGHT:
                        match e.d3d_decl_type:
                            # The type is not actually UDEC3, but UBYTE4.
                            case D3DDECLTYPE.UDEC3:
                                for i, o in VO:
                                    blend_weights[i] = V[o:o+4]
                            case x:
                                raise Exception(f'Not supported vert decl type for blendweight: {repr(x)}')
                    case D3DDECLUSAGE.BLENDINDICES:
                        match e.d3d_decl_type:
                            case D3DDECLTYPE.UBYTE4:
                                for i, o in VO:
                                    blend_indices[i] = V[o:o+4]
                            case x:
                                raise Exception(f'Not supported vert decl type for blendindices: {repr(x)}')
                    case D3DDECLUSAGE.NORMAL:
                        match e.d3d_decl_type:
                            case D3DDECLTYPE.FLOAT3:
                                for i, o in VO:
                                    vertex_normals[i] = V[o:o+12].cast('f')
                            case x:
                                raise Exception(f'Not supported vert decl type for normal: {repr(x)}')
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
                                        raise Exception(f'Not supported vert decl type for texcoord: {repr(x)}')
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
                                        raise Exception(f'Not supported vert decl type for texcoord: {repr(x)}')
                            case x:
                                raise Exception(f'Not supported usage index for texcoord: {repr(x)}')
                    case D3DDECLUSAGE.TANGENT:
                        pass
                    case D3DDECLUSAGE.COLOR:
                        pass
                    case x:
                        raise Exception(f'Not supported vert decl usage: {repr(x)}')

    bm.verts.index_update()

    # Let's assign vertices which has blend weight to corresponding vertex groups
    for v in bm.verts:
        vd = v[deform_layer]
        ng = tmc.nodelay.chunks[vd.keys()[0]].chunks[0].node_group
        for i, w in zip(blend_indices[v.index], blend_weights[v.index]):
            if w > 0:
                vd[ng[i]] = w/0xff

    # We add UVs
    l0 = bm.loops.layers.uv.new('UVMap')
    l1 = bm.loops.layers.uv.new('UVMap.001')
    l2 = bm.loops.layers.uv.new('UVMap.002')
    l3 = bm.loops.layers.uv.new('UVMap.003')
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

    bm.to_mesh(mesh_obj.data)
    mesh_obj.data.normals_split_custom_set_from_vertices(tuple(v.normal for v in bm.verts))
    bm.free()

def set_bones_tail(b):
    if b.name.startswith('MOT') or not b.parent:
        mot = tuple( c for c in b.children if c.name.startswith('MOT') )
        if len(mot):
            b.tail = sum(( c.head for c in mot ), Vector()) / len(mot)
        elif not b.parent:
            b.tail = (0, .01, 0)
        else:
            b.tail = b.head + b.parent.matrix.to_3x3() @ Vector((0, b.parent.length, 0))
    else:
        b.tail = b.head + b.parent.matrix.to_3x3() @ Vector((0, .01, 0))

    for c in b.children:
        set_bones_tail(c)
