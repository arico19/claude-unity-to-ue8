"""Mapeo de componentes de Unity a componentes de Unreal Engine.

Cada conversor recibe el objeto Unity y devuelve un dict neutral (JSON) que los scripts
del editor de UE (``ue_editor/unity2ue_import``) saben materializar. Todo lo que no se
puede traducir automáticamente se registra como incidencia ``manual``.
"""

from __future__ import annotations

from typing import Any, Callable

from ..naming import cpp_property_name, to_snake
from ..unity import class_ids as C
from ..unity.builtin import KNOWN_PACKAGE_SCRIPTS
from ..unity.yaml_parser import UnityObject, ref_file_id, ref_guid
from .context import ConversionContext
from .coords import (
    axis_swap,
    color_to_linear,
    location_to_ue,
    vec_from_unity,
    vertical_to_horizontal_fov,
)

Converter = Callable[[UnityObject, ConversionContext, str], "dict[str, Any] | list[dict[str, Any]] | None"]

MONO_BEHAVIOUR_BASE_KEYS = {
    "m_ObjectHideFlags", "m_CorrespondingSourceObject", "m_PrefabInstance", "m_PrefabAsset",
    "m_GameObject", "m_Enabled", "m_EditorHideFlags", "m_Script", "m_Name", "m_EditorClassIdentifier",
    "serializedVersion",
}


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _b(v: Any, d: bool = False) -> bool:
    if v is None:
        return d
    try:
        return bool(int(v))
    except (TypeError, ValueError):
        return bool(v)


def _materials(obj: UnityObject, ctx: ConversionContext, src: str) -> list[dict[str, Any] | None]:
    return [ctx.asset_ref(m, src) for m in obj.get("m_Materials") or []]


def _shadow_flags(obj: UnityObject) -> dict[str, Any]:
    return {
        "cast_shadow": _b(obj.get("m_CastShadows"), True),
        "visible": _b(obj.get("m_Enabled"), True),
    }


