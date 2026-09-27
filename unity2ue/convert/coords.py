"""Conversión de espacio de coordenadas Unity -> Unreal Engine.

Unity:  mano izquierda, Y arriba, Z adelante, X derecha, metros.
Unreal: mano izquierda, Z arriba, X adelante, Y derecha, centímetros.

El cambio de base es una permutación cíclica de ejes (determinante +1), por lo que la
quiralidad se conserva y los cuaterniones se transforman igual que los vectores:

    UE.X = Unity.Z     UE.Y = Unity.X     UE.Z = Unity.Y
"""

from __future__ import annotations

import math
from typing import Any, Sequence

METERS_TO_CM = 100.0

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def vec_from_unity(d: Any, default: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    if isinstance(d, dict):
        return (_f(d.get("x"), default[0]), _f(d.get("y"), default[1]), _f(d.get("z"), default[2]))
    if isinstance(d, (list, tuple)) and len(d) >= 3:
        return (_f(d[0]), _f(d[1]), _f(d[2]))
    return default


def quat_from_unity(d: Any) -> Quat:
    if isinstance(d, dict):
        return (_f(d.get("x")), _f(d.get("y")), _f(d.get("z")), _f(d.get("w"), 1.0))
    if isinstance(d, (list, tuple)) and len(d) >= 4:
        return (_f(d[0]), _f(d[1]), _f(d[2]), _f(d[3]))
    return (0.0, 0.0, 0.0, 1.0)


def axis_swap(v: Sequence[float]) -> Vec3:
    """Vector Unity (x, y, z) -> ejes UE (z, x, y), sin cambio de unidades."""
    return (float(v[2]), float(v[0]), float(v[1]))


def location_to_ue(v: Sequence[float], scale: float = METERS_TO_CM) -> Vec3:
    x, y, z = axis_swap(v)
    return (round(x * scale, 5), round(y * scale, 5), round(z * scale, 5))


def scale_to_ue(v: Sequence[float]) -> Vec3:
    x, y, z = axis_swap(v)
    return (round(x, 6), round(y, 6), round(z, 6))


def quat_to_ue(q: Sequence[float]) -> Quat:
    x, y, z, w = (float(c) for c in q)
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return (round(z / n, 8), round(x / n, 8), round(y / n, 8), round(w / n, 8))


def _normalize_axis(angle: float) -> float:
    angle = math.fmod(angle, 360.0)
    if angle > 180.0:
        angle -= 360.0
    elif angle <= -180.0:
        angle += 360.0
    return angle


def ue_quat_to_rotator(q: Sequence[float]) -> Vec3:
    """Replica ``FQuat::Rotator()`` de UE. Devuelve (Pitch, Yaw, Roll) en grados."""
    x, y, z, w = (float(c) for c in q)
    singularity = z * x - w * y
    yaw_y = 2.0 * (w * z + x * y)
    yaw_x = 1.0 - 2.0 * (y * y + z * z)
    threshold = 0.4999995
    rad2deg = 180.0 / math.pi
    yaw = math.atan2(yaw_y, yaw_x) * rad2deg
    if singularity < -threshold:
        pitch = -90.0
        roll = _normalize_axis(-yaw - 2.0 * math.atan2(x, w) * rad2deg)
    elif singularity > threshold:
        pitch = 90.0
        roll = _normalize_axis(yaw - 2.0 * math.atan2(x, w) * rad2deg)
    else:
        pitch = math.asin(2.0 * singularity) * rad2deg
        roll = math.atan2(-2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)) * rad2deg
    return (round(pitch, 5) + 0.0, round(yaw, 5) + 0.0, round(roll, 5) + 0.0)


def transform_to_ue(position: Any, rotation: Any, scale: Any) -> dict[str, list[float]]:
    """Convierte un Transform local de Unity (dicts x/y/z[/w]) a formato UE."""
    q = quat_to_ue(quat_from_unity(rotation))
    return {
        "location": list(location_to_ue(vec_from_unity(position))),
        "rotation_quat": list(q),
        "rotation": list(ue_quat_to_rotator(q)),  # Pitch, Yaw, Roll
        "scale": list(scale_to_ue(vec_from_unity(scale, (1.0, 1.0, 1.0)))),
    }


def color_to_linear(c: Any) -> list[float]:
    """Color Unity {r,g,b,a} -> [r,g,b,a]. Unity guarda colores en espacio gamma."""
    if not isinstance(c, dict):
        return [1.0, 1.0, 1.0, 1.0]
    return [_f(c.get("r"), 1.0), _f(c.get("g"), 1.0), _f(c.get("b"), 1.0), _f(c.get("a"), 1.0)]


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def vertical_to_horizontal_fov(vfov_deg: float, aspect: float = 16.0 / 9.0) -> float:
    """Unity usa FOV vertical; UE usa FOV horizontal."""
    v = math.radians(vfov_deg)
    return round(math.degrees(2.0 * math.atan(math.tan(v / 2.0) * aspect)), 4)
