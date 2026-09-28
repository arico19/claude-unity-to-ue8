"""Conversión de clips .anim de Unity (curvas -> muestras) y de su pose de reposo."""

import math

from unity2ue.convert.anim_clips import _eval, _signed_perms, euler_to_quat


def _close(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b, strict=True))


def test_euler_matches_unity_quaternion_euler():
    # Quaternion.Euler(0, 90, 0) en Unity = (0, 0.7071, 0, 0.7071)
    h = math.sqrt(0.5)
    assert _close(euler_to_quat(0, 90, 0), [0, h, 0, h])
    # Orden de Unity: Z, luego X, luego Y (q = qy * qx * qz)
    q = euler_to_quat(30, 45, 60)
    assert _close(q, [0.3919038, 0.2005621, 0.3604234, 0.8223632], 1e-6)


def test_hermite_uses_unity_tangents():
    keys = [{"time": 0, "value": 0.0, "outSlope": 0.0}, {"time": 1, "value": 10.0, "inSlope": 0.0}]
    assert _eval(keys, 0.5, "x") == 5.0  # tangentes planas: punto medio exacto
    assert _eval(keys, 2.0, "x") == 10.0  # más allá del último key: se mantiene
    steps = [{"time": 0, "value": 1.0, "outSlope": "Infinity"}, {"time": 1, "value": 3.0, "inSlope": "Infinity"}]
    assert _eval(steps, 0.7, "x") == 1.0  # tangente "constant" de Unity: escalón


def test_signed_permutations_cover_axis_conversions():
    perms = _signed_perms()
    assert len(perms) == 48
    rx_minus_90 = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]  # FBX (Blender) -> Unity: -90 en X
    assert rx_minus_90 in perms
