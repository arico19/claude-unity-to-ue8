"""Armas en la mano de los personajes, intercambiables con un fichero de configuración.

Cada personaje con un arma colgada de un hueso (en Unity: el arma hija del hueso de la mano) lleva
el arma en un soporte anclado a ese hueso con el transform ``agarre``: sigue la animación de la mano
y es el mismo para cualquier arma. Cada arma sólo define su ajuste respecto al agarre y dónde
tiene la boca del cañón (el componente ``muzzle`` del que salen los disparos).

Configuración: ``<ProyectoUE>/Unity2UE/armas.json`` (se crea la primera vez a partir de los
prefabs convertidos, con el arma original de Unity):

    {
      "arma": "TommyGun",                      <- la que llevan los personajes
      "armas": {
        "TommyGun": {"malla": "/Game/Unity/.../TommyGun", "posicion": [0, 0, 0],
                     "rotacion": [0, 0, 0], "escala": [1, 1, 1], "boca": [45.7, -0.8, 5.9]},
        "Rifle":    {"fichero": "D:/modelos/rifle.fbx", "rotacion": [0, 90, 0], "escala": 0.8}
      },
      "personajes": {
        "/Game/Unity/animations/BP_US_Soldier_Humanoid": {
          "componente": "TommyGun", "malla_personaje": "/Game/.../US_Soldier", "hueso": "Soldier-R-Hand",
          "agarre": {"posicion": [...], "rotacion": [...], "escala": [...]}}
      }
    }

- ``alternativas`` (lista, al nivel de ``arma``): armas que cada personaje lleva ya puestas pero
  ocultas (``Arma_<nombre>`` y su boca ``Boca_<nombre>``) para que el juego las cambie en partida;
  (por ejemplo, un lanzallamas que el jugador obtiene al recoger una recompensa).
- ``integrada``: el arma forma parte de la malla del personaje (ranura de material con ese nombre),
  como el TommyGun del soldado: al poner otra arma esa ranura se oculta y se restaura al volver.
- ``fichero``: FBX/GLB/OBJ que se importa como StaticMesh en ``/Game/Armas/<nombre>`` (una vez).
- ``posicion`` (cm), ``rotacion`` ([pitch, yaw, roll] en grados) y ``escala`` (número o [x, y, z]):
  ajuste del arma respecto al agarre. Todos opcionales.
- ``boca``: punto de la malla del arma (sus coordenadas locales, cm) del que salen los disparos. Si
  falta, se estima: el extremo más largo de la malla en su eje +.
- ``agarre``: transform del soporte respecto al hueso de la mano; se calcula de Unity y se puede
  retocar aquí (vale para todas las armas de ese personaje). ``agarre_disparo``: el de las armas
  externas, calculado para que apunten hacia delante al disparar (characters.aim_grip).

Uso: ``python -m unity2ue arma <ProyectoUE> <nombre> [--fichero ruta]`` (editor cerrado), o en la
consola Python del editor: ``import unity2ue_import.weapons as w; w.run("Rifle")``. También se
reaplica al final de cada importación, así que el arma elegida sobrevive a las reconversiones.
"""

from __future__ import annotations

import json
import os

import unreal

from . import blueprints as bps
from .common import ASSET_TOOLS, LOG, data_dir, ensure_dir, load, load_json, resolve_mesh, rot, save, set_prop, vec

STEP = "weapons"
CONFIG = "armas.json"
MUZZLE = "muzzle"
MUZZLE_NAMES = {"muzzle", "shot_point", "shoot_point"}
ALT_PREFIX, MUZZLE_PREFIX = "Arma_", "Boca_"  # armas alternativas ocultas (cambio en partida)
IMPORT_FOLDER = "/Game/Armas"
LIB = unreal.SubobjectDataBlueprintFunctionLibrary


# --------------------------------------------------------------------------- configuración
def _config_path() -> str:
    return os.path.join(data_dir(), CONFIG)


