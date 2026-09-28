"""Punto de entrada: ejecuta toda la importación dentro de Unreal Editor.

Uso:
  UnrealEditor-Cmd <Proyecto>.uproject -run=pythonscript -script="unity2ue_import/run_all.py"
o desde el editor: Tools > Execute Python Script... / consola Python:
  import unity2ue_import.run_all as r; r.main()

Pasos opcionales con la variable de entorno UNITY2UE_STEPS (p.ej. "materials,levels").
"""

from __future__ import annotations

import os
import sys

# Cuando se ejecuta como fichero (-script=...), el paquete puede no estar en sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

import unreal  # noqa: E402

from unity2ue_import import (  # noqa: E402
    anim_clips,
    blueprints,
    data_assets,
    import_assets,
    input_actions,
    levels,
    materials,
)
from unity2ue_import.common import LOG, load_json, save_all_dirty  # noqa: E402

ALL_STEPS = ("assets", "anims", "materials", "input", "blueprints", "data", "levels")


def main(steps: tuple[str, ...] | None = None) -> str:
    env = os.environ.get("UNITY2UE_STEPS")
    steps = steps or (tuple(s.strip() for s in env.split(",")) if env else ALL_STEPS)
    unreal.log(f"[unity2ue] Pasos: {', '.join(steps)}")
    if "assets" in steps:
        import_assets.run(load_json("assets.json"))
        save_all_dirty()
    if "anims" in steps:
        anim_clips.run(load_json("anim_clips.json"))
        save_all_dirty()
    if "materials" in steps:
        materials.run(load_json("materials.json"))
        save_all_dirty()
    if "input" in steps:
        input_actions.run()
        save_all_dirty()
    if "blueprints" in steps or "levels" in steps:
        # Nivel vacío: que ningún nivel generado quede cargado mientras se reconstruye.
        try:
            unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
        except Exception:  # noqa: BLE001
            pass
    if "blueprints" in steps:
        blueprints.run(load_json("blueprints.json"))
        save_all_dirty()
    if "data" in steps:
        data_assets.run(load_json("data_assets.json"))
        save_all_dirty()
    if "levels" in steps:
        levels.run(load_json("levels.json"))
        save_all_dirty()
    path = LOG.save()
    summary = {}
    for e in LOG.entries:
        summary[e["status"]] = summary.get(e["status"], 0) + 1
    unreal.log(f"[unity2ue] Terminado: {summary}. Log: {path}")
    return path


if __name__ == "__main__":
    main()
