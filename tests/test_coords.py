import math

import pytest

from unity2ue.convert.coords import (
    location_to_ue,
    quat_to_ue,
    scale_to_ue,
    transform_to_ue,
    ue_quat_to_rotator,
    vertical_to_horizontal_fov,
)

S = math.sqrt(0.5)


def test_location_axes_and_units():
    # Unity (x=1 derecha, y=2 arriba, z=3 adelante) -> UE (X adelante, Y derecha, Z arriba) en cm
    assert location_to_ue((1, 2, 3)) == (300.0, 100.0, 200.0)


def test_scale_axes():
    assert scale_to_ue((1, 2, 3)) == (3.0, 1.0, 2.0)


@pytest.mark.parametrize(
    "unity_quat, expected",
    [
        ((0, S, 0, S), (0.0, 90.0, 0.0)),   # yaw 90 en Unity -> yaw 90 en UE
        ((S, 0, 0, S), (-90.0, 0.0, 0.0)),  # pitch +90 (mirar abajo) en Unity -> pitch -90 en UE
        ((0, 0, 0, 1), (0.0, 0.0, 0.0)),
    ],
)
def test_rotation(unity_quat, expected):
    pyr = ue_quat_to_rotator(quat_to_ue(unity_quat))
    assert pyr == pytest.approx(expected, abs=1e-3)


def test_roll():
    # Rotación de 30º sobre el eje Z de Unity (adelante) = roll en UE.
    a = math.radians(30) / 2
    pyr = ue_quat_to_rotator(quat_to_ue((0, 0, math.sin(a), math.cos(a))))
    assert abs(pyr[2]) == pytest.approx(30.0, abs=1e-3)
    assert pyr[0] == pytest.approx(0.0, abs=1e-3) and pyr[1] == pytest.approx(0.0, abs=1e-3)


def test_transform_dict():
    t = transform_to_ue({"x": 0, "y": 1, "z": -10}, {"x": 0, "y": 0, "z": 0, "w": 1}, {"x": 1, "y": 1, "z": 1})
    assert t["location"] == [-1000.0, 0.0, 100.0]
    assert t["scale"] == [1.0, 1.0, 1.0]


def test_fov():
    assert vertical_to_horizontal_fov(60, 16 / 9) == pytest.approx(91.4928, abs=1e-3)
