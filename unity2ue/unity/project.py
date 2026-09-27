"""Modelo de alto nivel de un proyecto Unity: versión, pipeline, ajustes y assets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from .assets import GuidDatabase
from .yaml_parser import UnityBinaryAssetError, UnityDocument, load_unity_file


class NotAUnityProjectError(ValueError):
    pass


@dataclass
class UnityProject:
    root: Path
    guids: GuidDatabase = field(init=False)
    _doc_cache: dict[str, UnityDocument] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        if not (self.root / "Assets").is_dir():
            raise NotAUnityProjectError(f"{self.root} no contiene una carpeta Assets/")
        self.guids = GuidDatabase(self.root).scan()

    # ------------------------------------------------------------------ ajustes
    @cached_property
    def unity_version(self) -> str | None:
        f = self.root / "ProjectSettings" / "ProjectVersion.txt"
        if f.exists():
            m = re.search(r"m_EditorVersion:\s*(\S+)", f.read_text("utf-8", errors="replace"))
            if m:
                return m.group(1)
        return None

    @cached_property
    def package_manifest(self) -> dict[str, Any]:
        f = self.root / "Packages" / "manifest.json"
        if f.exists():
            try:
                return json.loads(f.read_text("utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    @cached_property
    def render_pipeline(self) -> str:
        deps = self.package_manifest.get("dependencies", {})
        if "com.unity.render-pipelines.high-definition" in deps:
            return "HDRP"
        if "com.unity.render-pipelines.universal" in deps:
            return "URP"
        return "Built-in"

    @cached_property
    def packages(self) -> list[str]:
        return sorted(self.package_manifest.get("dependencies", {}).keys())

    def settings_asset(self, name: str) -> dict[str, Any]:
        """Lee ``ProjectSettings/<name>.asset`` y devuelve el primer objeto."""
        f = self.root / "ProjectSettings" / f"{name}.asset"
        if not f.exists():
            return {}
        try:
            doc = load_unity_file(f)
        except UnityBinaryAssetError:
            return {}
        for obj in doc:
            return obj.data
        return {}

    @cached_property
    def serialization_mode(self) -> int | None:
        data = self.settings_asset("EditorSettings")
        mode = data.get("m_SerializationMode")
        return int(mode) if mode is not None else None

    @cached_property
    def tags_and_layers(self) -> dict[str, Any]:
        data = self.settings_asset("TagManager")
        layers = [str(x) if x else "" for x in (data.get("layers") or [])]
        return {
            "tags": [str(t) for t in (data.get("tags") or []) if t],
            "layers": {i: n for i, n in enumerate(layers) if n},
            "sorting_layers": [s.get("name") for s in data.get("m_SortingLayers") or [] if isinstance(s, dict)],
        }

    @cached_property
    def build_scenes(self) -> list[dict[str, Any]]:
        data = self.settings_asset("EditorBuildSettings")
        scenes = []
        for s in data.get("m_Scenes") or []:
            if isinstance(s, dict) and s.get("path"):
                scenes.append({"path": str(s["path"]), "enabled": bool(s.get("enabled", 1)), "guid": s.get("guid")})
        return scenes

    @cached_property
    def physics(self) -> dict[str, Any]:
        data = self.settings_asset("DynamicsManager")
        g = data.get("m_Gravity") or {"x": 0, "y": -9.81, "z": 0}
        return {
            "gravity": [float(g.get("x", 0)), float(g.get("y", -9.81)), float(g.get("z", 0))],
            "default_contact_offset": data.get("m_DefaultContactOffset"),
            "bounce_threshold": data.get("m_BounceThreshold"),
        }

    @cached_property
    def input_axes(self) -> list[dict[str, Any]]:
        data = self.settings_asset("InputManager")
        axes = []
        for a in data.get("m_Axes") or []:
            if not isinstance(a, dict):
                continue
            axes.append(
                {
                    "name": str(a.get("m_Name", "")),
                    "positive": str(a.get("positiveButton") or ""),
                    "negative": str(a.get("negativeButton") or ""),
                    "alt_positive": str(a.get("altPositiveButton") or ""),
                    "alt_negative": str(a.get("altNegativeButton") or ""),
                    "type": int(a.get("type", 0) or 0),  # 0 tecla/botón, 1 ratón, 2 joystick
                    "axis": int(a.get("axis", 0) or 0),
                    "invert": bool(a.get("invert", 0)),
                }
            )
        return axes

    @cached_property
    def player_settings(self) -> dict[str, Any]:
        data = self.settings_asset("ProjectSettings")
        return {
            "company_name": data.get("companyName"),
            "product_name": data.get("productName"),
            "bundle_version": data.get("bundleVersion"),
        }

    # ------------------------------------------------------------------ documentos
    def load(self, rel_path: str) -> UnityDocument:
        if rel_path not in self._doc_cache:
            self._doc_cache[rel_path] = load_unity_file(self.root / rel_path)
        return self._doc_cache[rel_path]

    def load_guid(self, guid: str | None) -> UnityDocument | None:
        info = self.guids.get(guid)
        if info is None:
            return None
        return self.load(info.path)
