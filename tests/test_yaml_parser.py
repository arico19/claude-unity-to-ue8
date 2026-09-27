import pytest

from unity2ue.unity.yaml_parser import UnityBinaryAssetError, load_yaml, parse_unity_yaml

DOC = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Name: On
  m_IsActive: 1
--- !u!4 &-200 stripped
Transform:
  m_CorrespondingSourceObject: {fileID: 400, guid: 12345678901234567890123456789012, type: 3}
  m_PrefabInstance: {fileID: 50}
"""


def test_parse_documents():
    doc = parse_unity_yaml(DOC)
    assert set(doc.objects) == {100, -200}
    go = doc.get(100)
    assert go.class_id == 1 and go.type_name == "GameObject"
    # "On" no debe convertirse en True (YAML 1.1)
    assert go.get("m_Name") == "On"
    t = doc.get(-200)
    assert t.stripped
    # GUID numérico preservado como string
    assert t.get("m_CorrespondingSourceObject")["guid"] == "12345678901234567890123456789012"


def test_binary_rejected():
    with pytest.raises(UnityBinaryAssetError):
        parse_unity_yaml("\x00\x01binary")


def test_meta_loader_keeps_leading_zero_guid():
    data = load_yaml("fileFormatVersion: 2\nguid: 00000000000000000000000000000789\n")
    assert data["guid"] == "00000000000000000000000000000789"
