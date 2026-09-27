"""Capturas de cada nivel generado (se ejecuta DENTRO del editor con render, no en commandlet).

Uso:
  UnrealEditor <Proyecto>.uproject -ExecutePythonScript="unity2ue_import/screenshots.py"

Por cada nivel hace dos capturas en ``Unity2UE/screenshots``: desde la cámara convertida de
Unity (lo que vería el jugador) y una vista general que encuadra todo el nivel. Al terminar
cierra el editor.
"""

from __future__ import annotations

import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

import unreal  # noqa: E402

from unity2ue_import import import_assets  # noqa: E402
from unity2ue_import.common import LOG, data_dir, load_json  # noqa: E402

OUT = os.path.join(data_dir(), "screenshots")
WIDTH, HEIGHT = 1280, 720
WAIT_FRAMES = 90  # deja que carguen texturas/shaders antes de capturar


def _bounds(actors):
    lo, hi = None, None
    for a in actors:
        if not any(isinstance(c, (unreal.StaticMeshComponent, unreal.SkeletalMeshComponent))
                   for c in a.get_components_by_class(unreal.PrimitiveComponent)):
            continue
        origin, extent = a.get_actor_bounds(False)
        if extent.length() <= 0 or extent.length() > 1e6:
            continue
        mn, mx = origin - extent, origin + extent
        lo = mn if lo is None else unreal.Vector(min(lo.x, mn.x), min(lo.y, mn.y), min(lo.z, mn.z))
        hi = mx if hi is None else unreal.Vector(max(hi.x, mx.x), max(hi.y, mx.y), max(hi.z, mx.z))
    return lo, hi


def _views(actors):
    views = []
    for a in actors:
        cams = a.get_components_by_class(unreal.CameraComponent)
        if cams:
            views.append(("camara", cams[0].get_world_location(), cams[0].get_world_rotation()))
            break
    lo, hi = _bounds(actors)
    if lo is not None:
        center = (lo + hi) * 0.5
        radius = max((hi - lo).length() * 0.5, 200.0)
        dist = radius / math.tan(math.radians(45))
        pitch, yaw = -35.0, -135.0
        d = unreal.Rotator(roll=0, pitch=pitch, yaw=yaw).get_forward_vector()
        views.append(("general", center - d * dist, unreal.Rotator(roll=0, pitch=pitch, yaw=yaw)))
    return views


class Shooter:
    def __init__(self) -> None:
        self.levels = [e["ue_level_path"] for e in (load_json("levels.json") or {}).get("levels", [])]
        self.queue: list = []
        self.wait = 0
        self.done: list[str] = []
        # -ExecutePythonScript cierra el editor tras ejecutar el script salvo que se pida mantenerlo
        # vivo (EditorPythonExecuter.cpp): las capturas necesitan varios frames.
        unreal.EditorPythonScripting.set_keep_python_script_alive(True)
        self.handle = unreal.register_slate_post_tick_callback(self.tick)
        os.makedirs(OUT, exist_ok=True)

    def _next_level(self) -> bool:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        while self.levels:
            path = self.levels.pop(0)
            if unreal.EditorAssetLibrary.does_asset_exist(path) and les.load_level(path):
                name = path.rsplit("/", 1)[-1]
                self.queue = [(name, *v) for v in _views(eas.get_all_level_actors())]
                self.wait = WAIT_FRAMES
                return True
        return False

    def tick(self, _dt: float) -> None:
        # load_level hace tick de Slate por dentro: evita reentrar en el callback.
        if getattr(self, "_busy", False):
            return
        self._busy = True
        try:
            self._tick()
        finally:
            self._busy = False

    def _tick(self) -> None:
        try:
            if self.wait > 0:
                self.wait -= 1
                return
            if not self.queue and not self._next_level():
                self.finish()
                return
            if not self.queue:
                return
            name, kind, loc, rot = self.queue.pop(0)
            ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            ues.set_level_viewport_camera_info(loc, rot)
            path = os.path.join(OUT, f"{name}_{kind}.png")
            unreal.AutomationLibrary.take_high_res_screenshot(WIDTH, HEIGHT, path)
            self.done.append(path)
            self.wait = 30
        except Exception as exc:  # noqa: BLE001
            unreal.log_error(f"[unity2ue][screenshots] {exc}")
            self.finish()

    def finish(self) -> None:
        unreal.unregister_slate_post_tick_callback(self.handle)
        with open(os.path.join(OUT, "screenshots.json"), "w", encoding="utf-8") as fh:
            json.dump(self.done, fh, indent=2)
        unreal.log(f"[unity2ue][screenshots] {len(self.done)} capturas en {OUT}")
        unreal.EditorPythonScripting.set_keep_python_script_alive(False)  # el editor se cierra solo


# Las fuentes no se pueden importar en el commandlet (necesitan Slate): se importan aquí.
try:
    import_assets.run(load_json("assets.json"), only=import_assets.NEEDS_UI)
    LOG.save("import_log_ui.json")
except Exception as _exc:  # noqa: BLE001
    unreal.log_error(f"[unity2ue][screenshots] importando fuentes: {_exc}")

SHOOTER = Shooter()
