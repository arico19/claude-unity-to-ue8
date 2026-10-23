"""Personajes alternativos: crea un Blueprint jugable por cada modelo con rig de ``personajes.json``.

Pensado para ver en acción personajes nuevos (rig Mixamo o con nombres de hueso tipo Mixamo) usando
un personaje ya convertido como plantilla: mismo comportamiento (scripts, colisión), mismas
animaciones (redirigidas al esqueleto nuevo) y el arma bien agarrada.

Configuración: ``<ProyectoUE>/Unity2UE/personajes.json``

    {
      "plantilla": "/Game/Unity/animations/BP_US_Soldier_Humanoid",
      "personajes": {
        "Ch44":  {"fichero": "C:/Users/yo/Downloads/Ch44_nonPBR.fbx", "arma": "Lanzallamas", "mas_alto_cm": 20},
        "Titan": {"fichero": "C:/.../Titan.fbx", "arma": "Lanzallamas", "mas_alto_cm": 40}
      }
    }

Por cada personaje ``<N>``:
- importa el FBX como SkeletalMesh en ``/Game/Personajes/<N>`` (una vez; borra la carpeta para
  reimportar). Un GLB con varios huesos raíz se pasa antes a FBX con Blender (ver docs).
- crea ``/Game/Personajes/<N>/BP_<N>`` duplicando la plantilla, con la malla nueva mirando hacia
  delante y los pies en el suelo; quita lo que la plantilla llevaba colgado de huesos que el
  esqueleto nuevo no tiene (ojos...), salvo el soporte del arma.
- redirige los clips de la plantilla (Idle, Walking, Shoot, Dying...) con el retarget Humanoid.
- añade el personaje a ``armas.json`` con su hueso de la mano derecha y un agarre calculado para que,
  en mitad de la animación de disparo, el arma apunte hacia delante (el paso "weapons" le pone
  después el arma ``arma``). Para retocarlo a mano: ``agarre_manual`` en su entrada de armas.json.
- ``altura`` (m, opcional): escala el personaje a esa altura; o ``mas_alto_cm``: tantos cm más alto
  (o más bajo, si es negativo) que el personaje de la plantilla.
- ``plantilla`` (opcional, por personaje): Blueprint del que se copia el comportamiento (p.ej. el del
  jefe o el del enano). Las animaciones salen siempre de la plantilla general (Humanoid). Si la
  plantilla no tiene HumanoidAnimatorLink se le añade.
- ``usar_como`` (opcional): "jugador" (personaje inicial), "enemigo" (los enanos) o "jefe": pone el
  Blueprint en esa propiedad del DataAsset del juego (se reaplica en cada importación).
"""

from __future__ import annotations

import json
import math
import os

import unreal

from . import blueprints as bps
from . import humanoid_retarget as hr
from . import weapons
from .common import ASSET_TOOLS, LOG, data_dir, ensure_dir, load, load_json, save, script_class, set_prop

STEP = "characters"
ANIM_LINK = "HumanoidAnimatorLink"
# "usar_como" -> propiedad del DataAsset del juego (HordeGameData) que se sustituye
ROLES = {"jugador": "player_man_prefab", "enemigo": "enemy_man_prefab", "jefe": "boss_prefab"}
CONFIG = "personajes.json"
FOLDER = "/Game/Personajes"
LIB = unreal.SubobjectDataBlueprintFunctionLibrary
POSE = unreal.AnimPoseExtensions
WORLD = unreal.AnimPoseSpaces.WORLD


