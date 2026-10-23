"""Blender: GLB (o FBX) con rig -> FBX listo para UE: un solo hueso raíz, una sola malla y las
texturas en ficheros PNG junto al FBX. Se ejecuta DENTRO de Blender (no en UE):

  blender -b -P blender_glb_to_fbx.py -- entrada.glb salida.fbx [hueso_a_quitar ...]

o ``python -m unity2ue glb2fbx entrada.glb salida.fbx --quitar neutral_bone``. Los huesos a quitar son
raíces sobrantes (p.ej. ``neutral_bone`` de los rigs automáticos); lo que cuelgue de ellos se borra.
"""
import os
import sys

import bpy
import mathutils

args = sys.argv[sys.argv.index("--") + 1:]
src, dst, drop = args[0], args[1], set(args[2:])
out_dir = os.path.dirname(dst)
tex_dir = os.path.join(out_dir, os.path.splitext(os.path.basename(dst))[0] + "_texturas")
os.makedirs(tex_dir, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
if src.lower().endswith(".fbx"):
    bpy.ops.import_scene.fbx(filepath=src)
else:
    bpy.ops.import_scene.gltf(filepath=src)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print("ARMATURE", arm.name, "bones", len(arm.data.bones), "meshes", len(meshes))

# 1) Un solo hueso raíz: UE no admite varios. Lo que cuelga del hueso quitado (p.ej. una malla
#    diminuta en neutral_bone) se borra también.
for m in list(meshes):
    if m.parent_type == "BONE" and m.parent_bone in drop:
        print("QUITADA", m.name, "(colgaba de", m.parent_bone, ")")
        meshes.remove(m)
        bpy.data.objects.remove(m, do_unlink=True)
if drop:
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for b in list(arm.data.edit_bones):
        if b.name in drop:
            arm.data.edit_bones.remove(b)
    bpy.ops.object.mode_set(mode="OBJECT")
    for m in meshes:
        for g in list(m.vertex_groups):
            if g.name in drop:
                m.vertex_groups.remove(g)
print("ROOTS", [b.name for b in arm.data.bones if b.parent is None])

# 2) Texturas del GLB (empaquetadas) a ficheros PNG junto al FBX.
for i, img in enumerate(bpy.data.images):
    if img.type != "IMAGE" or not img.has_data and not img.packed_file:
        continue
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (img.name or f"img{i}"))
    path = os.path.join(tex_dir, f"{name}.png")
    img.filepath_raw = path
    img.file_format = "PNG"
    try:
        img.save()
        img.unpack(method="REMOVE") if img.packed_file else None
        img.filepath = path
    except Exception as e:  # noqa: BLE001
        print("NO SE PUDO GUARDAR", img.name, e)
print("TEXTURAS", len(os.listdir(tex_dir)))

# 3) Todas las mallas en una: UE crearía una SkeletalMesh (y un esqueleto) por malla suelta.
bpy.ops.object.select_all(action="DESELECT")
for m in meshes:
    m.select_set(True)
body = max(meshes, key=lambda o: len(o.data.vertices))
bpy.context.view_layer.objects.active = body
if len(meshes) > 1:
    bpy.ops.object.join()
body.name = os.path.splitext(os.path.basename(dst))[0]
zs = [(body.matrix_world @ mathutils.Vector(c)).z for c in body.bound_box]
print("HEIGHT_M", max(zs) - min(zs), "MATERIALS", len(body.data.materials))

bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
body.select_set(True)
bpy.ops.export_scene.fbx(filepath=dst, use_selection=True, add_leaf_bones=False, bake_anim=False,
                         object_types={"ARMATURE", "MESH"}, path_mode="COPY", embed_textures=False,
                         apply_scale_options="FBX_SCALE_UNITS", axis_forward="-Z", axis_up="Y")
print("EXPORTED", dst)
