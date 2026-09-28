"""Crea y configura componentes de UE a partir de los componentes convertidos (JSON).

Se usa tanto para plantillas de Blueprint (prefabs) como para actores de nivel.
"""

from __future__ import annotations

import unreal

from .common import (
    LOG,
    linear_color,
    resolve_asset,
    resolve_class,
    resolve_mesh,
    rot,
    script_class,
    set_prop,
    vec,
)

STEP = "components"

LIGHT_CLASSES = {
    "PointLight": unreal.PointLightComponent,
    "SpotLight": unreal.SpotLightComponent,
    "DirectionalLight": unreal.DirectionalLightComponent,
    "RectLight": unreal.RectLightComponent,
}


def _skeletal_as_static(c: dict) -> bool:
    """Modelo con skin que UE no pudo importar como SkeletalMesh (p.ej. varios huesos raíz) y quedó
    como StaticMesh: se muestra como malla estática en vez de dejar el componente vacío."""
    if c.get("type") != "SkeletalMesh" or resolve_mesh(c.get("mesh"), skeletal=True) is not None:
        return False
    return resolve_mesh(c.get("mesh")) is not None


def component_class(c: dict):
    t = c.get("type")
    if t == "StaticMesh" or _skeletal_as_static(c):
        return unreal.StaticMeshComponent
    if t == "SkeletalMesh":
        return unreal.SkeletalMeshComponent
    if t in LIGHT_CLASSES:
        return LIGHT_CLASSES[t]
    if t == "Camera":
        return unreal.CameraComponent
    if t == "BoxCollision":
        return unreal.BoxComponent
    if t == "SphereCollision":
        return unreal.SphereComponent
    if t == "CapsuleCollision":
        return unreal.CapsuleComponent
    if t == "Audio":
        return unreal.AudioComponent
    if t == "Particles":
        return getattr(unreal, "NiagaraComponent", None)
    if t == "Script":
        return script_class(c.get("cpp_class"))
    if t == "Sprite":
        return getattr(unreal, "PaperSpriteComponent", None)
    return None


def _mobility(comp, static: bool) -> None:
    if isinstance(comp, unreal.SceneComponent):
        set_prop(comp, "mobility", unreal.ComponentMobility.STATIC if static else unreal.ComponentMobility.MOVABLE)


def _collision(comp, c: dict) -> None:
    if c.get("is_trigger"):
        try:
            comp.set_collision_profile_name("OverlapAllDynamic")
        except Exception:  # noqa: BLE001
            set_prop(comp, "collision_profile_name", "OverlapAllDynamic")
        set_prop(comp, "generate_overlap_events", True)
    else:
        set_prop(comp, "generate_overlap_events", True)


