"""Crea los DataAssets (instancias de ScriptableObject de Unity) de ``data_assets.json``.

Dos pasadas: primero se crean todos (unos referencian a otros, p.ej. HordeGameData -> BossData)
y después se asignan los valores. Va después de los Blueprints (referencias a prefabs) y antes
de los niveles (los componentes de las escenas referencian estos datos).
"""

from __future__ import annotations

import unreal

from . import components as comps
from .common import ASSET_TOOLS, LOG, ensure_dir, load, save, script_class

STEP = "data_assets"


def _create(entry: dict):
    path = entry["ue_path"]
    existing = load(path)
    if existing is not None:
        return existing  # reimportación: se reutiliza (borrar y recrear falla en la misma sesión)
    cls = script_class(entry["cpp_class"])
    if cls is None:
        LOG.error(STEP, entry["unity_path"], f"Clase C++ {entry['cpp_class']} no encontrada (¿módulo compilado?)")
        return None
    folder, name = path.rsplit("/", 1)
    ensure_dir(folder)
    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", cls)
    asset = ASSET_TOOLS.create_asset(name, folder, None, factory)
    if asset is None:
        LOG.error(STEP, entry["unity_path"], f"No se pudo crear {path}")
    return asset


def run(data: dict | None) -> None:
    entries = (data or {}).get("data_assets", [])
    created = []
    for e in entries:
        try:
            asset = _create(e)
            if asset is not None:
                created.append((e, asset))
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, e.get("unity_path", "?"))
    for e, asset in created:
        try:
            comps.configure_script(asset, {"cpp_class": e["cpp_class"], "properties": e["properties"]},
                                   e["unity_path"])
            save(asset)
            LOG.ok(STEP, e["unity_path"], f"-> {e['ue_path']}")
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, e.get("unity_path", "?"))
