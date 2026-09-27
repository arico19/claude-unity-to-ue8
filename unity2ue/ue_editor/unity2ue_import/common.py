"""Utilidades compartidas por los scripts del editor (se ejecutan DENTRO de Unreal Editor).

Estos módulos se copian a ``<ProyectoUE>/Content/Python/unity2ue_import`` y usan la API
Python del editor (plugin *Python Editor Script Plugin*). Leen los JSON generados por
``unity2ue convert`` en ``<ProyectoUE>/Unity2UE``.
"""

from __future__ import annotations

import json
import math
import os
import time
import traceback

import unreal

ASSET_TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary


def project_dir() -> str:
    return unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())


def data_dir() -> str:
    return os.path.join(project_dir(), "Unity2UE")


def load_json(name: str, default=None):
    path = os.path.join(data_dir(), name)
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


SETTINGS = None


def settings() -> dict:
    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_json("settings.json", {}) or {}
    return SETTINGS


def module_name() -> str:
    return settings().get("module", "ConvertedProject")


def content_root() -> str:
    return settings().get("content_root", "/Game/Unity")


# --------------------------------------------------------------------------- log
class ImportLog:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.started = time.time()

    def add(self, step: str, item: str, status: str, message: str = "") -> None:
        self.entries.append({"step": step, "item": item, "status": status, "message": message})
        text = f"[unity2ue][{step}] {status.upper()} {item} {message}".rstrip()
        if status == "error":
            unreal.log_error(text)
        elif status == "warning":
            unreal.log_warning(text)
        else:
            unreal.log(text)

    def ok(self, step: str, item: str, message: str = "") -> None:
        self.add(step, item, "ok", message)

    def warn(self, step: str, item: str, message: str) -> None:
        self.add(step, item, "warning", message)

    def error(self, step: str, item: str, message: str) -> None:
        self.add(step, item, "error", message)

    def exception(self, step: str, item: str) -> None:
        self.add(step, item, "error", traceback.format_exc(limit=4))

    def save(self) -> str:
        path = os.path.join(data_dir(), "import_log.json")
        summary: dict[str, int] = {}
        for e in self.entries:
            summary[e["status"]] = summary.get(e["status"], 0) + 1
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"duration_s": round(time.time() - self.started, 1), "summary": summary,
                       "entries": self.entries}, fh, indent=2, ensure_ascii=False)
        return path


LOG = ImportLog()


# --------------------------------------------------------------------------- assets
def object_path(package_path: str) -> str:
    name = package_path.rsplit("/", 1)[-1]
    return package_path if "." in name else f"{package_path}.{name}"


def load(path: str | None):
    if not path:
        return None
    try:
        if EAL.does_asset_exist(path.split(".")[0]):
            return EAL.load_asset(path)
    except Exception:  # noqa: BLE001
        pass
    return None


def ensure_dir(path: str) -> None:
    if not EAL.does_directory_exist(path):
        EAL.make_directory(path)


def create_or_load(name: str, folder: str, asset_class, factory):
    ensure_dir(folder)
    existing = load(f"{folder}/{name}")
    if existing is not None:
        return existing, False
    return ASSET_TOOLS.create_asset(name, folder, asset_class, factory), True


def save(asset) -> None:
    try:
        EAL.save_loaded_asset(asset, only_if_is_dirty=False)
    except TypeError:
        EAL.save_loaded_asset(asset)


# Cache de mallas de modelos: carpeta -> lista de assets
_MODEL_CACHE: dict[str, list] = {}


def resolve_mesh(ref: dict | None, skeletal: bool = False):
    """Resuelve una referencia de malla del JSON a un StaticMesh/SkeletalMesh cargado."""
    if not ref:
        return None
    kind = ref.get("kind")
    if kind == "builtin_mesh":
        return load(ref.get("ue_path"))
    if kind != "model":
        return None
    folder = ref.get("ue_folder")
    if folder not in _MODEL_CACHE:
        assets = []
        if folder and EAL.does_directory_exist(folder):
            for p in EAL.list_assets(folder, recursive=True, include_folder=False):
                a = load(p)
                if isinstance(a, (unreal.StaticMesh, unreal.SkeletalMesh)):
                    assets.append(a)
        _MODEL_CACHE[folder] = assets
    wanted_cls = unreal.SkeletalMesh if skeletal else unreal.StaticMesh
    candidates = [a for a in _MODEL_CACHE[folder] if isinstance(a, wanted_cls)] or _MODEL_CACHE[folder]
    sub = (ref.get("sub_name") or "").lower()
    if sub:
        for a in candidates:
            if a.get_name().lower() == sub:
                return a
        for a in candidates:
            if sub in a.get_name().lower():
                return a
    return candidates[0] if candidates else None


def resolve_asset(ref: dict | None):
    if not ref:
        return None
    if ref.get("kind") in ("builtin_mesh", "model"):
        return resolve_mesh(ref)
    return load(ref.get("ue_path"))


def resolve_class(path: str | None):
    """Carga una clase de Blueprint (``..._C``) o nativa (``/Script/Mod.Clase``)."""
    if not path:
        return None
    try:
        if path.startswith("/Script/"):
            return unreal.load_class(None, path)
        bp_path = path[:-2] if path.endswith("_C") else path
        return EAL.load_blueprint_class(bp_path.split(".")[0])
    except Exception:  # noqa: BLE001
        return None


def script_class(cpp_class: str | None):
    if not cpp_class:
        return None
    return resolve_class(f"/Script/{module_name()}.{cpp_class}")


# --------------------------------------------------------------------------- math
def vec(v) -> unreal.Vector:
    return unreal.Vector(float(v[0]), float(v[1]), float(v[2]))


def rot_from_quat(q) -> unreal.Rotator:
    return unreal.Quat(float(q[0]), float(q[1]), float(q[2]), float(q[3])).rotator()


def rot(pyr) -> unreal.Rotator:
    """(Pitch, Yaw, Roll) -> unreal.Rotator (el constructor Python es roll, pitch, yaw)."""
    return unreal.Rotator(roll=float(pyr[2]), pitch=float(pyr[0]), yaw=float(pyr[1]))


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else math.pow((c + 0.055) / 1.055, 2.4)


def linear_color(rgba, gamma_to_linear: bool = True) -> unreal.LinearColor:
    r, g, b = (float(x) for x in rgba[:3])
    a = float(rgba[3]) if len(rgba) > 3 else 1.0
    if gamma_to_linear:
        r, g, b = (srgb_to_linear(max(0.0, x)) if x <= 1.0 else x for x in (r, g, b))
    return unreal.LinearColor(r, g, b, a)


def set_prop(obj, name: str, value, step: str = "", item: str = "") -> bool:
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:  # noqa: BLE001
        if step:
            LOG.warn(step, item, f"No se pudo asignar {name}: {exc}")
        return False


def enum_value(enum_cls, *names):
    for n in names:
        if hasattr(enum_cls, n):
            return getattr(enum_cls, n)
    return None
