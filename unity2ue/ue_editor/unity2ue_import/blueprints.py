"""Crea un Blueprint de actor por cada prefab de Unity (``blueprints.json``).

Estructura generada para un prefab:
    DefaultSceneRoot (GameObject raíz)
      ├─ componentes del GameObject raíz (malla, colisión, luz, scripts...)
      └─ <Hijo> (SceneComponent con transform local)
            └─ componentes del hijo ...
Si el GameObject raíz tiene Rigidbody, su colisión (o malla) pasa a ser la raíz del
actor con Simulate Physics, que es como UE espera los cuerpos físicos.
"""

from __future__ import annotations

import unreal

from . import components as comps
from .common import ASSET_TOOLS, LOG, ensure_dir, load, resolve_class, rot_from_quat, save, set_prop, vec

STEP = "blueprints"
SDS = None
LIB = unreal.SubobjectDataBlueprintFunctionLibrary

PHYSICS_ROOT_PRIORITY = ("BoxCollision", "SphereCollision", "CapsuleCollision", "StaticMesh", "SkeletalMesh")


def _sds():
    global SDS
    if SDS is None:
        SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    return SDS


def _obj(handle):
    return LIB.get_object(LIB.get_data(handle))


def _add(bp, parent_handle, cls, name: str):
    params = unreal.AddNewSubobjectParams(parent_handle=parent_handle, new_class=cls, blueprint_context=bp)
    handle, fail = _sds().add_new_subobject(params)
    if not LIB.is_handle_valid(handle):
        raise RuntimeError(f"No se pudo añadir {cls}: {fail}")
    try:
        _sds().rename_subobject(handle, unreal.Text(name))
    except Exception:  # noqa: BLE001
        pass
    return handle


def _unique(name: str, used: set[str]) -> str:
    base = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name) or "Component"
    out, i = base, 1
    while out in used:
        i += 1
        out = f"{base}_{i}"
    used.add(out)
    return out


def _apply_rigidbody(comp, rb: dict, item: str) -> None:
    set_prop(comp, "simulate_physics", not rb.get("kinematic", False), STEP, item)
    set_prop(comp, "enable_gravity", bool(rb.get("enable_gravity", True)))
    set_prop(comp, "linear_damping", float(rb.get("linear_damping", 0.0)))
    set_prop(comp, "angular_damping", float(rb.get("angular_damping", 0.0)))
    try:
        body = comp.get_editor_property("body_instance")
        set_prop(body, "override_mass", True)
        set_prop(body, "mass_in_kg_override", float(rb.get("mass_kg", 1.0)))
        set_prop(body, "use_ccd", bool(rb.get("ccd", False)))
        lp, lr = rb.get("lock_position", {}), rb.get("lock_rotation", {})
        set_prop(body, "lock_x_translation", bool(lp.get("x")))
        set_prop(body, "lock_y_translation", bool(lp.get("y")))
        set_prop(body, "lock_z_translation", bool(lp.get("z")))
        set_prop(body, "lock_x_rotation", bool(lr.get("x")))
        set_prop(body, "lock_y_rotation", bool(lr.get("y")))
        set_prop(body, "lock_z_rotation", bool(lr.get("z")))
        comp.set_editor_property("body_instance", body)
    except Exception:  # noqa: BLE001
        LOG.warn(STEP, item, "No se pudo configurar body_instance (masa/bloqueos)")
    try:
        comp.set_collision_profile_name("PhysicsActor")
    except Exception:  # noqa: BLE001
        pass


def _add_components(bp, parent_handle, node: dict, used: set[str], item: str, skip_ids: set[int]) -> None:
    for c in node.get("components", []):
        if id(c) in skip_ids:
            continue
        t = c.get("type")
        if t in ("Rigidbody", "MeshCollision", "AudioListener", "Animator", "LODGroup",
                                  "UnresolvedScript", "PackageScript", "Unsupported", "UICanvas", "NavAgent",
                                  "NavObstacle", "Terrain", "LegacyAnimation"):
            if t == "UnresolvedScript":
                LOG.warn(STEP, item, f"Script no resuelto: {c.get('unity_path') or c.get('guid')}")
            continue
        cls = comps.component_class(c)
        if cls is None:
            if t == "Script":
                LOG.warn(STEP, item, f"Clase C++ {c.get('cpp_class')} no encontrada (¿módulo compilado?)")
            continue
        try:
            h = _add(bp, parent_handle, cls, _unique(c.get("cpp_class") or t, used))
            comps.configure(_obj(h), c, node, item)
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, f"{item}:{t}")
    # MeshCollider -> colisión compleja de la malla estática
    if any(c.get("type") == "MeshCollision" for c in node.get("components", [])):
        LOG.warn(STEP, item, "MeshCollider: activa 'Use Complex Collision As Simple' en la malla si es estática")