def _t_to_json(t) -> dict:
    r = t.rotation.rotator()
    return {"posicion": [round(v, 4) for v in (t.translation.x, t.translation.y, t.translation.z)],
            "rotacion": [round(v, 4) for v in (r.pitch, r.yaw, r.roll)],
            "escala": [round(v, 5) for v in (t.scale3d.x, t.scale3d.y, t.scale3d.z)]}


def _t_from_json(d: dict | None):
    d = d or {}
    s = d.get("escala", 1.0)
    scale = [float(s)] * 3 if isinstance(s, (int, float)) else s
    return unreal.Transform(vec(d.get("posicion", [0, 0, 0])), rot(d.get("rotacion", [0, 0, 0])), vec(scale))


def _walk(node: dict, parent: dict | None = None):
    yield node, parent
    for ch in node.get("children", []):
        yield from _walk(ch, node)


def discover() -> dict:
    """Configuración inicial: las armas que los prefabs de Unity llevan colgadas de un hueso."""
    cfg: dict = {"arma": None, "armas": {}, "personajes": {}}
    for prefab in (load_json("blueprints.json", {}) or {}).get("prefabs", []):
        if prefab.get("variant_of") or not prefab.get("root"):
            continue
        for node, _parent in _walk(prefab["root"]):
            mesh_c = next((c for c in node.get("components", []) if c.get("type") == "StaticMesh"), None)
            if not node.get("attach_bone") or mesh_c is None:
                continue
            weapon, character = resolve_mesh(mesh_c.get("mesh")), resolve_mesh(node.get("attach_mesh"), skeletal=True)
            if character is None:
                continue
            where = f"{prefab['unity_path']}/{node['name']}"
            bone, grip = bps.bone_grip(node, character, where)
            if bone is None:
                continue
            name = node["name"]
            if weapon is not None:
                entry = {"malla": weapon.get_path_name().split(".")[0]}
            elif name in _slot_names(character):
                # Parte rígida del FBX del personaje: UE la funde en su SkeletalMesh (con un hueso propio
                # que sigue a la mano). Es un arma "integrada": su ranura se oculta al poner otra.
                entry = {"integrada": name}
            else:
                continue
            entry = cfg["armas"].setdefault(name, entry)
            muzzle = next((c for c in node.get("children", []) if bps.component_name(c["name"]).lower()
                           in MUZZLE_NAMES), None)
            if muzzle is not None and "boca" not in entry:  # la de Unity (espacio del agarre = de la malla)
                entry["boca"] = [round(v, 3) for v in muzzle["transform"]["location"]]
            cfg["arma"] = cfg["arma"] or name
            cfg["personajes"][prefab["ue_blueprint_path"]] = {
                "componente": bps.component_name(name), "malla_personaje": character.get_path_name().split(".")[0],
                "hueso": bone, "agarre": _t_to_json(grip)}
    return cfg


def load_config() -> dict | None:
    path = _config_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    cfg = discover()
    if not cfg["personajes"]:
        return None
    save_config(cfg)
    LOG.ok(STEP, CONFIG, f"creado con {len(cfg['personajes'])} personajes armados")
    return cfg


