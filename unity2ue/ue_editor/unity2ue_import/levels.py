"""Crea un nivel por cada escena de Unity (``levels.json`` + ``levels/*.json``).

Cada GameObject se convierte en un actor, respetando la jerarquía con attachments:
* Un único componente "principal" (malla, luz, cámara) -> actor tipado de UE.
* GameObject con Rigidbody -> Blueprint generado (la física necesita el cuerpo como raíz).
* Instancia de prefab -> actor del Blueprint del prefab.
* Resto -> ``AUnityGameObject`` (módulo generado) con componentes añadidos.
"""

from __future__ import annotations

import unreal

from . import components as comps
from .blueprints import build_blueprint
from .common import (
    LOG,
    content_root,
    data_dir,
    linear_color,
    load_json,
    resolve_class,
    rot_from_quat,
    script_class,
    set_prop,
    settings,
    vec,
)

STEP = "levels"
EAS = None
LES = None
SDS = None
LIB = unreal.SubobjectDataBlueprintFunctionLibrary

PRIMARY_ACTORS = {
    "StaticMesh": (unreal.StaticMeshActor, "static_mesh_component"),
    "SkeletalMesh": (unreal.SkeletalMeshActor, "skeletal_mesh_component"),
    "PointLight": (unreal.PointLight, "point_light_component"),
    "SpotLight": (unreal.SpotLight, "spot_light_component"),
    "DirectionalLight": (unreal.DirectionalLight, "directional_light_component"),
    "RectLight": (unreal.RectLight, "rect_light_component"),
    "Camera": (unreal.CameraActor, "camera_component"),
}
IGNORED = {"AudioListener", "Rigidbody", "MeshCollision", "LODGroup", "Animator", "UnresolvedScript",
           "PackageScript", "Unsupported", "UICanvas", "NavAgent", "NavObstacle", "Terrain", "LegacyAnimation"}


def _subsystems():
    global EAS, LES, SDS
    if EAS is None:
        EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        LES = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)


def _generic_actor_class():
    cls = script_class("UnityGameObject")
    return cls or unreal.StaticMeshActor  # sin módulo compilado: StaticMeshActor vacío como "grupo"


