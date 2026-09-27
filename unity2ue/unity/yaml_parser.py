"""Parser del formato YAML serializado de Unity (escenas, prefabs, materiales, .asset).

Unity escribe ficheros YAML 1.1 con varios documentos, cada uno precedido por una
cabecera del tipo ``--- !u!<classID> &<fileID> [stripped]``. PyYAML no entiende esas
etiquetas personalizadas, así que partimos el texto por cabeceras y parseamos cada
cuerpo por separado con un loader que desactiva las conversiones implícitas
problemáticas (``yes``/``no``/``on`` -> bool, fechas, GUIDs numéricos -> int).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

try:  # El loader en C es ~10x más rápido en proyectos grandes.
    _BaseLoader = yaml.CSafeLoader  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover
    _BaseLoader = yaml.SafeLoader


class UnityLoader(_BaseLoader):  # type: ignore[misc, valid-type]
    """SafeLoader sin resolución implícita de bool ni timestamp."""


UnityLoader.yaml_implicit_resolvers = {
    key: [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag not in ("tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp")
    ]
    for key, resolvers in _BaseLoader.yaml_implicit_resolvers.items()
}

DOC_HEADER = re.compile(r"^--- !u!(\d+) &(-?\d+)( stripped)?[^\n]*$", re.M)
# Los GUID pueden ser sólo dígitos y YAML los convertiría a int (u octal).
_GUID_VALUE = re.compile(r"(guid: )([0-9a-fA-F]{32})")


class UnityBinaryAssetError(ValueError):
    """El fichero está serializado en binario (Asset Serialization != Force Text)."""


@dataclass
class UnityObject:
    class_id: int
    file_id: int
    type_name: str
    data: dict[str, Any]
    stripped: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass
class UnityDocument:
    path: Path | None
    objects: dict[int, UnityObject] = field(default_factory=dict)

    def __iter__(self) -> Iterator[UnityObject]:
        return iter(self.objects.values())

    def get(self, file_id: int | None) -> UnityObject | None:
        if not file_id:
            return None
        return self.objects.get(int(file_id))

    def by_class(self, *class_ids: int) -> list[UnityObject]:
        return [o for o in self.objects.values() if o.class_id in class_ids]

    def by_type(self, *type_names: str) -> list[UnityObject]:
        return [o for o in self.objects.values() if o.type_name in type_names]


def _prepare(text: str) -> str:
    return _GUID_VALUE.sub(r'\1"\2"', text)


def load_yaml(text: str) -> Any:
    """Parsea un documento YAML simple (p.ej. un .meta) con el loader de Unity."""
    return yaml.load(_prepare(text), Loader=UnityLoader)  # noqa: S506 - loader seguro


def parse_unity_yaml(text: str, path: Path | None = None) -> UnityDocument:
    stripped_text = text.lstrip("﻿")
    if not stripped_text.startswith("%YAML") and not stripped_text.startswith("---"):
        raise UnityBinaryAssetError(
            f"{path or 'El fichero'} no es YAML de texto. Activa en Unity "
            "Project Settings > Editor > Asset Serialization = Force Text."
        )
    doc = UnityDocument(path=path)
    headers = list(DOC_HEADER.finditer(stripped_text))
    for i, match in enumerate(headers):
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(stripped_text)
        body = stripped_text[start:end]
        class_id = int(match.group(1))
        file_id = int(match.group(2))
        try:
            parsed = load_yaml(body) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - datos corruptos
            parsed = {"__parse_error__": str(exc)}
        if isinstance(parsed, dict) and len(parsed) == 1:
            type_name, data = next(iter(parsed.items()))
        else:
            type_name, data = "Unknown", parsed if isinstance(parsed, dict) else {}
        doc.objects[file_id] = UnityObject(
            class_id=class_id,
            file_id=file_id,
            type_name=str(type_name),
            data=data if isinstance(data, dict) else {},
            stripped=bool(match.group(3)),
        )
    return doc


def load_unity_file(path: str | Path) -> UnityDocument:
    path = Path(path)
    raw = path.read_bytes()
    if b"\x00" in raw[:1024]:
        raise UnityBinaryAssetError(
            f"{path} está en formato binario. Usa Asset Serialization = Force Text."
        )
    return parse_unity_yaml(raw.decode("utf-8", errors="replace"), path)


def ref_file_id(ref: Any) -> int:
    """Devuelve el fileID de una referencia ``{fileID: X, guid: Y, type: Z}``."""
    if isinstance(ref, dict):
        try:
            return int(ref.get("fileID") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def ref_guid(ref: Any) -> str | None:
    if isinstance(ref, dict) and ref.get("guid"):
        return str(ref["guid"]).lower()
    return None
