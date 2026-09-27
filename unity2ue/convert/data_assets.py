"""Instancias de ScriptableObject (``.asset``) -> DataAssets de UE (``data_assets.json``).

El script (``class X : ScriptableObject``) ya se convierte a ``UPrimaryDataAsset``; aquí se
convierten los *ficheros* con los valores (p.ej. ``Horde Data.asset``), que suelen llevar
referencias a prefabs, clips o a otros datos y que los MonoBehaviour de las escenas usan.
"""

from __future__ import annotations

from typing import Any

from ..unity.yaml_parser import UnityBinaryAssetError, load_unity_file, ref_guid
from .components import mono_behaviour
from .context import ConversionContext


def convert_data_asset(ctx: ConversionContext, unity_path: str) -> dict[str, Any] | None:
    """Devuelve la descripción del DataAsset o ``None`` si el ``.asset`` no es de un script del proyecto."""
    try:
        doc = load_unity_file(ctx.project.root / unity_path)
    except UnityBinaryAssetError:
        return None
    for obj in doc.by_type("MonoBehaviour"):
        guid = ref_guid(obj.get("m_Script"))
        script = ctx.scripts.get(guid or "")
        if script is None or script.kind != "data_asset":
            continue
        data = mono_behaviour(obj, ctx, unity_path)
        if not data:
            return None
        return {
            "unity_path": unity_path,
            "name": obj.get("m_Name") or ctx.naming.imported_name(unity_path),
            "ue_path": ctx.naming.asset_path(unity_path, prefix="DA_"),
            "cpp_class": script.cpp_class,
            "unity_class": script.unity_class,
            "properties": data.get("properties", {}),
        }
    return None