def save_config(cfg: dict) -> None:
    with open(_config_path(), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- assets
def _import_weapon(name: str, path: str):
    """Importa un FBX/GLB/OBJ como StaticMesh (una sola malla) en /Game/Armas/<nombre>."""
    folder = f"{IMPORT_FOLDER}/{name}"
    ensure_dir(folder)
    task = unreal.AssetImportTask()
    for k, v in (("filename", path), ("destination_path", folder), ("automated", True),
                 ("replace_existing", True), ("save", True)):
        task.set_editor_property(k, v)
    if path.lower().endswith(".fbx"):
        ui = unreal.FbxImportUI()
        ui.set_editor_property("import_mesh", True)
        ui.set_editor_property("import_as_skeletal", False)
        ui.set_editor_property("import_animations", False)
        ui.set_editor_property("import_materials", True)
        ui.set_editor_property("import_textures", True)
        ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
        sm = ui.get_editor_property("static_mesh_import_data")
        sm.set_editor_property("combine_meshes", True)
        sm.set_editor_property("convert_scene", True)
        sm.set_editor_property("force_front_x_axis", False)
        sm.set_editor_property("convert_scene_unit", True)
        task.set_editor_property("options", ui)
    ASSET_TOOLS.import_asset_tasks([task])
    meshes = [a for a in (load(p) for p in unreal.EditorAssetLibrary.list_assets(folder, recursive=True,
                                                                                 include_folder=False))
              if isinstance(a, unreal.StaticMesh)]
    if not meshes:
        LOG.error(STEP, name, f"No se obtuvo ninguna malla estática de {path}")
        return None
    mesh = max(meshes, key=lambda m: m.get_bounding_box().max.distance(m.get_bounding_box().min))
    LOG.ok(STEP, name, f"importada -> {mesh.get_path_name()}")
    return mesh


def _weapon_mesh(name: str, spec: dict, cfg: dict):
    mesh = load(spec.get("malla"))
    if mesh is None and spec.get("fichero"):
        mesh = _import_weapon(name, spec["fichero"])
        if mesh is not None:
            spec["malla"] = mesh.get_path_name().split(".")[0]
            save_config(cfg)
    return mesh


def _muzzle_in_mesh(mesh, spec: dict):
    if spec.get("boca"):
        return vec(spec["boca"])
    box = mesh.get_bounding_box()
    lo, hi = [box.min.x, box.min.y, box.min.z], [box.max.x, box.max.y, box.max.z]
    axis = max(range(3), key=lambda i: hi[i] - lo[i])
    p = [(lo[i] + hi[i]) / 2 for i in range(3)]
    p[axis] = hi[axis]
    return vec(p)


# --------------------------------------------------------------------------- Blueprints
def _children(bp, parent_handle):
    return bps.children(bp, parent_handle)


def _slot_names(skeletal) -> list[str]:
    return [str(m.get_editor_property("material_slot_name")) for m in skeletal.get_editor_property("materials")]


INVISIBLE = f"{IMPORT_FOLDER}/M_Invisible"


def _invisible_material():
    """Material que no se ve (Masked con opacidad 0): oculta la ranura del arma integrada."""
    mat = load(INVISIBLE)
    if mat is not None:
        return mat
    ensure_dir(IMPORT_FOLDER)
    mat = ASSET_TOOLS.create_asset("M_Invisible", IMPORT_FOLDER, unreal.Material, unreal.MaterialFactoryNew())
    mel = unreal.MaterialEditingLibrary
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    mat.set_editor_property("used_with_skeletal_mesh", True)
    zero = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -200, 0)
    zero.set_editor_property("r", 0.0)
    mel.connect_material_property(zero, "", unreal.MaterialProperty.MP_OPACITY_MASK)
    mel.recompile_material(mat)
    save(mat)
    return mat


def _show_builtin(bp, character, cfg: dict, keep: str | None) -> None:
    """Oculta las armas integradas en la malla del personaje salvo ``keep`` (que se restaura)."""
    slots = _slot_names(character)
    builtin = {n: s["integrada"] for n, s in cfg.get("armas", {}).items() if s.get("integrada") in slots}
    if not builtin:
        return
    originals = cfg.setdefault("materiales_originales", {}).setdefault(bp.get_path_name().split(".")[0], {})
    for h in bps._sds().k2_gather_subobject_data_for_blueprint(bp):
        comp = bps._obj(h)
        if not isinstance(comp, unreal.SkeletalMeshComponent) or comp.get_editor_property("skeletal_mesh") != character:
            continue
        mats = list(comp.get_editor_property("override_materials") or [])
        mats += [None] * (len(slots) - len(mats))
        for name, slot in builtin.items():
            i = slots.index(slot)
            current = mats[i]
            if current is not None and current.get_path_name().split(".")[0] != INVISIBLE:
                originals[slot] = current.get_path_name().split(".")[0]  # el de la importación
            mats[i] = load(originals.get(slot)) if name == keep else _invisible_material()
        comp.set_editor_property("override_materials", mats)


