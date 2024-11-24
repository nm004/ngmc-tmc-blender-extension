# NINJA GAIDEN SIGMA 2 TMC Importer by Nozomi Miyamori is under the public domain
# and also marked with CC0 1.0. This file is a part of NINJA GAIDEN SIGMA 2 TMC Importer.

from .importer import import_ngs2_tmc

from . import tcmlib

import bpy

from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty
from bpy.types import Operator

import os
import mmap

def import_tmc_wrapper(context, tmc_path, tmcl_path):
    tmc_m, tmcl_m = mmap_open(tmc_path), mmap_open(tmcl_path)
    with tmc_m, tmcl_m:
        with tcmlib.ngs2.TMCParser(tmc_m, tmcl_m) as tmc:
            import_ngs2_tmc(context, tmc)

class SelectTMCLImportTMC(Operator, ImportHelper):
    bl_idname = 'ninja_gaiden_tmc.select_tmcl_import_tmc'
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
            import_tmc_wrapper(context, self.tmc_path, self.filepath)
        except tcmlib.ParserError as e:
            self.report({'ERROR'}, "Failed to parse TMC: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class ImportTMCEntry(Operator, ImportHelper):
    '''Load a TMC file (NGS2)'''
    bl_idname = 'ninja_gaiden_tmc.import_tmc_entry'
    bl_label = 'Select TMC'
    old_dir = ''

    filter_glob: StringProperty(
            default="*.tmc;*.dat",
            options={'SKIP_SAVE', 'HIDDEN'},
    )
    directory: StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        self.directory = ImportTMCEntry.old_dir
        return super().invoke(context, event)

    def execute(self, context):
        ImportTMCEntry.old_dir = self.directory
        return bpy.ops.ninja_gaiden_tmc.select_tmcl_import_tmc('INVOKE_DEFAULT', tmc_path=self.filepath, directory=self.directory)

def mmap_open(path):
    with open(path, 'rb') as f:
        return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

def menu_func_import(self, context):
    self.layout.operator(ImportTMCEntry.bl_idname, text="Ninja Gaiden Sigam 2 TMC (.tmc/.tmcl)")

def register():
    bpy.utils.register_class(SelectTMCLImportTMC)
    bpy.utils.register_class(ImportTMCEntry)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(SelectTMCLImportTMC)
    bpy.utils.unregister_class(ImportTMCEntry)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
    register()
