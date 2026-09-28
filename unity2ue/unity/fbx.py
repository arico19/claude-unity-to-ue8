"""Lector mínimo de FBX binario: jerarquía de nodos (Model) con su transform local de reposo.

Sólo lo necesario para convertir animaciones ``.anim`` de Unity: nombre, padre, traslación,
rotación (con Pre/PostRotation) y escala locales de cada nodo, y la escala de unidades del fichero.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Any

_MAGIC = b"Kaydara FBX Binary  \x00"


class FbxError(ValueError):
    pass


def _read_props(data: bytes, pos: int, count: int) -> tuple[list[Any], int]:
    props: list[Any] = []
    for _ in range(count):
        t = chr(data[pos])
        pos += 1
        if t in "YCIFDL":
            fmt = {"Y": "<h", "C": "<?", "I": "<i", "F": "<f", "D": "<d", "L": "<q"}[t]
            size = struct.calcsize(fmt)
            props.append(struct.unpack_from(fmt, data, pos)[0])
            pos += size
        elif t in "fdlib":
            length, encoding, clen = struct.unpack_from("<III", data, pos)
            pos += 12
            raw = data[pos:pos + clen]
            pos += clen
            if encoding == 1:
                raw = zlib.decompress(raw)
            fmt = {"f": "f", "d": "d", "l": "q", "i": "i", "b": "?"}[t]
            props.append(list(struct.unpack(f"<{length}{fmt}", raw[:length * struct.calcsize(fmt)])))
        elif t in "SR":
            (length,) = struct.unpack_from("<I", data, pos)
            pos += 4
            raw = data[pos:pos + length]
            pos += length
            props.append(raw.decode("utf-8", "replace") if t == "S" else raw)
        else:
            raise FbxError(f"Tipo de propiedad FBX desconocido: {t!r}")
    return props, pos


def _read_node(data: bytes, pos: int, wide: bool) -> tuple[dict[str, Any] | None, int]:
    if wide:
        end, nprops, _plen = struct.unpack_from("<QQQ", data, pos)
        pos += 24
    else:
        end, nprops, _plen = struct.unpack_from("<III", data, pos)
        pos += 12
    name_len = data[pos]
    pos += 1
    if end == 0:
        return None, pos
    name = data[pos:pos + name_len].decode("ascii", "replace")
    pos += name_len
    props, pos = _read_props(data, pos, nprops)
    children = []
    while pos < end:
        child, pos = _read_node(data, pos, wide)
        if child is None:
            break
        children.append(child)
    return {"name": name, "props": props, "children": children}, end


def _parse(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if not data.startswith(_MAGIC):
        raise FbxError("No es un FBX binario (los FBX ASCII no se admiten)")
    version = struct.unpack_from("<I", data, 23)[0]
    wide = version >= 7500
    pos, nodes = 27, []
    while pos < len(data) - (25 if wide else 13):
        node, pos = _read_node(data, pos, wide)
        if node is None:
            break
        nodes.append(node)
    return nodes


def _child(node: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((c for c in node["children"] if c["name"] == name), None)


def _props70(node: dict[str, Any]) -> dict[str, list[Any]]:
    p70 = _child(node, "Properties70")
    return {p["props"][0]: p["props"][4:] for p in (p70["children"] if p70 else []) if p["name"] == "P"}


def _quat_xyz(deg: list[float]) -> tuple[float, float, float, float]:
    """Rotación FBX (orden XYZ: X, luego Y, luego Z) en grados -> cuaternión (x, y, z, w)."""
    def axis(i: int, a: float) -> tuple[float, float, float, float]:
        s, c = math.sin(math.radians(a) / 2), math.cos(math.radians(a) / 2)
        v = [0.0, 0.0, 0.0]
        v[i] = s
        return (v[0], v[1], v[2], c)
    return quat_mul(quat_mul(axis(2, deg[2]), axis(1, deg[1])), axis(0, deg[0]))


def quat_mul(a, b) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def read_fbx_skeleton(path: str | Path) -> dict[str, Any]:
    """Devuelve ``{"unit_scale": cm por unidad, "nodes": {nombre: {parent, t, r, s, type}}}``.

    ``r`` es la rotación local de reposo como cuaternión FBX (PreRotation * Lcl * PostRotation⁻¹).
    """
    nodes = _parse(Path(path))
    top = {n["name"]: n for n in nodes}
    settings = _props70(_child(top["GlobalSettings"], "Properties70") and top["GlobalSettings"] or {"children": []})
    unit = float((settings.get("UnitScaleFactor") or [1.0])[0])
    models: dict[int, dict[str, Any]] = {}
    for obj in (top.get("Objects") or {"children": []})["children"]:
        if obj["name"] != "Model":
            continue
        oid, full, kind = obj["props"][0], obj["props"][1], obj["props"][2]
        p = _props70(obj)

        def vec(key: str, default: float, p=p) -> list[float]:
            v = p.get(key)
            return [float(x) for x in v[:3]] if v else [default] * 3

        pre, lcl, post = vec("PreRotation", 0.0), vec("Lcl Rotation", 0.0), vec("PostRotation", 0.0)
        post_q = _quat_xyz(post)
        post_inv = (-post_q[0], -post_q[1], -post_q[2], post_q[3])
        models[oid] = {
            "name": str(full).split("\x00")[0],
            "type": kind,
            "t": vec("Lcl Translation", 0.0),
            "r": list(quat_mul(quat_mul(_quat_xyz(pre), _quat_xyz(lcl)), post_inv)),
            "s": vec("Lcl Scaling", 1.0),
            "parent": None,
        }
    for c in (top.get("Connections") or {"children": []})["children"]:
        props = c["props"]
        if c["name"] == "C" and props and props[0] == "OO" and props[1] in models and props[2] in models:
            models[props[1]]["parent"] = models[props[2]]["name"]
    return {"unit_scale": unit, "nodes": {m["name"]: m for m in models.values()}}