def equip(bp_path: str, who: dict, weapon_name: str, spec: dict, mesh, cfg: dict) -> bool:
    bp = load(bp_path)
    character = load(who.get("malla_personaje"))
    if bp is None or character is None:
        LOG.warn(STEP, bp_path, "Blueprint o malla del personaje no encontrados")
        return False
    holder = bps._handle_named(bp, who["componente"])
    if holder is None:
        LOG.warn(STEP, bp_path, f"Sin componente {who['componente']} donde poner el arma")
        return False
    # El soporte del arma es el agarre: anclado al hueso de la mano con el transform "agarre".
    # (Un socket de la malla sería más cómodo de editar, pero la API Python no deja crearlo.)
    # Armas externas: agarre "apuntando" (characters.aim_grip) si existe; el arma integrada en la
    # malla (TommyGun) mantiene el agarre de Unity, que es donde está su boca.
    external = mesh is not None
    grip = _t_from_json(who.get("agarre_disparo") if external and who.get("agarre_disparo") else who.get("agarre"))
    holder_comp = bps._obj(holder)
    set_prop(holder_comp, "relative_location", grip.translation)
    set_prop(holder_comp, "relative_rotation", grip.rotation.rotator())
    set_prop(holder_comp, "relative_scale3d", grip.scale3d)
    unreal.UnityCompatLibrary.set_component_attach_socket(bp, who["componente"], who["hueso"])

    kids = list(_children(bp, holder))
    mesh_h = next((h for h in kids if isinstance(bps._obj(h), unreal.StaticMeshComponent)
                   and not _var(h).startswith(ALT_PREFIX)), None)
    if mesh_h is None:
        mesh_h = bps._add(bp, holder, unreal.StaticMeshComponent, "Weapon")
    offset = _t_from_json(spec)
    mesh_comp = bps._obj(mesh_h)
    if mesh is None:  # arma integrada en la malla del personaje
        set_prop(mesh_comp, "visible", False)
    else:
        if mesh_comp.get_editor_property("static_mesh") != mesh:
            mesh_comp.set_editor_property("static_mesh", mesh)
            mesh_comp.set_editor_property("override_materials", [])  # los de la nueva arma
        set_prop(mesh_comp, "visible", True)
        set_prop(mesh_comp, "relative_location", offset.translation)
        set_prop(mesh_comp, "relative_rotation", offset.rotation.rotator())
        set_prop(mesh_comp, "relative_scale3d", offset.scale3d)
        set_prop(mesh_comp, "collision_enabled", unreal.CollisionEnabled.NO_COLLISION)
    _show_builtin(bp, character, cfg, weapon_name if mesh is None else None)

    if mesh is not None or spec.get("boca"):
        muzzle_h = next((h for h in kids if str(LIB.get_variable_name(LIB.get_data(h))).lower() in MUZZLE_NAMES),
                        None) or bps._add(bp, holder, unreal.SceneComponent, MUZZLE)
        local = _muzzle_in_mesh(mesh, spec) if mesh is not None else vec(spec["boca"])
        set_prop(bps._obj(muzzle_h), "relative_location", unreal.MathLibrary.transform_location(offset, local))

    alts = [a for a in cfg.get("alternativas", []) if a != weapon_name]
    for alt in alts:
        _prepare_alternative(bp, holder, kids, alt, cfg, who, grip)

    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    save(bp)
    extra = f"; alternativas ocultas: {', '.join(alts)}" if alts else ""
    LOG.ok(STEP, bp_path, f"arma {weapon_name} en la mano ({who['hueso']}){extra}")
    return True


def _var(handle) -> str:
    return str(LIB.get_variable_name(LIB.get_data(handle)))


