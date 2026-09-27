"""Configuración de la conversión (sobrescribible con un JSON vía ``--config``)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class ConversionConfig:
    project_name: str = "ConvertedProject"
    engine_version: str = "5.8"
    content_root: str = "/Game/Unity"
    # Aspecto usado para convertir FOV vertical (Unity) -> horizontal (UE).
    camera_aspect: float = 16.0 / 9.0
    # Factores de intensidad de luz (Unity built-in/URP no usa unidades físicas).
    light_intensity: dict[str, float] = field(
        default_factory=lambda: {
            "directional_lux_per_unit": 10.0,
            "point_candela_per_unit": 8.0,
            "spot_candela_per_unit": 8.0,
            "area_candela_per_unit": 8.0,
        }
    )
    # Copiar también assets que ninguna escena/prefab referencia.
    include_unreferenced_assets: bool = True
    # Carpetas (prefijo de ruta Unity) a excluir del proceso.
    exclude_paths: list[str] = field(default_factory=lambda: ["Assets/Plugins/", "Assets/TextMesh Pro/Examples"])
    # Generar esqueletos C++ a partir de los scripts C#.
    generate_cpp: bool = True
    # Escenas a convertir (vacío = todas).
    scenes: list[str] = field(default_factory=list)

    @property
    def module_name(self) -> str:
        from .naming import to_pascal

        return to_pascal(self.project_name)

    @classmethod
    def load(cls, path: str | Path | None, **overrides: Any) -> "ConversionConfig":
        data: dict[str, Any] = {}
        if path:
            data = json.loads(Path(path).read_text("utf-8"))
        data.update({k: v for k, v in overrides.items() if v is not None})
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_excluded(self, unity_path: str) -> bool:
        return any(unity_path.startswith(p) for p in self.exclude_paths)
