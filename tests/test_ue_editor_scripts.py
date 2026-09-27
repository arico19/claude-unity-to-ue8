"""Los scripts del editor no pueden ejecutarse sin Unreal; comprobamos al menos que compilan."""

import py_compile
from pathlib import Path

import pytest

EDITOR = Path(__file__).resolve().parent.parent / "unity2ue" / "ue_editor" / "unity2ue_import"


@pytest.mark.parametrize("path", sorted(EDITOR.glob("*.py")), ids=lambda p: p.name)
def test_compiles(path):
    py_compile.compile(str(path), doraise=True)


def test_key_mapping():
    from unity2ue.ue.project_gen import unity_key_to_ue

    assert unity_key_to_ue("left shift") == "LeftShift"
    assert unity_key_to_ue("w") == "W"
    assert unity_key_to_ue("1") == "One"
    assert unity_key_to_ue("[3]") == "NumPadThree"
    assert unity_key_to_ue("f5") == "F5"
    assert unity_key_to_ue("mouse 0") == "LeftMouseButton"


def test_default_engine_ini_targets_dx11_sm5():
    """DX12 cuelga la GPU en equipos como GTX 1070; DX11 + SM5 sin sombras virtuales (exigen SM6)."""
    from unity2ue.config import ConversionConfig
    from unity2ue.ue.project_gen import default_engine_ini

    ini = default_engine_ini(ConversionConfig(), "/Game/Unity/Maps/Main", -981.0, {})
    assert "DefaultGraphicsRHI=DefaultGraphicsRHI_DX11" in ini
    assert "+TargetedRHIs=PCD3D_SM5" in ini
    assert "r.Shadow.Virtual.Enable=0" in ini
