# NINJA GAIDEN SIGMA 2 TMC Importer by Nozomi Miyamori is under the public domain
# and also marked with CC0 1.0. This file is a part of NINJA GAIDEN SIGMA 2 TMC Importer.

from .tmc11 import ImportTMC11
import bpy

def menu_func_import(self, context):
    self.layout.operator(ImportTMC11.bl_idname, text="Ninja Gaiden Sigam 2 TMC (.tmc/.tmcl)")

def register():
    bpy.utils.register_class(ImportTMC11)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(ImportTMC11)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
    register()