class LevelBuilder:
    def __init__(self, level: dict) -> None:
        self.level = level
        self.name = level.get("name", "Level")
        self.actor_by_unity_id: dict[str, unreal.Actor] = {}
        self.pending_scripts: list[tuple[object, dict, str]] = []
        self.generated_folder = f"{content_root()}/Maps/{self.name}_Generated"
        self._scale_override = None

    # ------------------------------------------------------------ componentes extra
    def _add_instance_component(self, actor, cls, c: dict, node: dict, item: str):
        handles = SDS.k2_gather_subobject_data_for_instance(actor)
        if not handles:
            raise RuntimeError("sin handles de subobjetos")
        parent = handles[0]
        root = actor.get_editor_property("root_component")
        for h in handles:
            if LIB.get_object(LIB.get_data(h)) == root:
                parent = h
                break
        params = unreal.AddNewSubobjectParams(parent_handle=parent, new_class=cls, blueprint_context=None)
        handle, fail = SDS.add_new_subobject(params)
        if not LIB.is_handle_valid(handle):
            raise RuntimeError(f"add_new_subobject falló: {fail}")
        comp = LIB.get_object(LIB.get_data(handle))
        if c.get("type") == "Script":
            self.pending_scripts.append((comp, c, item))
        else:
            comps.configure(comp, c, node, item)
        return comp

    # ------------------------------------------------------------ actores
    def _spawn(self, cls, node: dict):
        actor = EAS.spawn_actor_from_class(cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if actor is None:
            raise RuntimeError(f"No se pudo generar {cls}")
        return actor

    def _node_actor(self, node: dict, item: str):
        comps_data = [c for c in node.get("components", []) if c.get("type") not in IGNORED]
        has_rb = any(c.get("type") == "Rigidbody" for c in node.get("components", []))
        if node.get("prefab"):
            cls = resolve_class(node["prefab"].get("ue_class_path"))
            if cls is None:
                LOG.warn(STEP, item, f"Blueprint de prefab no encontrado: {node['prefab'].get('unity_path')}")
                return self._spawn(_generic_actor_class(), node), []
            return self._spawn(cls, node), []
        if has_rb:
            bp_path = f"{self.generated_folder}/BP_{node['name']}_{node['id']}".replace(" ", "_")
            root = dict(node)
            root["children"] = []  # los hijos se crean como actores adjuntos
            bp = build_blueprint(bp_path, root, None, item)
            if bp is not None:
                return self._spawn(bp.generated_class(), node), []
        primaries = [c for c in comps_data if c.get("type") in PRIMARY_ACTORS]
        if len(primaries) >= 1:
            primary = primaries[0]
            extra_scale = (primary.get("mesh") or {}).get("extra_scale")
            scaled_with_children = extra_scale and extra_scale != [1.0, 1.0, 1.0] and node.get("children")
            if not scaled_with_children:
                cls, comp_prop = PRIMARY_ACTORS[primary["type"]]
                actor = self._spawn(cls, node)
                comp = actor.get_editor_property(comp_prop)
                comps.configure(comp, primary, node, item)
                extra = (primary.get("mesh") or {}).get("extra_scale")
                if extra and extra != [1.0, 1.0, 1.0]:
                    comp.set_editor_property("relative_scale3d", unreal.Vector(1, 1, 1))
                    node = dict(node)
                    s = node["transform"]["scale"]
                    node["transform"] = dict(node["transform"], scale=[s[0] * extra[0], s[1] * extra[1], s[2] * extra[2]])
                    self._scale_override = node["transform"]["scale"]
                return actor, [c for c in comps_data if c is not primary]
        return self._spawn(_generic_actor_class(), node), comps_data

    def _place(self, actor, node: dict, parent, static: bool) -> None:
        t = node["transform"]
        root = actor.get_editor_property("root_component")
        if root is not None:
            set_prop(root, "mobility", unreal.ComponentMobility.STATIC if static else unreal.ComponentMobility.MOVABLE)
        if parent is not None:
            actor.attach_to_actor(parent, "", unreal.AttachmentRule.KEEP_RELATIVE, unreal.AttachmentRule.KEEP_RELATIVE,
                                  unreal.AttachmentRule.KEEP_RELATIVE, False)
        scale = getattr(self, "_scale_override", None) or t["scale"]
        self._scale_override = None
        actor.set_actor_relative_location(vec(t["location"]), False, False)
        actor.set_actor_relative_rotation(rot_from_quat(t["rotation_quat"]), False, False)
        actor.set_actor_relative_scale3d(vec(scale))

    def _flags(self, actor, node: dict) -> None:
        actor.set_actor_label(node.get("name", "GameObject"))
        tags = [unreal.Name("Unity2UE")]
        if node.get("tag") and node["tag"] != "Untagged":
            tags.append(unreal.Name(node["tag"]))
        layers = (settings().get("tags_and_layers") or {}).get("layers") or {}
        layer_name = layers.get(str(node.get("layer", 0)))
        if layer_name and layer_name != "Default":
            tags.append(unreal.Name(f"Layer:{layer_name}"))
        set_prop(actor, "tags", tags)
        set_prop(actor, "unity_layer", int(node.get("layer", 0)))
        if not node.get("active", True):
            actor.set_actor_hidden_in_game(True)
            actor.set_actor_enable_collision(False)
            try:
                actor.set_is_temporarily_hidden_in_editor(True)
            except Exception:  # noqa: BLE001
                pass

    def build_node(self, node: dict, parent, parent_static: bool, path: str) -> None:
        item = f"{self.name}:{path}/{node.get('name')}"
        static = bool(node.get("static")) and parent_static
        try:
            actor, extra = self._node_actor(node, item)
            self._place(actor, node, parent, static)
            self._flags(actor, node)
            for c in extra:
                cls = comps.component_class(c)
                if cls is None:
                    if c.get("type") == "Script":
                        LOG.warn(STEP, item, f"Clase C++ {c.get('cpp_class')} no encontrada (¿módulo compilado?)")
                    continue
                try:
                    self._add_instance_component(actor, cls, c, node, item)
                except Exception:  # noqa: BLE001
                    LOG.exception(STEP, f"{item}:{c.get('type')}")
            for uid in node.get("unity_ids", [node.get("id")]):
                self.actor_by_unity_id[str(uid)] = actor
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, item)
            return
        for child in node.get("children", []):
            self.build_node(child, actor, static, f"{path}/{node.get('name')}")

    # ------------------------------------------------------------ entorno
    def environment(self) -> None:
        env = self.level.get("environment") or {}
        try:
            EAS.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
            sky = EAS.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 0))
            sky_comp = sky.get_editor_property("light_component")
            set_prop(sky_comp, "real_time_capture", True)
            set_prop(sky_comp, "mobility", unreal.ComponentMobility.MOVABLE)
            set_prop(sky_comp, "intensity", float(env.get("ambient_intensity", 1.0)))
            if env.get("fog"):
                fog = EAS.spawn_actor_from_class(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0))
                fog_comp = fog.get_editor_property("component")
                set_prop(fog_comp, "fog_density", min(0.05, float(env.get("fog_density", 0.02)) * 2.0))
                color = linear_color(env.get("fog_color", [0.5, 0.6, 0.7, 1]))
                if not set_prop(fog_comp, "fog_inscattering_luminance", color):
                    set_prop(fog_comp, "fog_inscattering_color", color)
            if not any(isinstance(a, unreal.DirectionalLight) for a in self.actor_by_unity_id.values()):
                LOG.warn(STEP, self.name, "La escena no tiene luz direccional; sólo SkyLight.")
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, f"{self.name}: entorno")

    # ------------------------------------------------------------ run
    def build(self) -> None:
        path = self.level["ue_level_path"]
        # Reimportación: se reutiliza el nivel vaciándolo. Borrar y recrear un asset con el mismo
        # nombre en la misma sesión falla en UE 5.8 (el paquete borrado sigue en memoria).
        if unreal.EditorAssetLibrary.does_asset_exist(path) and LES.load_level(path):
            actors = EAS.get_all_level_actors()
            if actors:
                EAS.destroy_actors(actors)
        elif not LES.new_level(path):
            raise RuntimeError(f"No se pudo crear el nivel {path}")
        roots = self.level.get("roots", [])
        with unreal.ScopedSlowTask(len(roots), f"unity2ue: nivel {self.name}") as slow:
            slow.make_dialog(True)
            for node in roots:
                slow.enter_progress_frame(1, node.get("name", ""))
                self.build_node(node, None, True, "")
        # Segunda pasada: propiedades de scripts (ya existen todos los actores para referencias).
        for comp, c, item in self.pending_scripts:
            comps.configure_script(comp, c, item, self.actor_by_unity_id)
        self.environment()
        LES.save_current_level()
        LOG.ok(STEP, self.level.get("unity_path", self.name), f"-> {path} ({len(self.actor_by_unity_id)} ids)")


def run(index: dict | None) -> None:
    if not index:
        return
    _subsystems()
    for entry in index.get("levels", []):
        try:
            level = load_json(entry["file"])
            if level is None:
                LOG.error(STEP, entry["file"], f"No existe en {data_dir()}")
                continue
            LevelBuilder(level).build()
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, entry.get("unity_path", "?"))
