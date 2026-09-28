"""Script de Blender (se ejecuta con ``blender -b -P blender_fix_root.py -- entrada.fbx salida.fbx``).

UE no importa como SkeletalMesh un FBX cuyo esqueleto tiene varios huesos raíz (típico de Blender:
Left_Hip, Right_Hip, Spine... colgando directamente del objeto Armature). Este script añade un
hueso ``root`` en el origen, cuelga de él las raíces y vuelve a exportar el FBX.
"""

import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
src, dst = args[0], args[1]
# Eje a lo largo del que apuntan los huesos en el FBX original: importar y exportar con el mismo eje
# conserva los ejes locales de cada hueso (si no, Blender los recalcula y las animaciones de Unity,
# que son rotaciones locales, dejan de encajar).
primary = args[2] if len(args) > 2 else "Y"
secondary = args[3] if len(args) > 3 else "X"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src, primary_bone_axis=primary, secondary_bone_axis=secondary)

fixed = 0
for arm in [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]:
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    bones = arm.data.edit_bones
    roots = [b for b in bones if b.parent is None]
    if len(roots) > 1:
        root = bones.new("root")
        root.head = (0.0, 0.0, 0.0)
        root.tail = (0.0, 0.0, max(0.01, max(b.length for b in roots) * 0.25))
        for b in roots:
            b.parent = root
        fixed += 1
    bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.export_scene.fbx(filepath=dst, add_leaf_bones=False, bake_anim=False, use_armature_deform_only=False,
                         primary_bone_axis=primary, secondary_bone_axis=secondary)
print(f"[unity2ue][blender] {fixed} esqueletos con un solo hueso raíz -> {dst}")
