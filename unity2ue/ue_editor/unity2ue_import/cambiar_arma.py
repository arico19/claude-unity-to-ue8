"""Cambia el arma de los personajes (ver weapons.py). Se ejecuta con el editor cerrado:

  UnrealEditor-Cmd <Proyecto>.uproject -run=pythonscript -script="unity2ue_import/cambiar_arma.py"

El arma se toma de la variable de entorno UNITY2UE_ARMA (si falta, la de Unity2UE/armas.json) y
UNITY2UE_ARMA_DATOS (JSON opcional) añade o cambia sus datos: fichero, posicion, rotacion, escala, boca.
Lo normal es lanzarlo con ``python -m unity2ue arma <ProyectoUE> <nombre>``.
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from unity2ue_import import weapons  # noqa: E402
from unity2ue_import.common import LOG, save_all_dirty  # noqa: E402

if __name__ == "__main__":
    weapons.run(os.environ.get("UNITY2UE_ARMA") or None, json.loads(os.environ.get("UNITY2UE_ARMA_DATOS") or "{}"))
    save_all_dirty()
    LOG.save("armas_log.json")