def configure(comp, c: dict, node: dict, item: str) -> None:
    """Aplica las propiedades del componente convertido ``c`` al componente UE ``comp``."""
    t = c.get("type")
    if _skeletal_as_static(c):
        LOG.warn(STEP, item, "Malla con skin importada como estática: se usa StaticMeshComponent (sin animación)")
        c = dict(c, type="StaticMesh")
        t = "StaticMesh"
    try:
        if t == "StaticMesh":
            mesh = resolve_mesh(c.get("mesh"))
            if mesh is None and resolve_mesh(c.get("mesh"), skeletal=True) is not None:
                # Parte rígida de un FBX con esqueleto: UE la importa fusionada en la SkeletalMesh.
                LOG.add(STEP, item, "info", "Parte rígida incluida en la malla esquelética del modelo; se omite")
                set_prop(comp, "visible", False)
            elif mesh is None:
                LOG.warn(STEP, item, f"Malla no encontrada: {c.get('mesh')}")
            else:
                comp.set_editor_property("static_mesh", mesh)
            mats = [resolve_asset(m) for m in c.get("materials") or []]
            if any(mats):
                set_prop(comp, "override_materials", [m for m in mats if m is not None] if all(mats) else mats,
                         STEP, item)
            set_prop(comp, "cast_shadow", bool(c.get("cast_shadow", True)))
            set_prop(comp, "visible", bool(c.get("visible", True)))
            extra = (c.get("mesh") or {}).get("extra_scale")
            if extra and extra != [1.0, 1.0, 1.0]:
                set_prop(comp, "relative_scale3d", vec(extra))
            if (c.get("mesh") or {}).get("name") == "Quad":
                # El Quad de Unity es vertical (mira a -Z Unity = -X UE)
                set_prop(comp, "relative_rotation", rot([90.0, 0.0, 0.0]))
        elif t == "SkeletalMesh":
            mesh = resolve_mesh(c.get("mesh"), skeletal=True)
            if mesh is not None:
                if not set_prop(comp, "skeletal_mesh_asset", mesh):
                    set_prop(comp, "skeletal_mesh", mesh, STEP, item)
            mats = [resolve_asset(m) for m in c.get("materials") or []]
            if any(mats) and all(mats):
                set_prop(comp, "override_materials", mats, STEP, item)
        elif t in LIGHT_CLASSES:
            # FColor está en sRGB, igual que los colores serializados por Unity.
            r, g, b = (int(round(max(0.0, min(1.0, float(x))) * 255)) for x in c.get("color", [1, 1, 1])[:3])
            set_prop(comp, "light_color", unreal.Color(r=r, g=g, b=b, a=255))
            units = c.get("intensity_units")
            if units and t != "DirectionalLight":
                unit_enum = getattr(unreal.LightUnits, units.upper(), None)
                if unit_enum is not None:
                    set_prop(comp, "intensity_units", unit_enum)
            set_prop(comp, "intensity", float(c.get("intensity", 1.0)), STEP, item)
            set_prop(comp, "cast_shadows", bool(c.get("cast_shadows", True)))
            if c.get("use_temperature"):
                set_prop(comp, "use_temperature", True)
                set_prop(comp, "temperature", float(c.get("temperature", 6500)))
            if "attenuation_radius" in c:
                set_prop(comp, "attenuation_radius", float(c["attenuation_radius"]))
            if t == "SpotLight":
                set_prop(comp, "outer_cone_angle", float(c.get("outer_cone_angle", 44)))
                set_prop(comp, "inner_cone_angle", float(c.get("inner_cone_angle", 0)))
            if t == "RectLight":
                set_prop(comp, "source_width", float(c.get("source_width", 100)))
                set_prop(comp, "source_height", float(c.get("source_height", 100)))
            if t == "DirectionalLight":
                set_prop(comp, "atmosphere_sun_light", True)
        elif t == "Camera":
            set_prop(comp, "field_of_view", float(c.get("field_of_view", 90)))
            set_prop(comp, "aspect_ratio", float(c.get("aspect_ratio", 1.777)))
            if c.get("projection") == "orthographic":
                set_prop(comp, "projection_mode", unreal.CameraProjectionMode.ORTHOGRAPHIC)
                set_prop(comp, "ortho_width", float(c.get("ortho_width", 1000)))
        elif t == "BoxCollision":
            set_prop(comp, "box_extent", vec(c.get("box_extent", [50, 50, 50])))
            set_prop(comp, "relative_location", vec(c.get("offset", [0, 0, 0])))
            _collision(comp, c)
        elif t == "SphereCollision":
            set_prop(comp, "sphere_radius", float(c.get("radius", 50)))
            set_prop(comp, "relative_location", vec(c.get("offset", [0, 0, 0])))
            _collision(comp, c)
        elif t == "CapsuleCollision":
            radius = float(c.get("radius", 50))
            half = max(float(c.get("half_height", 100)), radius)
            set_prop(comp, "capsule_radius", radius)
            set_prop(comp, "capsule_half_height", half)
            set_prop(comp, "relative_location", vec(c.get("offset", [0, 0, 0])))
            if c.get("rotation"):
                set_prop(comp, "relative_rotation", rot(c["rotation"]))
            _collision(comp, c)
        elif t == "Audio":
            sound = resolve_asset(c.get("sound"))
            if sound is not None:
                set_prop(comp, "sound", sound)
            set_prop(comp, "auto_activate", bool(c.get("auto_activate", True)))
            set_prop(comp, "volume_multiplier", float(c.get("volume", 1.0)))
            set_prop(comp, "pitch_multiplier", float(c.get("pitch", 1.0)))
            if c.get("loop") and sound is not None:
                try:
                    sound.set_editor_property("looping", True)
                except Exception:  # noqa: BLE001
                    pass
        elif t == "Particles":
            set_prop(comp, "auto_activate", bool(c.get("play_on_awake", True)))
        elif t == "Script":
            configure_script(comp, c, item)
        if c.get("enabled") is False:
            set_prop(comp, "auto_activate", False)
    except Exception:  # noqa: BLE001
        LOG.exception(STEP, f"{item}:{t}")


def configure_script(comp, c: dict, item: str, actor_map: dict | None = None) -> None:
    """Asigna los valores serializados del MonoBehaviour a las UPROPERTY del componente C++."""
    for py_name, prop in (c.get("properties") or {}).items():
        value = prop.get("value")
        resolved = _resolve_value(value, actor_map)
        if resolved is _SKIP:
            continue
        if not set_prop(comp, py_name, resolved):
            # Los bool con prefijo b pierden la 'b' en Python.
            alt = py_name[2:] if py_name.startswith("b_") else None
            if not (alt and set_prop(comp, alt, resolved)):
                LOG.warn(STEP, item, f"{c.get('cpp_class')}.{prop.get('cpp')} = {str(value)[:60]} no asignado")


_SKIP = object()


def _resolve_value(value, actor_map):
    if value is None:
        return _SKIP
    if isinstance(value, bool) or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, dict):
        vt = value.get("__type")
        if vt == "Vector3":
            # Dirección/posición: se aplica cambio de ejes; las posiciones (m->cm) deben revisarse.
            return vec(value["ue_axes"])
        if vt == "Color":
            return linear_color(value["value"])
        if vt == "Quaternion":
            u = value["unity"]
            return unreal.Quat(float(u["z"]), float(u["x"]), float(u["y"]), float(u["w"]))
        if vt == "ObjectRef":
            if value.get("guid"):
                ref = value.get("resolved")
                if ref and ref.get("ue_class_path"):
                    return resolve_class(ref["ue_class_path"]) or _SKIP
                if ref:
                    return resolve_asset(ref) or _SKIP
                return _SKIP
            if actor_map is not None:
                target = actor_map.get(str(value.get("fileID")))
                return target if target is not None else _SKIP
            return _SKIP
        return _SKIP
    if isinstance(value, list):
        out = [_resolve_value(v, actor_map) for v in value]
        return [v for v in out if v is not _SKIP]
    return _SKIP