def _import_skeletal(name: str, path: str):
    folder = f"{FOLDER}/{name}"
    existing = hr._first(folder, unreal.SkeletalMesh)
    if existing is not None:
        return existing
    if not os.path.exists(path):
        LOG.error(STEP, name, f"No existe {path}")
        return None
    ensure_dir(folder)
    task = unreal.AssetImportTask()
    for k, v in (("filename", path), ("destination_path", folder), ("automated", True),
                 ("replace_existing", True), ("save", True)):
        task.set_editor_property(k, v)
    ui = unreal.FbxImportUI()
    for k, v in (("import_mesh", True), ("import_as_skeletal", True), ("import_animations", False),
                 ("import_materials", True), ("import_textures", True), ("create_physics_asset", True),
                 ("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)):
        ui.set_editor_property(k, v)
    sk = ui.get_editor_property("skeletal_mesh_import_data")
    sk.set_editor_property("convert_scene", True)
    sk.set_editor_property("convert_scene_unit", True)
    sk.set_editor_property("import_morph_targets", False)
    task.set_editor_property("options", ui)
    ASSET_TOOLS.import_asset_tasks([task])
    mesh = hr._first(folder, unreal.SkeletalMesh)
    if mesh is None:
        LOG.error(STEP, name, f"No se pudo importar {path} como SkeletalMesh")
    else:
        LOG.ok(STEP, name, f"importado -> {mesh.get_path_name()}")
    return mesh


MASTER = "/Game/Unity/_Master/M_UnityLit"
MEL = unreal.MaterialEditingLibrary


def _fix_materials(mesh, name: str) -> None:
    """Materiales con nuestro maestro PBR (M_UnityLit) en vez del "Phong" que crea la importación de
    FBX: con él las texturas oscuras (armaduras...) salen lavadas, casi grises."""
    folder = f"{FOLDER}/{name}"
    mats = list(mesh.get_editor_property("materials"))
    changed = 0
    for sm in mats:
        src = sm.get_editor_property("material_interface")
        if not isinstance(src, unreal.MaterialInstance):
            continue
        names = [str(n) for n in MEL.get_texture_parameter_names(src)]
        if "DiffuseColorMap" not in names:
            continue  # ya es nuestro o no es el material Phong de la importación
        diffuse = MEL.get_material_instance_texture_parameter_value(src, "DiffuseColorMap")
        normal = MEL.get_material_instance_texture_parameter_value(src, "NormalMap") if "NormalMap" in names else None
        mi_name = f"MI_{name}_{sm.get_editor_property('material_slot_name')}"
        mi = load(f"{folder}/{mi_name}") or ASSET_TOOLS.create_asset(
            mi_name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        MEL.set_material_instance_parent(mi, load(MASTER))
        if diffuse is not None:
            MEL.set_material_instance_texture_parameter_value(mi, "BaseColorMap", diffuse)
        if normal is not None and "Engine" not in normal.get_path_name():
            MEL.set_material_instance_texture_parameter_value(mi, "NormalMap", normal)
        MEL.set_material_instance_vector_parameter_value(mi, "UVTiling", unreal.LinearColor(1, 1, 0, 0))
        MEL.set_material_instance_vector_parameter_value(mi, "BaseColorTint", unreal.LinearColor(1, 1, 1, 1))
        MEL.set_material_instance_scalar_parameter_value(mi, "Metallic", 0.0)
        MEL.set_material_instance_scalar_parameter_value(mi, "Smoothness", 0.35)
        MEL.update_material_instance(mi)
        save(mi)
        sm.set_editor_property("material_interface", mi)
        changed += 1
    if changed:
        mesh.set_editor_property("materials", mats)
        save(mesh)
        LOG.ok(STEP, name, f"{changed} materiales con el maestro PBR")


def _template_job(template: str) -> dict | None:
    for job in (load_json("humanoid.json", {}) or {}).get("jobs", []):
        if job.get("blueprint") == template:
            return job
    return None


def _bone(pose_names: list[str], human: dict, key: str) -> str | None:
    return hr._match(pose_names, human).get(key)


def _pose_names(skeletal):
    pose = POSE.get_reference_pose(skeletal.get_editor_property("skeleton"))
    return pose, [str(n) for n in POSE.get_bone_names(pose)]


def _placement(mesh, human: dict, ref_mesh, ref_human: dict, height: float | None, taller_cm: float | None):
    """Transform del componente para que mire a +X (como la plantilla) y pise el suelo."""
    pose, names = _pose_names(mesh)
    rpose, rnames = _pose_names(ref_mesh)

    def pos(p, n, h, key):
        b = _bone(n, h, key)
        return POSE.get_bone_pose(p, b, WORLD).translation if b else None

    lh, rh = pos(pose, names, human, "LeftHand"), pos(pose, names, human, "RightHand")
    yaw = 0.0
    if lh is not None and rh is not None:
        v = rh - lh  # de la mano izquierda a la derecha: debe apuntar a +Y (mirando a +X)
        yaw = 90.0 - math.degrees(math.atan2(v.y, v.x))
    scale = 1.0
    feet = [p for p in (pos(pose, names, human, "LeftFoot"), pos(pose, names, human, "RightFoot")) if p]
    head = pos(pose, names, human, "Head")
    if height and head is not None and feet:
        cur = head.z - min(f.z for f in feet)
        scale = (height * 100.0 * 0.9) / cur if cur > 1 else 1.0  # la cabeza está al ~90 % de la altura
    ref_feet = [p for p in (pos(rpose, rnames, ref_human, "LeftFoot"), pos(rpose, rnames, ref_human, "RightFoot")) if p]
    ref_head = pos(rpose, rnames, ref_human, "Head")
    if taller_cm is not None and head is not None and feet and ref_head is not None and ref_feet:
        # Tantos cm más alto que la plantilla (pies -> cabeza es ~90 % de la altura total).
        cur = head.z - min(f.z for f in feet)
        ref_cur = ref_head.z - min(f.z for f in ref_feet)
        scale = (ref_cur + taller_cm * 0.9) / cur if cur > 1 else 1.0
    dz = 0.0
    if feet and ref_feet:
        dz = min(f.z for f in ref_feet) - min(f.z for f in feet) * scale
    return unreal.Transform(unreal.Vector(0, 0, dz), unreal.Rotator(roll=0, pitch=0, yaw=yaw),
                            unreal.Vector(scale, scale, scale))


def _descendants(bp, handle) -> list:
    out, frontier = [], [handle]
    while frontier:
        for h in bps.children(bp, frontier.pop()):
            out.append(h)
            frontier.append(h)
    return out


def _parent_world(handles: list, handle):
    """Transform acumulado de los padres de un componente del Blueprint (sin el suyo)."""
    by_name = {bps.var_name(h): h for h in handles}
    total = unreal.Transform()
    name = bps.parent_name(handle)
    for _ in range(32):
        parent = by_name.get(name) if name else None
        if parent is None:
            break
        comp = bps._obj(parent)
        if isinstance(comp, unreal.SceneComponent) and not LIB.is_root_component(LIB.get_data(parent)):
            rel = unreal.Transform(comp.get_editor_property("relative_location"),
                                   comp.get_editor_property("relative_rotation"),
                                   comp.get_editor_property("relative_scale3d"))
            total = unreal.MathLibrary.compose_transforms(total, rel)
        name = bps.parent_name(parent)
    return total


def _make_blueprint(name: str, template: str, mesh, placement, keep: set[str]):
    path = f"{FOLDER}/{name}/BP_{name}"
    bp = load(path)
    if bp is None:
        bp = unreal.EditorAssetLibrary.duplicate_asset(template, path)
    if bp is None:
        LOG.error(STEP, name, f"No se pudo duplicar {template}")
        return None
    # Quitar lo que la plantilla colgaba de sus huesos (ojos...) salvo el soporte del arma.
    tpl = next((p for p in (load_json("blueprints.json", {}) or {}).get("prefabs", [])
                if p.get("ue_blueprint_path") == template), None)
    attached = {bps.component_name(n["name"]) for n, _ in weapons._walk(tpl["root"])
                if n.get("attach_bone")} - keep if tpl else set()
    root = bps._scene_root_handle(bp)
    for comp_name in attached:
        h = bps._handle_named(bp, comp_name)
        if h is not None:
            doomed = [*reversed(_descendants(bp, h)), h]
            bps._sds().delete_subobjects(root, doomed, bp)
    # Sin HumanoidAnimatorLink (p.ej. plantilla de stickman para enemigos o jefe) se añade: es quien
    # reproduce los clips redirigidos (el juego lo usa cuando los del stickman no valen).
    link_cls = script_class(ANIM_LINK)
    has_link = any(bps._obj(h) is not None and bps._obj(h).get_class().get_name() == ANIM_LINK
                   for h in bps._sds().k2_gather_subobject_data_for_blueprint(bp))
    if not has_link and link_cls is not None:
        bps._add(bp, root, link_cls, ANIM_LINK)
    handles = list(bps._sds().k2_gather_subobject_data_for_blueprint(bp))
    for h in handles:
        comp = bps._obj(h)
        if isinstance(comp, unreal.SkeletalMeshComponent):
            comp.set_editor_property("skeletal_mesh", mesh)
            comp.set_editor_property("override_materials", [])
            # La malla puede colgar de nodos con su propio transform (p.ej. el stickman enano, con
            # escala 0,15): se compensa para que quede con ``placement`` respecto al actor.
            local = unreal.MathLibrary.make_relative_transform(placement, _parent_world(handles, h))
            set_prop(comp, "relative_location", local.translation)
            set_prop(comp, "relative_rotation", local.rotation.rotator())
            set_prop(comp, "relative_scale3d", local.scale3d)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    save(bp)
    return bp


def _hand_world(seq_or_mesh, bone: str, actor_from_mesh):
    """Transform de un hueso en el espacio del actor: en el fotograma 0 del clip, o en reposo."""
    if isinstance(seq_or_mesh, unreal.AnimSequence):
        pose = seq_or_mesh.get_anim_pose_at_frame(0, unreal.AnimPoseEvaluationOptions())
    else:
        pose, _ = _pose_names(seq_or_mesh)
    return unreal.MathLibrary.compose_transforms(POSE.get_bone_pose(pose, bone, WORLD), actor_from_mesh)


def aim_grip(mesh, hand: str, placement, anims_folder: str) -> dict | None:
    """Agarre "apuntando": en mitad del clip de disparo, el soporte del arma queda en la mano derecha
    con +X hacia delante (hacia los enemigos) y +Z arriba. Las armas se orientan con el cañón en +X
    del soporte (ver weapons.py), así que disparan hacia donde mira el personaje."""
    clip = next((load(p) for p in unreal.EditorAssetLibrary.list_assets(anims_folder, recursive=True)
                 if "shoot" in p.lower() or "fire" in p.lower()), None)
    if clip is None:
        return None
    frame = unreal.AnimationLibrary.get_num_frames(clip) // 2
    pose = clip.get_anim_pose_at_frame(frame, unreal.AnimPoseEvaluationOptions())
    hand_actor = unreal.MathLibrary.compose_transforms(POSE.get_bone_pose(pose, hand, WORLD), placement)
    target = unreal.Transform(hand_actor.translation, unreal.Rotator(0, 0, 0), unreal.Vector(1, 1, 1))
    return weapons._t_to_json(unreal.MathLibrary.make_relative_transform(target, hand_actor))


def _aim_template_entries(template_mesh, anims_folder: str) -> None:
    """Agarre apuntando también para los personajes de la plantilla (armas externas: lanzallamas...)."""
    wcfg = weapons.load_config() or {}
    for who in wcfg.get("personajes", {}).values():
        if who.get("malla_personaje") != template_mesh.get_path_name().split(".")[0]:
            continue
        grip = aim_grip(template_mesh, who["hueso"], unreal.Transform(), anims_folder)
        if grip:
            who["agarre_disparo"] = grip
    weapons.save_config(wcfg)


def run() -> None:
    cfg = load_json(CONFIG)
    if not cfg:
        return
    template = cfg.get("plantilla")
    job = _template_job(template)
    if job is None or not job.get("states"):
        LOG.error(STEP, CONFIG, f"La plantilla {template} no tiene animaciones Humanoid (humanoid.json)")
        return
    human = job["states"][0]["source_human"]  # nombres de hueso Mixamo (con o sin "mixamorig:")
    ref_mesh = hr._first(job["target_folder"], unreal.SkeletalMesh)
    wcfg = weapons.load_config() or {}
    if ref_mesh is not None:
        _aim_template_entries(ref_mesh, f"{job['target_folder']}/Anims")
    for name, spec in cfg.get("personajes", {}).items():
        try:
            bp_template = spec.get("plantilla") or template
            holder = (wcfg.get("personajes", {}).get(bp_template) or {}).get("componente")
            mesh = _import_skeletal(name, spec["fichero"])
            if mesh is None:
                continue
            _fix_materials(mesh, name)
            placement = _placement(mesh, human, ref_mesh, job["target_human"], spec.get("altura"),
                                   spec.get("mas_alto_cm"))
            bp = _make_blueprint(name, bp_template, mesh, placement, {holder} if holder else set())
            if bp is None:
                continue
            bp_path = bp.get_path_name().split(".")[0]
            hr.run({"jobs": [dict(job, prefab=f"personaje {name}", blueprint=bp_path,
                                  target_folder=f"{FOLDER}/{name}", target_human=human)]})
            hand = _bone(_pose_names(mesh)[1], human, "RightHand")
            grip = aim_grip(mesh, hand, placement, f"{FOLDER}/{name}/Anims") if hand else None
            if grip and holder:
                wcfg = weapons.load_config() or {}
                entry = wcfg.setdefault("personajes", {}).setdefault(bp_path, {})
                entry.update({"componente": holder, "malla_personaje": mesh.get_path_name().split(".")[0],
                              "hueso": hand, "agarre": entry.get("agarre_manual") or grip})
                if spec.get("arma"):
                    entry["arma"] = spec["arma"]
                weapons.save_config(wcfg)
            role = spec.get("usar_como")
            if role:
                _assign_role(role, bp, name)
            LOG.ok(STEP, name, f"-> {bp_path} (giro {placement.rotation.rotator().yaw:.0f}°, "
                               f"escala {placement.scale3d.x:.2f}{', ' + role if role else ''})")
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, name)


def _assign_role(role: str, bp, name: str) -> None:
    """Pone el Blueprint como jugador inicial, enemigo o jefe en el DataAsset del juego."""
    prop = ROLES.get(role)
    if prop is None:
        LOG.warn(STEP, name, f"usar_como '{role}' no válido (usa: {', '.join(ROLES)})")
        return
    for entry in (load_json("data_assets.json", {}) or {}).get("data_assets", []):
        if prop not in entry.get("properties", {}):
            continue
        da = load(entry["ue_path"])
        if da is None:
            continue
        try:
            da.set_editor_property(prop, bp.generated_class())
            save(da)
            LOG.ok(STEP, name, f"{da.get_name()}.{prop} = {bp.get_name()}")
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, f"{name}: {da.get_name()}.{prop}")


def config_path() -> str:
    return os.path.join(data_dir(), CONFIG)


def add_character(name: str, path: str, weapon: str | None = None, height: float | None = None) -> None:
    """Añade (o actualiza) un personaje en personajes.json."""
    cfg = load_json(CONFIG) or {"plantilla": None, "personajes": {}}
    entry = cfg.setdefault("personajes", {}).setdefault(name, {})
    entry["fichero"] = path
    if weapon:
        entry["arma"] = weapon
    if height:
        entry["altura"] = height
    with open(config_path(), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
