"""Estado compartido durante una conversión: proyecto, nombres, incidencias y referencias."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import ConversionConfig
from ..naming import NamingPolicy, sanitize, to_pascal
from ..unity.builtin import (
    BUILTIN_DEFAULT_GUID,
    BUILTIN_DEFAULT_MATERIAL,
    BUILTIN_EXTRA_GUID,
    BUILTIN_MATERIAL_FILE_IDS,
    BUILTIN_MESHES,
)
from ..unity.project import UnityProject
from ..unity.yaml_parser import ref_file_id, ref_guid

# Nombres reflejados por UE que colisionarían con clases del motor.
RESERVED_UE_NAMES = {
    # Gameplay framework
    "Actor", "Pawn", "Character", "Controller", "PlayerController", "AIController", "GameMode", "GameModeBase",
    "GameState", "GameStateBase", "PlayerState", "HUD", "GameInstance", "SaveGame", "Player", "LocalPlayer",
    "Level", "World", "Engine", "Subsystem", "Info", "Note", "Brush", "Volume", "TriggerBox", "TriggerVolume",
    "Emitter", "Skeleton", "Timeline",
    # Componentes
    "Component", "ActorComponent", "SceneComponent", "PrimitiveComponent", "MovementComponent",
    "CharacterMovementComponent", "CameraComponent", "AudioComponent", "InputComponent", "SplineComponent",
    # Assets
    "Material", "Texture", "Texture2D", "StaticMesh", "SkeletalMesh", "Sound", "SoundWave", "SoundCue", "Font",
    "DataAsset", "PrimaryDataAsset", "Camera", "Light", "Spline",
    # UMG
    "Widget", "UserWidget", "Button", "Image", "Slider", "TextBlock", "CanvasPanel",
    # Tipos base / structs del motor (nombres reflejados sin prefijo)
    "Object", "Class", "Package", "Function", "Property", "Struct", "Enum", "Interface", "Rotator", "Vector",
    "Vector2D", "Vector4", "Transform", "Color", "LinearColor", "Quat", "Box", "Box2D", "Plane", "Matrix", "Guid",
    "Key", "Name", "Text", "String", "DateTime", "Timespan", "HitResult",
}


@dataclass
class Issue:
    severity: str  # "info" | "warning" | "error" | "manual"
    source: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "source": self.source, "message": self.message}


@dataclass
class ScriptInfo:
    guid: str
    unity_path: str
    unity_class: str
    base_class: str = "MonoBehaviour"
    cpp_class: str = ""  # sin prefijo U/A/F
    kind: str = "component"  # component | data_asset | struct | object | library | editor
    header: str = ""
    field_map: dict[str, str] = field(default_factory=dict)


@dataclass
class ConversionContext:
    project: UnityProject
    config: ConversionConfig
    naming: NamingPolicy = field(init=False)
    issues: list[Issue] = field(default_factory=list)
    scripts: dict[str, ScriptInfo] = field(default_factory=dict)
    # guid de modelo -> {"skeletal": bool, "referenced_by": set()}
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    referenced_guids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.naming = NamingPolicy(self.config.content_root)

    # ------------------------------------------------------------------ incidencias
    def warn(self, source: str, message: str) -> None:
        self.issues.append(Issue("warning", source, message))

    def info(self, source: str, message: str) -> None:
        self.issues.append(Issue("info", source, message))

    def error(self, source: str, message: str) -> None:
        self.issues.append(Issue("error", source, message))

    def manual(self, source: str, message: str) -> None:
        """Tarea que requiere intervención (humana o de un agente de Claude)."""
        self.issues.append(Issue("manual", source, message))

    # ------------------------------------------------------------------ scripts
    def script_class_name(self, unity_class: str, kind: str) -> str:
        """Nombre C++ (sin prefijo) que evita choques con clases del motor."""
        name = to_pascal(unity_class)
        if name in RESERVED_UE_NAMES:
            suffix = {"component": "Component", "data_asset": "Data"}.get(kind, "Unity")
            name += suffix
        return name

    # ------------------------------------------------------------------ referencias
    def asset_ref(self, ref: Any, source: str = "") -> dict[str, Any] | None:
        """Resuelve una referencia ``{fileID, guid, type}`` a su destino en UE."""
        file_id = ref_file_id(ref)
        guid = ref_guid(ref)
        if not file_id and not guid:
            return None
        if not guid:
            # Referencia local al mismo fichero (p.ej. otro GameObject de la escena).
            return {"kind": "local", "fileID": file_id}
        if guid == BUILTIN_EXTRA_GUID:
            if file_id in BUILTIN_MESHES:
                name, path, extra = BUILTIN_MESHES[file_id]
                return {"kind": "builtin_mesh", "name": name, "ue_path": path, "extra_scale": list(extra)}
            return {"kind": "builtin", "fileID": file_id, "ue_path": None}
        if guid == BUILTIN_DEFAULT_GUID:
            if file_id in BUILTIN_MATERIAL_FILE_IDS:
                return {"kind": "builtin_material", "fileID": file_id, "ue_path": BUILTIN_DEFAULT_MATERIAL}
            return {"kind": "builtin", "fileID": file_id, "ue_path": None}

        info = self.project.guids.get(guid)
        if info is None:
            self.warn(source, f"Referencia a GUID desconocido {guid} (asset de paquete o eliminado)")
            return {"kind": "missing", "guid": guid, "fileID": file_id}
        self.referenced_guids.add(guid)
        out: dict[str, Any] = {
            "kind": info.category,
            "guid": guid,
            "fileID": file_id,
            "unity_path": info.path,
        }
        n = self.naming
        if info.category == "material":
            out["ue_path"] = n.object_path(n.material_path(info.path))
        elif info.category == "texture":
            out["ue_path"] = n.object_path(n.asset_path(info.path))
        elif info.category == "model":
            out["ue_folder"] = n.model_folder(info.path)
            sub = info.sub_object_names.get(file_id)
            if sub:
                out["sub_name"] = sanitize(sub)
            out["model_name"] = n.imported_name(info.path)
        elif info.category == "audio":
            out["ue_path"] = n.object_path(n.asset_path(info.path))
        elif info.category == "prefab":
            bp = n.blueprint_path(info.path)
            out["ue_path"] = n.object_path(bp)
            out["ue_class_path"] = n.object_path(bp) + "_C"
        elif info.category in ("animator", "animation"):
            out["ue_path"] = n.object_path(n.asset_path(info.path))
        elif info.category == "asset":
            # Instancia de ScriptableObject -> DataAsset (convert/data_assets.py)
            out["ue_path"] = n.object_path(n.asset_path(info.path, prefix="DA_"))
        elif info.category == "script":
            script = self.scripts.get(guid)
            if script:
                out["cpp_class"] = script.cpp_class
        else:
            out["ue_path"] = n.object_path(n.asset_path(info.path))
        return out

    def mark_model(self, ref: dict[str, Any] | None, skeletal: bool, source: str) -> None:
        if not ref or ref.get("kind") != "model":
            return
        entry = self.models.setdefault(ref["guid"], {"skeletal": False, "referenced_by": set()})
        entry["skeletal"] = entry["skeletal"] or skeletal
        entry["referenced_by"].add(source)