def _build_children(bp, parent_handle, node: dict, used: set[str], item: str) -> None:
    for child in node.get("children", []):
        name = _unique(child.get("name", "Child"), used)
        try:
            if child.get("prefab"):
                h = _add(bp, parent_handle, unreal.ChildActorComponent, name)
                comp = _obj(h)
                cls = resolve_class(child["prefab"].get("ue_class_path"))
                if cls is not None:
                    set_prop(comp, "child_actor_class", cls, STEP, item)
                else:
                    LOG.warn(STEP, item, f"Prefab anidado sin Blueprint: {child['prefab'].get('unity_path')}")
            else:
                h = _add(bp, parent_handle, unreal.SceneComponent, name)
                comp = _obj(h)
            t = child["transform"]
            set_prop(comp, "relative_location", vec(t["location"]))
            set_prop(comp, "relative_rotation", rot_from_quat(t["rotation_quat"]))
            set_prop(comp, "relative_scale3d", vec(t["scale"]))
            if not child.get("active", True):
                set_prop(comp, "visible", False)
            _add_components(bp, h, child, used, f"{item}/{child.get('name')}", set())
            _build_children(bp, h, child, used, f"{item}/{child.get('name')}")
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, f"{item}/{child.get('name')}")


def build_blueprint(package_path: str, root: dict, parent_class=None, item: str = "") -> object | None:
    folder, name = package_path.rsplit("/", 1)
    ensure_dir(folder)
    existing = load(package_path)
    if existing is not None:
        unreal.EditorAssetLibrary.delete_loaded_asset(existing)
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent_class or unreal.Actor)
    bp = ASSET_TOOLS.create_asset(name, folder, unreal.Blueprint, factory)
    if bp is None:
        LOG.error(STEP, item, f"No se pudo crear {package_path}")
        return None
    if parent_class is not None:
        # Variante: hereda del Blueprint base. Los overrides de la variante quedan en el JSON.
        LOG.warn(STEP, item, "Variante de prefab: revisar overrides respecto al Blueprint base")
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        save(bp)
        return bp

    handles = _sds().k2_gather_subobject_data_for_blueprint(bp)
    root_handle = handles[0]
    used: set[str] = {"DefaultSceneRoot"}
    skip: set[int] = set()
    rb = next((c for c in root.get("components", []) if c.get("type") == "Rigidbody"), None)
    if rb is not None:
        body = None
        for kind in PHYSICS_ROOT_PRIORITY:
            body = next((c for c in root.get("components", []) if c.get("type") == kind), None)
            if body:
                break
        if body is not None:
            try:
                h = _add(bp, root_handle, comps.component_class(body), _unique(body["type"], used))
                comp = _obj(h)
                comps.configure(comp, body, root, item)
                # La raíz de un cuerpo físico no puede tener offset: lo aplicamos al actor.
                set_prop(comp, "relative_location", unreal.Vector(0, 0, 0))
                _apply_rigidbody(comp, rb, item)
                if _sds().make_new_scene_root(root_handle, h, bp):
                    root_handle = h
                skip.add(id(body))
            except Exception:  # noqa: BLE001
                LOG.exception(STEP, f"{item}: raíz física")
        else:
            LOG.warn(STEP, item, "Rigidbody sin colisión ni malla: no se simula física")
    _add_components(bp, root_handle, root, used, item, skip)
    _build_children(bp, root_handle, root, used, item)
    # Tag/capa del GameObject raíz como tags del actor
    try:
        cdo = unreal.get_default_object(bp.generated_class())
        tags = [unreal.Name(root["tag"])] if root.get("tag") not in (None, "Untagged") else []
        if tags:
            cdo.set_editor_property("tags", tags)
    except Exception:  # noqa: BLE001
        pass
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    save(bp)
    return bp


def run(data: dict | None) -> None:
    if not data:
        return
    prefabs = data.get("prefabs", [])
    with unreal.ScopedSlowTask(len(prefabs), "unity2ue: Blueprints de prefabs") as slow:
        slow.make_dialog(True)
        for p in prefabs:
            slow.enter_progress_frame(1, p.get("unity_path", ""))
            item = p.get("unity_path", "?")
            try:
                parent_cls = None
                variant = p.get("variant_of")
                if variant:
                    parent_cls = resolve_class(variant.get("ue_class_path"))
                    if parent_cls is None:
                        LOG.warn(STEP, item, "Variante: Blueprint base no encontrado, se crea independiente")
                root = p.get("root")
                if root is None:
                    LOG.error(STEP, item, "Prefab vacío")
                    continue
                bp = build_blueprint(p["ue_blueprint_path"], root, parent_cls, item)
                if bp is not None:
                    LOG.ok(STEP, item, f"-> {p['ue_blueprint_path']}")
            except Exception:  # noqa: BLE001
                LOG.exception(STEP, item)
