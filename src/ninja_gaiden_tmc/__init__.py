# NINJA GAIDEN Model Importer by Nozomi Miyamori is under the public domain
# and also marked with CC0 1.0. This file is a part of NINJA GAIDEN SIGMA 2 TMC Importer.

from . import tcmlib
from .ngs1.importer import import_tmc as ngs1_import_tmc
from .ngs2.importer import import_tmc as ngs2_import_tmc

import bpy

from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty
from bpy.types import Operator

import os
import mmap

class NGS1SelectG1TGImportTMC(Operator, ImportHelper):
    bl_idname = 'ninja_gaiden_tmc.ngs1_select_g1tg_import_tmc'
    bl_label = 'Select TMCL2 or G1TG'
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(
            default="*.g1t;*.gt1;*.g1tg;*.tmcl2;*.dat",
            options={'SKIP_SAVE', 'HIDDEN'},
    )
    directory: StringProperty(subtype='DIR_PATH')

    tmc_path: StringProperty(
            subtype='FILE_PATH',
            default='',
            options={'SKIP_SAVE', 'HIDDEN'}
    )

    tmcl_path: StringProperty(
            subtype='FILE_PATH',
            default='',
            options={'SKIP_SAVE', 'HIDDEN'}
    )

    def execute(self, context):
        if not self.tmc_path or not self.tmcl_path:
            return {'CANCELLED'}

        try:
            with (mmap_open(self.tmc_path) as tmc, mmap_open(self.tmcl_path) as tmcl,
                  mmap_open(self.filepath) as g1tg, tcmlib.ngs1.TMCParser(tmc, tmcl) as tmc):
                ngs1_import_tmc(context, tmc, g1tg)
        except tcmlib.ParserError as e:
            self.report({'ERROR'}, f"Failed to parse TMC: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class NGS1SelectTMCL(Operator, ImportHelper):
    bl_idname = 'ninja_gaiden_tmc.ngs1_select_tmcl'
    bl_label = 'Select TMCL'

    filter_glob: StringProperty(
            default="*.tmcl;*.dat",
            options={'SKIP_SAVE', 'HIDDEN'},
    )
    directory: StringProperty(subtype='DIR_PATH')

    tmc_path: StringProperty(
            subtype='FILE_PATH',
            default='',
            options={'SKIP_SAVE', 'HIDDEN'}
    )

    def execute(self, context):
        return bpy.ops.ninja_gaiden_tmc.ngs1_select_g1tg_import_tmc('INVOKE_DEFAULT', tmc_path=self.tmc_path, tmcl_path=self.filepath, directory=self.directory)

class NGS2SelectTMCLImportTMC(Operator, ImportHelper):
    bl_idname = 'ninja_gaiden_tmc.ngs2_select_tmcl_import_tmc'
    bl_label = 'Select TMCL'
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(
            default="*.tmcl;*.dat",
            options={'SKIP_SAVE', 'HIDDEN'},
    )
    directory: StringProperty(subtype='DIR_PATH')

    tmc_path: StringProperty(
            subtype='FILE_PATH',
            default='',
            options={'SKIP_SAVE', 'HIDDEN'}
    )

    def execute(self, context):
        if not self.tmc_path:
            return {'CANCELLED'}

        try:
            with mmap_open(self.tmc_path) as tmc, mmap_open(self.filepath) as tmcl, tcmlib.ngs2.TMCParser(tmc, tmcl) as tmc:
                ngs2_import_tmc(context, tmc)
        except tcmlib.ParserError as e:
            self.report({'ERROR'}, f"Failed to parse TMC: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class ImportTMCEntry(Operator, ImportHelper):
    '''Load a TMC file'''
    bl_idname = 'ninja_gaiden_tmc.import_tmc_entry'
    bl_label = 'Select TMC'
    old_dir = ''

    filter_glob: StringProperty(
            default="*.tmc;*.dat",
            options={'SKIP_SAVE', 'HIDDEN'},
    )
    filename: StringProperty()
    directory: StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        self.directory = ImportTMCEntry.old_dir
        return super().invoke(context, event)

    def execute(self, context):
        ImportTMCEntry.old_dir = self.directory
        try:
            with mmap_open(self.filepath) as tmc, tcmlib.ContainerParser(b'TMC', tmc) as tmc:
                min_v = tmc._minor_ver
        except tcmlib.ParserError as e:
            self.report({'ERROR'}, f"{self.filename} is not TMC")
            return {'CANCELLED'}
        if min_v == 0:
            return bpy.ops.ninja_gaiden_tmc.ngs1_select_tmcl('INVOKE_DEFAULT', tmc_path=self.filepath, directory=self.directory)
        else:
            return bpy.ops.ninja_gaiden_tmc.ngs2_select_tmcl_import_tmc('INVOKE_DEFAULT', tmc_path=self.filepath, directory=self.directory)

def mmap_open(path):
    with open(path, 'rb') as f:
        return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

def menu_func_import(self, context):
    self.layout.operator(ImportTMCEntry.bl_idname, text="Ninja Gaiden Master Collection TMC (.tmc)")

def register():
    bpy.utils.register_class(NGS1SelectG1TGImportTMC)
    bpy.utils.register_class(NGS1SelectTMCL)
    bpy.utils.register_class(NGS2SelectTMCLImportTMC)
    bpy.utils.register_class(ImportTMCEntry)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(NGS1SelectG1TGImportTMC)
    bpy.utils.unregister_class(NGS1SelectTMCL)
    bpy.utils.unregister_class(NGS2SelectTMCLImportTMC)
    bpy.utils.unregister_class(ImportTMCEntry)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
    register()