def _prepare_alternative(bp, holder, kids, name: str, cfg: dict, who: dict, holder_grip) -> None:
    """Arma alternativa oculta junto a la actual (``Arma_<nombre>``) con su boca (``Boca_<nombre>``):
    el juego la muestra en partida para cambiar de arma sin cargar nada (p.ej. PlayerShooter)."""
    spec = cfg.get("armas", {}).get(name)
    mesh = _weapon_mesh(name, spec, cfg) if spec and not spec.get("integrada") else None
    if mesh is None:
        LOG.warn(STEP, name, "Alternativa sin malla propia (ni 'malla' ni 'fichero'): se omite")
        return
    comp_name = ALT_PREFIX + bps.component_name(name)
    muzzle_name = MUZZLE_PREFIX + bps.component_name(name)
    by_name = {_var(h): h for h in kids}
    h = by_name.get(comp_name) or bps._add(bp, holder, unreal.StaticMeshComponent, comp_name)
    offset = _t_from_json(spec)
    if who.get("agarre_disparo"):
        # El soporte usa el agarre del arma actual (p.ej. el de Unity del TommyGun integrado); la
        # alternativa se corrige para quedar con el agarre "apuntando".
        aim = unreal.MathLibrary.make_relative_transform(_t_from_json(who["agarre_disparo"]), holder_grip)
        offset = unreal.MathLibrary.compose_transforms(offset, aim)
    comp = bps._obj(h)
    comp.set_editor_property("static_mesh", mesh)
    set_prop(comp, "visible", False)
    set_prop(comp, "relative_location", offset.translation)
    set_prop(comp, "relative_rotation", offset.rotation.rotator())
    set_prop(comp, "relative_scale3d", offset.scale3d)
    set_prop(comp, "collision_enabled", unreal.CollisionEnabled.NO_COLLISION)
    m = by_name.get(muzzle_name) or bps._add(bp, holder, unreal.SceneComponent, muzzle_name)
    set_prop(bps._obj(m), "relative_location",
             unreal.MathLibrary.transform_location(offset, _muzzle_in_mesh(mesh, spec)))


def run(weapon: str | None = None, spec: dict | None = None) -> bool:
    """Pone a los personajes el arma ``weapon`` (o la de armas.json). ``spec`` añade o actualiza
    los datos de esa arma (fichero, malla, posicion, rotacion, escala, boca)."""
    cfg = load_config()
    if cfg is None:
        LOG.add(STEP, CONFIG, "info", "Ningún personaje lleva un arma colgada de un hueso")
        return False
    if weapon:
        spec = dict(spec or {})
        if spec.pop("alternativa", False):  # se prepara oculta; el arma actual no cambia
            if weapon not in cfg.setdefault("alternativas", []):
                cfg["alternativas"].append(weapon)
        else:
            cfg["arma"] = weapon
        if spec:
            entry = cfg.setdefault("armas", {}).setdefault(weapon, {})
            if spec.get("fichero") and spec["fichero"] != entry.get("fichero"):
                entry.pop("malla", None)  # fichero nuevo: se vuelve a importar
            entry.update(spec)
        save_config(cfg)
    ok = True
    for bp_path, who in cfg.get("personajes", {}).items():
        # Cada personaje puede llevar su propia arma ("arma" en su entrada); si no, la general.
        name = who.get("arma") or cfg.get("arma")
        spec = cfg.get("armas", {}).get(name)
        if spec is None:
            LOG.error(STEP, bp_path, f"El arma '{name}' no está en {CONFIG} (hay: {', '.join(cfg.get('armas', {}))})")
            ok = False
            continue
        mesh = None if spec.get("integrada") else _weapon_mesh(name, spec, cfg)
        if mesh is None and not spec.get("integrada"):
            LOG.error(STEP, name, "Sin malla: indica 'malla' (/Game/...) o 'fichero' (FBX/GLB/OBJ)")
            ok = False
            continue
        try:
            ok = equip(bp_path, who, name, spec, mesh, cfg) and ok
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, bp_path)
            ok = False
    save_config(cfg)  # guarda los materiales originales de las armas integradas
    return ok
