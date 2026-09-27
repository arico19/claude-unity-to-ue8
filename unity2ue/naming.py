"""Política de nombres y rutas: Unity ``Assets/...`` -> Unreal ``/Game/...``."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_INVALID = re.compile(r"[^A-Za-z0-9_]")
_MULTI_UNDERSCORE = re.compile(r"_+")


def sanitize(name: str, fallback: str = "Unnamed") -> str:
    """Nombre válido para un asset/objeto de UE (sin espacios, puntos ni símbolos)."""
    cleaned = _MULTI_UNDERSCORE.sub("_", _INVALID.sub("_", name)).strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def to_pascal(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    out = "".join(p[:1].upper() + p[1:] for p in parts if p)
    if not out:
        return "Unnamed"
    if out[0].isdigit():
        out = "_" + out
    return out


def to_snake(name: str) -> str:
    """``MoveSpeed`` -> ``move_speed`` (nombre de propiedad en la API Python de UE)."""
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")


def cpp_property_name(unity_field: str) -> str:
    """``m_moveSpeed`` / ``_speed`` / ``speed`` -> ``MoveSpeed`` / ``Speed``."""
    name = re.sub(r"^(m_|_+)", "", unity_field)
    if unity_field.startswith("b") and len(unity_field) > 1 and unity_field[1].isupper():
        return unity_field  # ya es convención UE (bFlag)
    return to_pascal(name) if name else to_pascal(unity_field)


class NamingPolicy:
    """Calcula la ruta de destino en UE para cada asset de Unity."""

    def __init__(self, content_root: str = "/Game/Unity") -> None:
        self.content_root = content_root.rstrip("/")

    def folder_for(self, unity_path: str) -> str:
        p = PurePosixPath(unity_path)
        parts = list(p.parent.parts)
        if parts and parts[0] in ("Assets", "Packages"):
            parts = parts[1:]
        parts = [sanitize(x) for x in parts]
        return "/".join([self.content_root, *parts]) if parts else self.content_root

    def imported_name(self, unity_path: str) -> str:
        return sanitize(PurePosixPath(unity_path).stem)

    def asset_path(self, unity_path: str, prefix: str = "", name: str | None = None) -> str:
        base = name or self.imported_name(unity_path)
        asset = f"{prefix}{base}" if prefix and not base.startswith(prefix) else base
        return f"{self.folder_for(unity_path)}/{asset}"

    def model_folder(self, unity_path: str) -> str:
        """Carpeta propia por modelo, para localizar sub-mallas tras importar."""
        return f"{self.folder_for(unity_path)}/{self.imported_name(unity_path)}"

    def material_path(self, unity_path: str) -> str:
        return self.asset_path(unity_path, prefix="MI_")

    def blueprint_path(self, unity_path: str) -> str:
        return self.asset_path(unity_path, prefix="BP_")

    def level_path(self, unity_path: str) -> str:
        return f"{self.content_root}/Maps/{self.imported_name(unity_path)}"

    @staticmethod
    def object_path(package_path: str) -> str:
        """``/Game/X/Y`` -> ``/Game/X/Y.Y`` (ruta de objeto completa)."""
        if "." in package_path.rsplit("/", 1)[-1]:
            return package_path
        return f"{package_path}.{package_path.rsplit('/', 1)[-1]}"
