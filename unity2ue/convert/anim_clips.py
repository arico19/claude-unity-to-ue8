"""Clips de animación de Unity (``.anim``) -> datos muestreados para crear AnimSequences en UE.

Se leen las curvas de transform de cada hueso (``m_RotationCurves`` en cuaterniones,
``m_EulerCurves`` en grados, ``m_PositionCurves``, ``m_ScaleCurves``), se evalúan con
interpolación de Hermite (tangentes de Unity) y se muestrean a una frecuencia fija. Los valores se
guardan en el espacio LOCAL de Unity; el script del editor (``anim_clips.py``) los pasa al
esqueleto de UE, que es quien conoce la escala de unidades y los ejes de la malla importada.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from ..unity.fbx import FbxError, read_fbx_skeleton
from ..unity.yaml_parser import UnityBinaryAssetError, load_unity_file
from .context import ConversionContext

FPS = 30
AXES = ("x", "y", "z", "w")


def _hermite(p0: float, m0: float, p1: float, m1: float, t: float, dt: float) -> float:
    if not all(math.isfinite(v) for v in (m0, m1)):  # tangente "constant" (escalón)
        return p0
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * dt * m0
            + (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * dt * m1)


def _eval(keys: list[dict[str, Any]], time: float, axis: str) -> float:
    """Evalúa una componente de una curva de Unity (lista de keyframes) en ``time``."""
    def comp(v: Any) -> float:
        try:
            return float(v.get(axis, 0.0) if isinstance(v, dict) else v)
        except (TypeError, ValueError):
            return math.inf
    if time <= float(keys[0]["time"]):
        return comp(keys[0]["value"])
    for a, b in zip(keys, keys[1:], strict=False):
        ta, tb = float(a["time"]), float(b["time"])
        if time <= tb:
            dt = max(tb - ta, 1e-6)
            return _hermite(comp(a["value"]), comp(a.get("outSlope", 0)), comp(b["value"]), comp(b.get("inSlope", 0)),
                            (time - ta) / dt, dt)
    return comp(keys[-1]["value"])


def _quat_mul(a: list[float], b: list[float]) -> list[float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def euler_to_quat(x: float, y: float, z: float) -> list[float]:
    """Quaternion.Euler de Unity (grados): rota Z, luego X, luego Y (q = qy * qx * qz)."""
    hx, hy, hz = (math.radians(v) / 2 for v in (x, y, z))
    qx = [math.sin(hx), 0.0, 0.0, math.cos(hx)]
    qy = [0.0, math.sin(hy), 0.0, math.cos(hy)]
    qz = [0.0, 0.0, math.sin(hz), math.cos(hz)]
    return _quat_mul(_quat_mul(qy, qx), qz)


def _normalize(q: list[float]) -> list[float]:
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return [c / n for c in q]


# --------------------------------------------------------------------------- pose de reposo de Unity
def _mat_from_quat(q) -> list[list[float]]:
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def _quat_from_mat(m) -> list[float]:
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s]
    i = max(range(3), key=lambda k: m[k][k])
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1.0 + m[i][i] - m[j][j] - m[k][k]) * 2
    q = [0.0, 0.0, 0.0, 0.0]
    q[i] = 0.25 * s
    q[j] = (m[j][i] + m[i][j]) / s
    q[k] = (m[k][i] + m[i][k]) / s
    q[3] = (m[k][j] - m[j][k]) / s
    return q


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _signed_perms() -> list[list[list[float]]]:
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1.0, -1.0), repeat=3):
            out.append([[signs[r] if c == perm[r] else 0.0 for c in range(3)] for r in range(3)])
    return out


_MODEL_CACHE: dict[str, dict[str, Any] | None] = {}


def _model_skeleton(ctx: ConversionContext, path: str) -> dict[str, Any] | None:
    if path not in _MODEL_CACHE:
        try:
            _MODEL_CACHE[path] = read_fbx_skeleton(ctx.project.root / path)
        except (OSError, FbxError, KeyError, IndexError, ValueError):
            _MODEL_CACHE[path] = None
    return _MODEL_CACHE[path]


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def unity_rest_pose(ctx: ConversionContext, bones: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Pose de reposo de los huesos TAL COMO LA VE UNITY, a partir del FBX del modelo.

    Unity convierte los ejes al importar (p.ej. -90° en X en los FBX de Blender y el espejo de
    mano derecha a izquierda). En vez de replicar sus reglas se deduce la conversión: de las 48
    matrices de permutación con signo, la que mejor lleva las traslaciones del FBX a las del clip.
    """
    wanted = {_norm(b) for b in bones}
    best, best_n = None, 0
    for a in ctx.project.guids.of_category("model"):
        if not a.path.lower().endswith(".fbx"):
            continue
        sk = _model_skeleton(ctx, a.path)
        if not sk:
            continue
        n = len(wanted & {_norm(k) for k in sk["nodes"]})
        if n > best_n:
            best, best_n = (a.path, sk), n
    if best is None or best_n < max(2, len(wanted) // 2):
        return None
    model_path, sk = best
    by_norm = {_norm(k): k for k in sk["nodes"]}
    samples = []
    for bone, tr in bones.items():
        node = sk["nodes"].get(by_norm.get(_norm(bone), ""))
        if node and tr.get("pos") and math.dist(node["t"], (0, 0, 0)) > 1e-4:
            samples.append((node["t"], tr["pos"][0]))
    if not samples:
        return None
    scale = sk["unit_scale"] / 100.0  # unidades del FBX -> metros (Unity)
    best_m, best_err = None, math.inf
    for m in _signed_perms():
        err = sum(math.dist([sum(m[r][c] * t[c] for c in range(3)) * scale for r in range(3)], p) for t, p in samples)
        if err < best_err:
            best_m, best_err = m, err
    mean = best_err / len(samples)
    if mean > 0.05 * max(math.dist(p, (0, 0, 0)) for _, p in samples):
        ctx.warn("animations", f"No se pudo deducir la conversión de ejes de Unity para {model_path}")
        return None
    mt = [list(r) for r in zip(*best_m, strict=True)]
    det = (best_m[0][0] * (best_m[1][1] * best_m[2][2] - best_m[1][2] * best_m[2][1])
           - best_m[0][1] * (best_m[1][0] * best_m[2][2] - best_m[1][2] * best_m[2][0])
           + best_m[0][2] * (best_m[1][0] * best_m[2][1] - best_m[1][1] * best_m[2][0]))
    rest = {}
    for name, node in sk["nodes"].items():
        r = _mul(_mul(best_m, _mat_from_quat(node["r"])), mt)
        # Con espejo (det = -1) la conjugación sigue siendo una rotación válida: M R Mᵀ.
        rest[name] = {"parent": node["parent"], "type": node["type"],
                      "t": [sum(best_m[i][c] * node["t"][c] for c in range(3)) * scale for i in range(3)],
                      "q": _normalize(_quat_from_mat(r)), "s": node["s"]}
    return {"model": model_path, "mirror": det < 0, "fit_error_m": round(mean, 5), "bones": rest}


def convert_anim_clip(ctx: ConversionContext, unity_path: str) -> dict[str, Any] | None:
    try:
        doc = load_unity_file(ctx.project.root / unity_path)
    except UnityBinaryAssetError:
        return None
    clip = next(iter(doc.by_type("AnimationClip")), None)
    if clip is None:
        return None
    settings = clip.get("m_AnimationClipSettings") or {}
    tracks: dict[str, dict[str, Any]] = {}
    end = 0.0

    def track(path: str) -> dict[str, Any]:
        return tracks.setdefault(path, {})

    for key, kind in (("m_RotationCurves", "rot"), ("m_EulerCurves", "euler"),
                      ("m_PositionCurves", "pos"), ("m_ScaleCurves", "scale")):
        for entry in clip.get(key) or []:
            keys = ((entry or {}).get("curve") or {}).get("m_Curve") or []
            path = str((entry or {}).get("path") or "")
            if not keys or not path:
                continue
            track(path)[kind] = keys
            end = max(end, float(keys[-1]["time"]))
    if not tracks:
        ctx.warn(unity_path, "Clip sin curvas de transform (sólo propiedades/eventos): no se convierte")
        return None
    stop = float(settings.get("m_StopTime") or end or 0.0)
    frames = max(2, int(round(stop * FPS)) + 1)
    times = [min(i / FPS, stop) for i in range(frames)]
    bones: dict[str, dict[str, Any]] = {}
    for path, curves in tracks.items():
        out: dict[str, Any] = {"path": path}
        if "rot" in curves:
            out["rot"] = [_normalize([_eval(curves["rot"], t, a) for a in AXES]) for t in times]
        elif "euler" in curves:
            out["rot"] = [euler_to_quat(*(_eval(curves["euler"], t, a) for a in "xyz")) for t in times]
        if "pos" in curves:
            out["pos"] = [[_eval(curves["pos"], t, a) for a in "xyz"] for t in times]
        if "scale" in curves:
            out["scale"] = [[_eval(curves["scale"], t, a) for a in "xyz"] for t in times]
        bones[path.rsplit("/", 1)[-1]] = out
    return {
        "unity_path": unity_path,
        "name": str(clip.get("m_Name") or ctx.naming.imported_name(unity_path)),
        "ue_path": ctx.naming.asset_path(unity_path),
        "fps": FPS,
        "frames": frames,
        "loop": bool(int(settings.get("m_LoopTime", 0) or 0)),
        "bones": bones,
        "unity_rest": unity_rest_pose(ctx, bones),
    }
