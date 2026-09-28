"""Retarget de clips de Unity a un esqueleto de UE usando las poses de reposo de ambos.

Cada motor orienta los ejes locales de los huesos a su manera al importar el FBX, así que las
rotaciones locales de Unity no se pueden copiar tal cual. Se trabaja en espacio de mundo:

    mundo_UE(hueso, t) = G · mundo_Unity(hueso, t) · (G · reposo_Unity(hueso))⁻¹ · reposo_UE(hueso)

donde G (rotación + escala + traslación) lleva el espacio del modelo en Unity al espacio de
componente de UE y se ajusta con las posiciones de reposo de los huesos comunes. Después se pasa
a local con la jerarquía de UE. Matemáticas en Python puro (tuplas); ``unreal`` sólo para leer la
pose de referencia y devolver las claves.
"""

from __future__ import annotations

import unreal


def norm(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


# --------------------------------------------------------------------------- cuaterniones y transforms
def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qinv(q):
    return (-q[0], -q[1], -q[2], q[3])


def qrot(q, v):
    x, y, z, _ = qmul(qmul(q, (v[0], v[1], v[2], 0.0)), qinv(q))
    return (x, y, z)


def compose(parent, local):
    """Mundo de un hijo a partir del mundo del padre y su transform local (pos, rot, escala)."""
    pp, pq, ps = parent
    lp, lq, ls = local
    rp = qrot(pq, (lp[0] * ps[0], lp[1] * ps[1], lp[2] * ps[2]))
    return ((pp[0] + rp[0], pp[1] + rp[1], pp[2] + rp[2]), qmul(pq, lq), (ps[0] * ls[0], ps[1] * ls[1], ps[2] * ls[2]))


def relative(parent, world):
    pp, pq, ps = parent
    wp, wq, ws = world
    d = qrot(qinv(pq), (wp[0] - pp[0], wp[1] - pp[1], wp[2] - pp[2]))
    return ((d[0] / ps[0], d[1] / ps[1], d[2] / ps[2]), qmul(qinv(pq), wq), (ws[0] / ps[0], ws[1] / ps[1], ws[2] / ps[2]))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _len(a):
    return (a[0] ** 2 + a[1] ** 2 + a[2] ** 2) ** 0.5


def _frame(a, b):
    x = tuple(c / _len(a) for c in a)
    z = _cross(a, b)
    z = tuple(c / _len(z) for c in z)
    return (x, _cross(z, x), z)


def _quat_from_rows(m):
    (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
    tr = m00 + m11 + m22
    if tr > 0:
        s = (tr + 1.0) ** 0.5 * 2
        return ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    if m00 > m11 and m00 > m22:
        s = (1.0 + m00 - m11 - m22) ** 0.5 * 2
        return (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = (1.0 + m11 - m00 - m22) ** 0.5 * 2
        return ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    s = (1.0 + m22 - m00 - m11) ** 0.5 * 2
    return ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)


def fit(pairs):
    """(rotación G, escala, desplazamiento) que lleva posiciones de Unity a las de UE."""
    cu = tuple(sum(p[0][i] for p in pairs) / len(pairs) for i in range(3))
    ce = tuple(sum(p[1][i] for p in pairs) / len(pairs) for i in range(3))
    vu = [_sub(p[0], cu) for p in pairs]
    ve = [_sub(p[1], ce) for p in pairs]
    su = sum(_len(v) for v in vu)
    if su < 1e-9:
        return None
    scale = sum(_len(v) for v in ve) / su
    ia = max(range(len(vu)), key=lambda k: _len(vu[k]))
    ib = max(range(len(vu)), key=lambda k: _len(_cross(vu[ia], vu[k])))
    if _len(_cross(vu[ia], vu[ib])) < 1e-9 or _len(_cross(ve[ia], ve[ib])) < 1e-9:
        return None
    fu, fe = _frame(vu[ia], vu[ib]), _frame(ve[ia], ve[ib])
    rot = tuple(tuple(sum(fe[k][i] * fu[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    g = _quat_from_rows(rot)
    moved = qrot(g, cu)
    return g, scale, (ce[0] - moved[0] * scale, ce[1] - moved[1] * scale, ce[2] - moved[2] * scale)


# --------------------------------------------------------------------------- lectura de UE
def _t(tr):
    q = tr.rotation
    return ((tr.translation.x, tr.translation.y, tr.translation.z), (q.x, q.y, q.z, q.w),
            (tr.scale3d.x, tr.scale3d.y, tr.scale3d.z))


def ue_reference(pose, names):
    """(padres, mundo, local) de la pose de referencia; el padre se deduce de ambas poses."""
    world = {b: _t(unreal.AnimPoseExtensions.get_bone_pose(pose, b, unreal.AnimPoseSpaces.WORLD)) for b in names}
    local = {b: _t(unreal.AnimPoseExtensions.get_bone_pose(pose, b, unreal.AnimPoseSpaces.LOCAL)) for b in names}
    parents = {names[0]: None} if names else {}
    for i, b in enumerate(names[1:], 1):
        best, err = None, float("inf")
        for p in names[:i]:  # en la referencia los padres van antes que los hijos
            w = compose(world[p], local[b])
            dot = abs(sum(x * y for x, y in zip(w[1], world[b][1], strict=True)))
            e = _len(_sub(w[0], world[b][0])) + (1.0 - dot) * 100.0
            if e < err:
                best, err = p, e
        parents[b] = best
    return parents, world, local


# --------------------------------------------------------------------------- retarget
def _unity_world(rest, anim, frame, cache, name):
    if name in cache:
        return cache[name]
    node = rest[name]
    tr = anim.get(norm(name)) or {}
    local = (tuple(tr["pos"][frame]) if tr.get("pos") else tuple(node["t"]),
             tuple(tr["rot"][frame]) if tr.get("rot") else tuple(node["q"]),
             tuple(tr["scale"][frame]) if tr.get("scale") else tuple(node["s"]))
    parent = node.get("parent")
    world = compose(_unity_world(rest, anim, frame, cache, parent), local) if parent in rest else local
    cache[name] = world
    return world


def retarget_keys(clip: dict, pose, bone_names: list[str]):
    """Claves locales por hueso de UE: {hueso: ([Vector], [Quat], [Vector])} o None si no se puede."""
    rest = clip["unity_rest"]["bones"]
    rest_by_norm = {norm(k): k for k in rest}
    parents, ue_world0, ue_local0 = ue_reference(pose, bone_names)
    u0: dict = {}
    for n in rest:
        _unity_world(rest, {}, 0, u0, n)
    matched = {b: rest_by_norm[norm(b)] for b in bone_names if norm(b) in rest_by_norm}
    if len(matched) < 3:
        return None
    g_fit = fit([(u0[u][0], ue_world0[b][0]) for b, u in matched.items()])
    if g_fit is None:
        return None
    g, scale, off = g_fit
    offsets = {b: qmul(qinv(qmul(g, u0[u][1])), ue_world0[b][1]) for b, u in matched.items()}
    anim = {norm(k): v for k, v in clip["bones"].items()}
    keys = {b: ([], [], []) for b in bone_names}
    for f in range(int(clip["frames"])):
        uw: dict = {}
        world: dict = {}
        for b in bone_names:
            parent = parents.get(b)
            pw = world.get(parent) if parent else None
            u = matched.get(b)
            if pw is None:
                w = ue_world0[b]  # raíz del esqueleto de UE: pose de referencia
            elif u is not None:
                wu = _unity_world(rest, anim, f, uw, u)
                rot = qmul(qmul(g, wu[1]), offsets[b])
                bone_rest = compose(pw, ue_local0[b])
                if (anim.get(norm(u)) or {}).get("pos"):
                    p = qrot(g, wu[0])
                    pos = (p[0] * scale + off[0], p[1] * scale + off[1], p[2] * scale + off[2])
                else:  # sin curva de posición: longitud de hueso de UE
                    pos = bone_rest[0]
                w = (pos, rot, bone_rest[2])
            else:
                w = compose(pw, ue_local0[b])
            world[b] = w
            loc = relative(pw, w) if pw is not None else ue_local0[b]
            keys[b][0].append(unreal.Vector(*loc[0]))
            keys[b][1].append(unreal.Quat(*loc[1]))
            keys[b][2].append(unreal.Vector(*loc[2]))
    return keys
