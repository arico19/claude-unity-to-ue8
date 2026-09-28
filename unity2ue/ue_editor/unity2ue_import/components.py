"""Crea y configura componentes de UE a partir de los componentes convertidos (JSON).

Se usa tanto para plantillas de Blueprint (prefabs) como para actores de nivel.
"""

from __future__ import annotations

import unreal

from .common import (
    ASSET_TOOLS,
    LOG,
    ensure_dir,
    linear_color,
    load,
    resolve_asset,
    resolve_class,
    resolve_mesh,
    rot,
    save,
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
    if t == "Text3D":
        return unreal.TextRenderComponent
    if t == "Sprite":
        return unreal.StaticMeshComponent  # plano texturizado (ver _configure_sprite)
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


def _materials_by_slot(mesh, part_materials) -> list | None:
    """Reparte los materiales de Unity en las ranuras de una SkeletalMesh fusionada por su nombre.

    UE une las mallas con skin de un FBX (cuerpo, cabeza, manos...) en una sola con una ranura por
    material del FBX; en Unity cada parte tenía su material. Se empareja ranura <-> material por nombre.
    """
    if not part_materials:
        return None
    try:
        slots = list(mesh.get_editor_property("materials"))
    except Exception:  # noqa: BLE001
        return None
    if len(slots) < 2:
        return None

    def norm(s) -> str:
        return "".join(ch for ch in str(s).lower() if ch.isalnum())

    by_name = {}
    for ref in part_materials:
        path = ref.get("unity_path") or ""
        by_name.setdefault(norm(path.rsplit("/", 1)[-1].rsplit(".", 1)[0]), ref)
    out, found = [], 0
    for slot in slots:
        names = {norm(slot.get_editor_property("material_slot_name")),
                 norm(slot.get_editor_property("imported_material_slot_name"))}
        ref = next((by_name[n] for n in names if n in by_name), None)
        mat = resolve_asset(ref) if ref else None
        found += mat is not None
        out.append(mat if mat is not None else slot.get_editor_property("material_interface"))
    return out if found else None


SPRITE_FOLDER = "/Game/Unity/_Sprites"
_SPRITE_MATS: dict = {}


def _sprite_material(texture, color, item: str):
    """Material Instance translúcido, sin iluminación y a dos caras para un sprite (textura x color)."""
    rgba = [round(float(x), 3) for x in (list(color or [1, 1, 1, 1]) + [1.0])[:4]]
    key = (texture.get_path_name(), tuple(rgba))
    if key in _SPRITE_MATS:
        return _SPRITE_MATS[key]
    ensure_dir(SPRITE_FOLDER)
    name = f"MI_Sprite_{texture.get_name()}_" + "".join(f"{int(v * 255):02x}" for v in rgba)
    path = f"{SPRITE_FOLDER}/{name}"
    mi = load(path)
    if mi is None:
        mi = ASSET_TOOLS.create_asset(name, SPRITE_FOLDER, unreal.MaterialInstanceConstant,
                                      unreal.MaterialInstanceConstantFactoryNew())
    mel = unreal.MaterialEditingLibrary
    mel.set_material_instance_parent(mi, load("/Game/Unity/_Master/M_UnityUnlit"))
    mel.set_material_instance_texture_parameter_value(mi, "BaseColorMap", texture)
    mel.set_material_instance_vector_parameter_value(mi, "BaseColorTint", unreal.LinearColor(*rgba))
    overrides = mi.get_editor_property("base_property_overrides")
    set_prop(overrides, "override_blend_mode", True)
    set_prop(overrides, "blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    set_prop(overrides, "override_two_sided", True)
    set_prop(overrides, "two_sided", True)
    mi.set_editor_property("base_property_overrides", overrides)
    mel.update_material_instance(mi)
    save(mi)
    _SPRITE_MATS[key] = mi
    return mi


def _configure_sprite(comp, c: dict, node: dict, item: str) -> None:
    """SpriteRenderer de Unity -> plano de /Engine/BasicShapes (1x1 m) en el plano XY de Unity (YZ de UE)."""
    texture = resolve_asset(c.get("sprite"))
    if texture is None:
        LOG.warn(STEP, item, f"Sprite sin textura importada: {c.get('sprite')}")
        return
    set_prop(comp, "static_mesh", load("/Engine/BasicShapes/Plane"), STEP, item)
    width, height = (c.get("size") or [1.0, 1.0])[:2]
    # El plano es XY (U a lo largo de X, V a lo largo de Y) con normal +Z. Se orienta en el plano
    # XY de Unity (YZ de UE): X local -> +Y (ancho de la imagen, izquierda a derecha) e Y local -> -Z
    # (filas de la imagen, de arriba abajo); la normal queda hacia -X, hacia la cámara de Unity.
    rot = unreal.MathLibrary.make_rot_from_xy(unreal.Vector(0, 1, 0), unreal.Vector(0, 0, -1))
    set_prop(comp, "relative_rotation", rot)
    sx = -1.0 if c.get("flip_x") else 1.0
    sy = -1.0 if c.get("flip_y") else 1.0
    # UE multiplica escalas padre/hijo eje a eje sin tener en cuenta la rotación del hijo (no hay
    # cizalla): con el plano girado, la escala no uniforme del nodo (p.ej. 1 x 2.25 x 0.8) caería en
    # el eje equivocado. Se compensa: X local (ancho) va a Y del padre, Y local (alto) a Z del padre.
    px, py, pz = (float(v) or 1.0 for v in (node.get("transform") or {}).get("scale", [1.0, 1.0, 1.0]))
    set_prop(comp, "relative_scale3d", unreal.Vector(width * sx * py / px, height * sy * pz / py, 1.0))
    set_prop(comp, "override_materials", [_sprite_material(texture, c.get("color"), item)], STEP, item)
    set_prop(comp, "cast_shadow", False)
    comp.set_collision_profile_name("NoCollision")


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
            by_slot = _materials_by_slot(mesh, c.get("part_materials")) if mesh is not None else None
            mats = by_slot or [resolve_asset(m) for m in c.get("materials") or []]
            if any(mats) and (by_slot or all(mats)):
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
        elif t == "Sprite":
            _configure_sprite(comp, c, node, item)
        elif t == "Text3D":
            set_prop(comp, "text", unreal.Text(c.get("text", "")), STEP, item)
            set_prop(comp, "world_size", float(c.get("world_size", 36.0)))
            align = {"left": unreal.HorizTextAligment.EHTA_LEFT, "right": unreal.HorizTextAligment.EHTA_RIGHT}.get(
                c.get("alignment"), unreal.HorizTextAligment.EHTA_CENTER)
            set_prop(comp, "horizontal_alignment", align)
            set_prop(comp, "vertical_alignment", unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
            if c.get("color"):
                r, g, b = (int(round(max(0.0, min(1.0, float(x))) ** (1 / 2.2) * 255)) for x in c["color"][:3])
                set_prop(comp, "text_render_color", unreal.Color(r=r, g=g, b=b, a=255))
            # El texto de TMP se lee mirando hacia +Z de Unity (+X de UE); TextRender se lee desde +X.
            set_prop(comp, "relative_rotation", unreal.Rotator(roll=0, pitch=0, yaw=180))
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
