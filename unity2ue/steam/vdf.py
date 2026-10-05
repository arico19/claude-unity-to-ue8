"""Escritura de ficheros KeyValues de Valve (.vdf) para SteamPipe y presencia enriquecida."""

from __future__ import annotations

from typing import Any, Union

# Un nodo es un dict o una lista de pares (clave, valor): la lista permite claves repetidas,
# que SteamPipe usa (varias "FileExclusion" o "FileMapping" en un mismo depot).
Node = Union[dict[str, Any], list[tuple[str, Any]]]


def _quote(value: Any) -> str:
    if isinstance(value, bool):
        value = "1" if value else "0"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"'


def _items(node: Node) -> list[tuple[str, Any]]:
    return list(node.items()) if isinstance(node, dict) else list(node)


def _dump(key: str, node: Node, depth: int, out: list[str]) -> None:
    tab = "\t" * depth
    out.append(f"{tab}{_quote(key)}")
    out.append(f"{tab}{{")
    for k, v in _items(node):
        if isinstance(v, (dict, list)):
            _dump(k, v, depth + 1, out)
        else:
            out.append(f"{tab}\t{_quote(k)}\t\t{_quote(v)}")
    out.append(f"{tab}}}")


def dumps(root_key: str, node: Node) -> str:
    out: list[str] = []
    _dump(root_key, node, 0, out)
    return "\n".join(out) + "\n"
