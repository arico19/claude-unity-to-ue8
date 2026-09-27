"""Índice de assets del proyecto Unity a partir de los ficheros ``.meta``."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from .yaml_parser import load_yaml

_GUID_LINE = re.compile(r"^guid:\s*([0-9a-fA-F]{32})", re.M)

CATEGORIES: dict[str, tuple[str, ...]] = {
    "scene": (".unity",),
    "prefab": (".prefab",),
    "material": (".mat",),
    "script": (".cs",),
    "shader": (".shader", ".shadergraph", ".hlsl", ".cginc", ".compute", ".shadersubgraph"),
    "texture": (".png", ".jpg", ".jpeg", ".tga", ".psd", ".tif", ".tiff", ".exr", ".hdr", ".bmp", ".gif"),
    "model": (".fbx", ".obj", ".dae", ".3ds", ".blend", ".max", ".ma", ".mb", ".gltf", ".glb"),
    "audio": (".wav", ".mp3", ".ogg", ".aif", ".aiff", ".flac"),
    "animation": (".anim",),
    "animator": (".controller", ".overridecontroller"),
    "avatar_mask": (".mask",),
    "physics_material": (".physicmaterial", ".physicsmaterial"),
    "font": (".ttf", ".otf", ".fontsettings"),
    "video": (".mp4", ".mov", ".webm", ".avi", ".m4v"),
    "input_actions": (".inputactions",),
    "assembly_definition": (".asmdef", ".asmref"),
    "ui_toolkit": (".uxml", ".uss", ".tss"),
    "render_texture": (".rendertexture",),
    "cubemap": (".cubemap",),
    "sprite_atlas": (".spriteatlas", ".spriteatlasv2"),
    "timeline": (".playable",),
    "lighting": (".lighting",),
    "terrain_layer": (".terrainlayer",),
    "asset": (".asset",),
    "text": (".txt", ".json", ".xml", ".csv", ".bytes", ".md"),
    "plugin": (".dll", ".so", ".bundle", ".aar", ".jar", ".a"),
}
_EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}


def categorize(path: str) -> str:
    return _EXT_TO_CATEGORY.get(os.path.splitext(path)[1].lower(), "other")


@dataclass
class AssetInfo:
    guid: str
    path: str  # relativo a la raíz del proyecto, con '/', p.ej. "Assets/Art/Rock.fbx"
    abs_path: Path
    meta_path: Path
    category: str
    _meta: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def meta(self) -> dict[str, Any]:
        if self._meta is None:
            try:
                self._meta = load_yaml(self.meta_path.read_text("utf-8", errors="replace")) or {}
            except Exception:  # noqa: BLE001 - .meta corrupto
                self._meta = {}
        return self._meta

    @property
    def importer_type(self) -> str | None:
        for key in self.meta:
            if key.endswith("Importer"):
                return key
        return None

    @property
    def importer(self) -> dict[str, Any]:
        t = self.importer_type
        return (self.meta.get(t) or {}) if t else {}

    @cached_property
    def sub_objects(self) -> list[tuple[int, int, str]]:
        """(classID, fileID interno, nombre) de los sub-objetos de un FBX (mallas, materiales, clips)."""
        out: list[tuple[int, int, str]] = []
        imp = self.importer
        for entry in imp.get("internalIDToNameTable") or []:
            if not isinstance(entry, dict):
                continue
            first = entry.get("first") or {}
            for cls, fid in first.items():
                try:
                    out.append((int(cls), int(fid), str(entry.get("second"))))
                except (TypeError, ValueError):
                    pass
        legacy = imp.get("fileIDToRecycleName") or {}
        if isinstance(legacy, dict):
            for fid, name in legacy.items():
                try:
                    # En el formato antiguo el classID va codificado: fileID = classID * 100000 + n
                    out.append((int(fid) // 100000, int(fid), str(name)))
                except (TypeError, ValueError):
                    pass
        return out

    @property
    def sub_object_names(self) -> dict[int, str]:
        """fileID interno -> nombre."""
        return {fid: name for _cls, fid, name in self.sub_objects}

    @property
    def mesh_count(self) -> int:
        return sum(1 for cls, _fid, _name in self.sub_objects if cls == 43)


class GuidDatabase:
    """Mapa GUID -> AssetInfo construido leyendo los .meta de Assets/ y Packages/."""

    def __init__(self, project_root: str | Path) -> None:
        self.root = Path(project_root)
        self.by_guid: dict[str, AssetInfo] = {}
        self.by_path: dict[str, AssetInfo] = {}

    def scan(self, folders: tuple[str, ...] = ("Assets", "Packages")) -> "GuidDatabase":
        for folder in folders:
            base = self.root / folder
            if not base.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                # Carpetas ocultas o terminadas en ~ son ignoradas por Unity.
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.endswith("~")]
                for fn in filenames:
                    if not fn.endswith(".meta"):
                        continue
                    meta_path = Path(dirpath) / fn
                    asset_path = meta_path.with_suffix("")
                    if not asset_path.exists() or asset_path.is_dir():
                        continue
                    guid = self._read_guid(meta_path)
                    if not guid:
                        continue
                    rel = asset_path.relative_to(self.root).as_posix()
                    info = AssetInfo(guid, rel, asset_path, meta_path, categorize(rel))
                    self.by_guid[guid] = info
                    self.by_path[rel] = info
        return self

    @staticmethod
    def _read_guid(meta_path: Path) -> str | None:
        try:
            with meta_path.open("r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(512)
        except OSError:
            return None
        m = _GUID_LINE.search(head)
        return m.group(1).lower() if m else None

    def get(self, guid: str | None) -> AssetInfo | None:
        return self.by_guid.get(guid.lower()) if guid else None

    def of_category(self, category: str) -> list[AssetInfo]:
        return sorted((a for a in self.by_guid.values() if a.category == category), key=lambda a: a.path)

    def __len__(self) -> int:
        return len(self.by_guid)
