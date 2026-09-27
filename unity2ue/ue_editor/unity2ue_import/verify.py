"""Verificación automática del resultado de la importación (se ejecuta DENTRO de Unreal).

Uso:
  UnrealEditor-Cmd <Proyecto>.uproject -run=pythonscript -script="unity2ue_import/verify.py"

Abre cada nivel generado y cuenta actores, mallas vacías, materiales sin asignar, componentes de
script C++ y Blueprints que no compilan. Escribe ``Unity2UE/verify.json``.
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

import unreal  # noqa: E402

from unity2ue_import.common import content_root, data_dir, load_json  # noqa: E402

EAL = unreal.EditorAssetLibrary


def _asset_counts(root: str) -> dict:
    counts: dict[str, int] = {}
    bp_errors: list[str] = []
    for path in EAL.list_assets(root, recursive=True, include_folder=False):
        data = EAL.find_asset_data(path)
        cls = str(data.asset_class_path.asset_name) if hasattr(data, "asset_class_path") else str(data.asset_class)
        counts[cls] = counts.get(cls, 0) + 1
        if cls == "Blueprint":
            bp = EAL.load_asset(path)
            try:
                status = bp.get_editor_property("status")
                if "ERROR" in str(status).upper():
                    bp_errors.append(path.split(".")[0])
            except Exception:  # noqa: BLE001
                pass
    return {"by_class": dict(sorted(counts.items())), "blueprints_with_errors": bp_errors}


def _level_report(level_path: str) -> dict:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if not EAL.does_asset_exist(level_path):
        return {"exists": False}
    if not les.load_level(level_path):
        return {"exists": True, "loaded": False}
    actors = eas.get_all_level_actors()
    rep = {"exists": True, "loaded": True, "actors": len(actors), "by_class": {},
           "empty_static_meshes": [], "missing_materials": [], "script_components": 0,
           "cameras": 0, "lights": 0}
    for a in actors:
        cls = a.get_class().get_name()
        rep["by_class"][cls] = rep["by_class"].get(cls, 0) + 1
        for comp in a.get_components_by_class(unreal.ActorComponent):
            if isinstance(comp, unreal.StaticMeshComponent):
                if comp.get_editor_property("static_mesh") is None and cls != "UnityGameObject":
                    rep["empty_static_meshes"].append(a.get_actor_label())
                else:
                    for i, m in enumerate(comp.get_materials()):
                        if m is None:
                            rep["missing_materials"].append(f"{a.get_actor_label()}[{i}]")
            elif isinstance(comp, unreal.CameraComponent):
                rep["cameras"] += 1
            elif isinstance(comp, unreal.LightComponent):
                rep["lights"] += 1
            cpath = comp.get_class().get_path_name()
            if cpath.startswith("/Script/") and not cpath.startswith(("/Script/Engine.", "/Script/Niagara")):
                rep["script_components"] += 1
    rep["by_class"] = dict(sorted(rep["by_class"].items(), key=lambda kv: -kv[1]))
    rep["empty_static_meshes"] = rep["empty_static_meshes"][:50]
    rep["missing_materials"] = rep["missing_materials"][:50]
    return rep


def main() -> str:
    result = {"assets": _asset_counts(content_root()), "levels": {}}
    for entry in (load_json("levels.json") or {}).get("levels", []):
        path = entry["ue_level_path"]
        try:
            result["levels"][path] = _level_report(path)
        except Exception as exc:  # noqa: BLE001
            result["levels"][path] = {"error": str(exc)}
        unreal.log(f"[unity2ue][verify] {path}: {result['levels'][path].get('actors', '?')} actores")
    out = os.path.join(data_dir(), "verify.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    unreal.log(f"[unity2ue][verify] Informe: {out}")
    return out


if __name__ == "__main__":
    main()