# ---------------------------------------------------------------------- render
def mesh_renderer(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    return {"type": "MeshRenderer", "materials": _materials(obj, ctx, src), **_shadow_flags(obj)}


def mesh_filter(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any] | None:
    ref = ctx.asset_ref(obj.get("m_Mesh"), src)
    if ref and ref.get("kind") == "asset":
        ctx.manual(src, "Malla almacenada como .asset (ProBuilder/procedural): exportarla a FBX desde Unity.")
    ctx.mark_model(ref, skeletal=False, source=src)
    return {"type": "MeshFilter", "mesh": ref}


def skinned_mesh_renderer(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ref = ctx.asset_ref(obj.get("m_Mesh"), src)
    ctx.mark_model(ref, skeletal=True, source=src)
    return {
        "type": "SkeletalMesh",
        "mesh": ref,
        "materials": _materials(obj, ctx, src),
        **_shadow_flags(obj),
    }


def sprite_renderer(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(src, "SpriteRenderer -> PaperSpriteComponent: requiere plugin Paper2D y crear los PaperSprite.")
    return {
        "type": "Sprite",
        "sprite": ctx.asset_ref(obj.get("m_Sprite"), src),
        "color": color_to_linear(obj.get("m_Color")),
        "flip_x": _b(obj.get("m_FlipX")),
        "flip_y": _b(obj.get("m_FlipY")),
        "sorting_order": obj.get("m_SortingOrder", 0),
    }


def lod_group(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    lods = []
    for lod in obj.get("m_LODs") or []:
        lods.append({"screen_relative_height": _f(lod.get("screenRelativeHeight"))})
    ctx.info(src, "LODGroup: en UE los LOD viven dentro del StaticMesh. Importa el FBX con LODs (sufijo _LOD0..n).")
    return {"type": "LODGroup", "lods": lods}


# ---------------------------------------------------------------------- cámara / luces
def camera(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    vfov = _f(obj.get("field of view"), _f(obj.get("m_FieldOfView"), 60.0))
    ortho = _b(obj.get("orthographic"))
    return {
        "type": "Camera",
        "field_of_view": vertical_to_horizontal_fov(vfov, ctx.config.camera_aspect),
        "unity_vertical_fov": vfov,
        "near_clip": _f(obj.get("near clip plane"), 0.3) * 100.0,
        "far_clip": _f(obj.get("far clip plane"), 1000.0) * 100.0,
        "projection": "orthographic" if ortho else "perspective",
        "ortho_width": _f(obj.get("orthographic size"), 5.0) * 2.0 * 100.0 * ctx.config.camera_aspect,
        "aspect_ratio": ctx.config.camera_aspect,
        "depth": _f(obj.get("m_Depth")),
    }


_LIGHT_TYPES = {0: "SpotLight", 1: "DirectionalLight", 2: "PointLight", 3: "RectLight", 4: "RectLight"}
_LIGHTMAP_MOBILITY = {4: "Movable", 1: "Stationary", 2: "Static"}


def light(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ltype = int(obj.get("m_Type", 2) or 0)
    kind = _LIGHT_TYPES.get(ltype, "PointLight")
    intensity = _f(obj.get("m_Intensity"), 1.0)
    li = ctx.config.light_intensity
    shadows = (obj.get("m_Shadows") or {}).get("m_Type", 0)
    out: dict[str, Any] = {
        "type": kind,
        "color": color_to_linear(obj.get("m_Color")),
        "unity_intensity": intensity,
        "cast_shadows": int(shadows or 0) > 0,
        "mobility": _LIGHTMAP_MOBILITY.get(int(obj.get("m_Lightmapping", 4) or 4), "Movable"),
        "use_temperature": _b(obj.get("m_UseColorTemperature")),
        "temperature": _f(obj.get("m_ColorTemperature"), 6570.0),
    }
    if kind == "DirectionalLight":
        out["intensity"] = intensity * li["directional_lux_per_unit"]
        out["intensity_units"] = "Lux"
    else:
        key = {"SpotLight": "spot", "PointLight": "point"}.get(kind, "area")
        out["intensity"] = intensity * li[f"{key}_candela_per_unit"]
        out["intensity_units"] = "Candelas"
        out["attenuation_radius"] = _f(obj.get("m_Range"), 10.0) * 100.0
    if kind == "SpotLight":
        outer = _f(obj.get("m_SpotAngle"), 30.0)
        inner = _f(obj.get("m_InnerSpotAngle"), outer * 0.7)
        # Unity: ángulo total del cono; UE: semiángulo.
        out["outer_cone_angle"] = outer / 2.0
        out["inner_cone_angle"] = min(inner, outer) / 2.0
    if kind == "RectLight":
        size = obj.get("m_AreaSize") or {"x": 1, "y": 1}
        out["source_width"] = _f(size.get("x"), 1.0) * 100.0
        out["source_height"] = _f(size.get("y"), 1.0) * 100.0
        if ltype == 3:
            ctx.info(src, "Luz de área (baked en Unity) convertida a RectLight dinámica.")
    return out


def reflection_probe(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    size = axis_swap(vec_from_unity(obj.get("m_BoxSize"), (10, 10, 10)))
    return {"type": "ReflectionCapture", "box_extent": [s * 50.0 for s in size]}


# ---------------------------------------------------------------------- física
def _center(obj: UnityObject) -> list[float]:
    return list(location_to_ue(vec_from_unity(obj.get("m_Center"))))


def box_collider(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    size = axis_swap(vec_from_unity(obj.get("m_Size"), (1, 1, 1)))
    return {
        "type": "BoxCollision",
        "box_extent": [round(s * 50.0, 5) for s in size],  # UE usa semiextensión en cm
        "offset": _center(obj),
        "is_trigger": _b(obj.get("m_IsTrigger")),
        "physics_material": ctx.asset_ref(obj.get("m_Material"), src),
    }


def sphere_collider(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    return {
        "type": "SphereCollision",
        "radius": _f(obj.get("m_Radius"), 0.5) * 100.0,
        "offset": _center(obj),
        "is_trigger": _b(obj.get("m_IsTrigger")),
    }


def capsule_collider(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    direction = int(obj.get("m_Direction", 1) or 0)
    # Cápsula de UE alineada con Z (= Y de Unity). Rotación relativa (Pitch, Yaw, Roll).
    rotation = {0: [0.0, 0.0, 90.0], 1: [0.0, 0.0, 0.0], 2: [90.0, 0.0, 0.0]}.get(direction, [0.0, 0.0, 0.0])
    return {
        "type": "CapsuleCollision",
        "radius": _f(obj.get("m_Radius"), 0.5) * 100.0,
        "half_height": _f(obj.get("m_Height"), 2.0) * 50.0,
        "offset": _center(obj),
        "rotation": rotation,
        "is_trigger": _b(obj.get("m_IsTrigger")),
    }


def mesh_collider(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ref = ctx.asset_ref(obj.get("m_Mesh"), src)
    ctx.mark_model(ref, skeletal=False, source=src)
    return {
        "type": "MeshCollision",
        "convex": _b(obj.get("m_Convex")),
        "mesh": ref,
        "is_trigger": _b(obj.get("m_IsTrigger")),
    }


def character_controller(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(
        src,
        "CharacterController: en UE usa un ACharacter (Capsule + CharacterMovementComponent). "
        "Se crea la cápsula; la lógica de movimiento debe migrarse al Character.",
    )
    return {
        "type": "CapsuleCollision",
        "radius": _f(obj.get("m_Radius"), 0.5) * 100.0,
        "half_height": _f(obj.get("m_Height"), 2.0) * 50.0,
        "offset": _center(obj),
        "rotation": [0.0, 0.0, 0.0],
        "is_trigger": False,
        "character_controller": {
            "slope_limit": _f(obj.get("m_SlopeLimit"), 45.0),
            "step_offset": _f(obj.get("m_StepOffset"), 0.3) * 100.0,
        },
    }


def rigidbody(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    constraints = int(obj.get("m_Constraints", 0) or 0)
    # Bits Unity: PosX=2, PosY=4, PosZ=8, RotX=16, RotY=32, RotZ=64. Ejes Unity->UE: X->Y, Y->Z, Z->X
    lock = {
        "lock_position": {"x": bool(constraints & 8), "y": bool(constraints & 2), "z": bool(constraints & 4)},
        "lock_rotation": {"x": bool(constraints & 64), "y": bool(constraints & 16), "z": bool(constraints & 32)},
    }
    return {
        "type": "Rigidbody",
        "mass_kg": _f(obj.get("m_Mass"), 1.0),
        "linear_damping": _f(obj.get("m_Drag", obj.get("m_LinearDamping")), 0.0),
        "angular_damping": _f(obj.get("m_AngularDrag", obj.get("m_AngularDamping")), 0.05),
        "enable_gravity": _b(obj.get("m_UseGravity"), True),
        "kinematic": _b(obj.get("m_IsKinematic")),
        "ccd": int(obj.get("m_CollisionDetection", 0) or 0) > 0,
        **lock,
    }


def rigidbody_2d(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(src, "Física 2D (Rigidbody2D/Collider2D) convertida a física 3D con el eje de profundidad bloqueado.")
    return {
        "type": "Rigidbody",
        "mass_kg": _f(obj.get("m_Mass"), 1.0),
        "linear_damping": _f(obj.get("m_LinearDrag"), 0.0),
        "angular_damping": _f(obj.get("m_AngularDrag"), 0.05),
        "enable_gravity": _f(obj.get("m_GravityScale"), 1.0) != 0.0,
        "kinematic": int(obj.get("m_BodyType", 0) or 0) == 1,
        "lock_position": {"x": True, "y": False, "z": False},
        "lock_rotation": {"x": False, "y": True, "z": True},
    }


def box_collider_2d(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    size = obj.get("m_Size") or {"x": 1, "y": 1}
    off = obj.get("m_Offset") or {"x": 0, "y": 0}
    return {
        "type": "BoxCollision",
        "box_extent": [50.0, _f(size.get("x"), 1) * 50.0, _f(size.get("y"), 1) * 50.0],
        "offset": [0.0, _f(off.get("x")) * 100.0, _f(off.get("y")) * 100.0],
        "is_trigger": _b(obj.get("m_IsTrigger")),
    }


def circle_collider_2d(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    off = obj.get("m_Offset") or {"x": 0, "y": 0}
    return {
        "type": "SphereCollision",
        "radius": _f(obj.get("m_Radius"), 0.5) * 100.0,
        "offset": [0.0, _f(off.get("x")) * 100.0, _f(off.get("y")) * 100.0],
        "is_trigger": _b(obj.get("m_IsTrigger")),
    }


# ---------------------------------------------------------------------- audio
def audio_source(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    return {
        "type": "Audio",
        "sound": ctx.asset_ref(obj.get("m_audioClip"), src),
        "auto_activate": _b(obj.get("m_PlayOnAwake"), True),
        "loop": _b(obj.get("Loop")),
        "volume": _f(obj.get("m_Volume"), 1.0),
        "pitch": _f(obj.get("m_Pitch"), 1.0),
        "min_distance": _f(obj.get("MinDistance"), 1.0) * 100.0,
        "max_distance": _f(obj.get("MaxDistance"), 500.0) * 100.0,
    }


def audio_listener(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.info(src, "AudioListener: en UE el listener es el PlayerController/cámara; se ignora.")
    return {"type": "AudioListener"}


# ---------------------------------------------------------------------- animación / FX / IA
def animator(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    controller = ctx.asset_ref(obj.get("m_Controller"), src)
    if controller:
        ctx.manual(src, f"Animator: recrear '{controller.get('unity_path')}' como Animation Blueprint (ver animators.json).")
    return {
        "type": "Animator",
        "controller": controller,
        "avatar": ctx.asset_ref(obj.get("m_Avatar"), src),
        "apply_root_motion": _b(obj.get("m_ApplyRootMotion")),
    }


def legacy_animation(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(src, "Componente Animation (legacy): usar PlayAnimation en SkeletalMeshComponent.")
    return {"type": "LegacyAnimation", "clip": ctx.asset_ref(obj.get("m_Animation"), src)}


def particle_system(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(src, "ParticleSystem (Shuriken) -> recrear como sistema Niagara. Se crea un NiagaraComponent vacío.")
    main = obj.get("InitialModule") or {}
    return {
        "type": "Particles",
        "duration": _f(obj.get("lengthInSec"), 5.0),
        "looping": _b(obj.get("looping"), True),
        "play_on_awake": _b(obj.get("playOnAwake"), True),
        "max_particles": main.get("maxNumParticles"),
    }


def nav_mesh_agent(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(src, "NavMeshAgent: usar un Pawn con AIController + FloatingPawnMovement/CharacterMovement y NavMeshBoundsVolume.")
    return {
        "type": "NavAgent",
        "speed": _f(obj.get("m_Speed"), 3.5) * 100.0,
        "radius": _f(obj.get("m_Radius"), 0.5) * 100.0,
        "height": _f(obj.get("m_Height"), 2.0) * 100.0,
        "stopping_distance": _f(obj.get("m_StoppingDistance")) * 100.0,
    }


def nav_mesh_obstacle(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    return {"type": "NavObstacle", "carve": _b(obj.get("m_Carve"))}


def line_renderer(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(src, f"{obj.type_name}: sin equivalente directo (usar Niagara Ribbon o SplineMesh).")
    return {"type": "Unsupported", "unity_type": obj.type_name}


def canvas(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(src, "UI (Canvas/uGUI): recrear como Widget Blueprint (UMG). Jerarquía exportada en ui.json.")
    return {"type": "UICanvas", "render_mode": obj.get("m_RenderMode", 0)}


def terrain(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any]:
    ctx.manual(src, "Terrain: exportar heightmap (RAW 16-bit) desde Unity e importarlo como Landscape en UE.")
    return {"type": "Terrain", "terrain_data": ctx.asset_ref(obj.get("m_TerrainData"), src)}


# ---------------------------------------------------------------------- scripts
def _serialize_value(value: Any, ctx: ConversionContext | None = None, src: str = "") -> Any:
    """Normaliza valores serializados de un MonoBehaviour a algo útil en UE."""
    if isinstance(value, dict):
        keys = set(value)
        if keys >= {"x", "y", "z", "w"}:
            return {"__type": "Quaternion", "unity": value}
        if keys >= {"x", "y", "z"}:
            return {"__type": "Vector3", "unity": value, "ue_axes": list(axis_swap(vec_from_unity(value)))}
        if keys >= {"r", "g", "b"}:
            return {"__type": "Color", "value": color_to_linear(value)}
        if "fileID" in keys:
            if not ref_file_id(value) and not ref_guid(value):
                return None
            out = {"__type": "ObjectRef", "fileID": ref_file_id(value), "guid": ref_guid(value)}
            if ctx is not None and ref_guid(value):
                out["resolved"] = ctx.asset_ref(value, src)
            return out
        return {k: _serialize_value(v, ctx, src) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v, ctx, src) for v in value]
    return value


def mono_behaviour(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any] | None:
    script_ref = obj.get("m_Script")
    guid = ref_guid(script_ref)
    script = ctx.scripts.get(guid) if guid else None
    props = {k: _serialize_value(v, ctx, src) for k, v in obj.data.items() if k not in MONO_BEHAVIOUR_BASE_KEYS}
    if script is None:
        info = ctx.project.guids.get(guid)
        known = KNOWN_PACKAGE_SCRIPTS.get(guid or "")
        if known:
            if known.startswith(("UnityEngine.UI", "TMPro")):
                ctx.manual(src, f"{known}: recrear en el Widget Blueprint (UMG) correspondiente.")
            return {"type": "PackageScript", "unity_class": known, "guid": guid, "properties": props}
        ctx.warn(
            src,
            f"MonoBehaviour con script no resuelto (guid={guid}, fileID={ref_file_id(script_ref)}). "
            "Probablemente de un paquete (UI, TextMeshPro, Cinemachine...).",
        )
        return {
            "type": "UnresolvedScript",
            "guid": guid,
            "unity_path": info.path if info else None,
            "properties": props,
        }
    ue_props = {}
    for key, value in props.items():
        cpp = script.field_map.get(key) or cpp_property_name(key)
        ue_props[to_snake(cpp)] = {"unity_field": key, "cpp": cpp, "value": value}
    return {
        "type": "Script",
        "unity_class": script.unity_class,
        "cpp_class": script.cpp_class,
        "script_path": script.unity_path,
        "enabled": _b(obj.get("m_Enabled"), True),
        "properties": ue_props,
    }


def ignored(obj: UnityObject, ctx: ConversionContext, src: str) -> None:
    return None


CONVERTERS: dict[int, Converter] = {
    C.MESH_RENDERER: mesh_renderer,
    C.MESH_FILTER: mesh_filter,
    C.SKINNED_MESH_RENDERER: skinned_mesh_renderer,
    C.SPRITE_RENDERER: sprite_renderer,
    C.LOD_GROUP: lod_group,
    C.CAMERA: camera,
    C.LIGHT: light,
    C.REFLECTION_PROBE: reflection_probe,
    C.BOX_COLLIDER: box_collider,
    C.SPHERE_COLLIDER: sphere_collider,
    C.CAPSULE_COLLIDER: capsule_collider,
    C.MESH_COLLIDER: mesh_collider,
    C.CHARACTER_CONTROLLER: character_controller,
    C.RIGIDBODY: rigidbody,
    C.RIGIDBODY_2D: rigidbody_2d,
    C.BOX_COLLIDER_2D: box_collider_2d,
    C.CIRCLE_COLLIDER_2D: circle_collider_2d,
    C.AUDIO_SOURCE: audio_source,
    C.AUDIO_LISTENER: audio_listener,
    C.ANIMATOR: animator,
    C.ANIMATION: legacy_animation,
    C.PARTICLE_SYSTEM: particle_system,
    C.NAV_MESH_AGENT: nav_mesh_agent,
    C.NAV_MESH_OBSTACLE: nav_mesh_obstacle,
    C.LINE_RENDERER: line_renderer,
    C.TRAIL_RENDERER: line_renderer,
    C.CANVAS: canvas,
    C.TERRAIN: terrain,
    C.MONO_BEHAVIOUR: mono_behaviour,
    # Sin equivalente o gestionados en otro sitio:
    C.TRANSFORM: ignored,
    C.RECT_TRANSFORM: ignored,
    C.PARTICLE_SYSTEM_RENDERER: ignored,
    C.CANVAS_RENDERER: ignored,
    C.FLARE_LAYER: ignored,
    C.TERRAIN_COLLIDER: ignored,
    C.CANVAS_GROUP: ignored,
}


def convert_component(obj: UnityObject, ctx: ConversionContext, src: str) -> dict[str, Any] | None:
    fn = CONVERTERS.get(obj.class_id)
    if fn is None:
        ctx.manual(src, f"Componente sin conversor: {obj.type_name} (classID {obj.class_id}).")
        return {"type": "Unsupported", "unity_type": obj.type_name, "class_id": obj.class_id}
    result = fn(obj, ctx, src)
    if isinstance(result, dict):
        result.setdefault("unity_type", obj.type_name)
        result.setdefault("unity_file_id", obj.file_id)
        if "enabled" not in result and obj.get("m_Enabled") is not None:
            result["enabled"] = _b(obj.get("m_Enabled"), True)
    return result  # type: ignore[return-value]


def merge_render_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fusiona MeshFilter + MeshRenderer en un único ``StaticMesh`` (como en UE)."""
    filt = next((c for c in components if c["type"] == "MeshFilter"), None)
    rend = next((c for c in components if c["type"] == "MeshRenderer"), None)
    out = [c for c in components if c["type"] not in ("MeshFilter", "MeshRenderer")]
    if filt or rend:
        merged = {
            "type": "StaticMesh",
            "unity_type": "MeshFilter+MeshRenderer",
            "mesh": (filt or {}).get("mesh"),
            "materials": (rend or {}).get("materials", []),
            "cast_shadow": (rend or {}).get("cast_shadow", True),
            "visible": (rend or {}).get("visible", True) if rend else False,
        }
        out.insert(0, merged)
    return out
