"""Prueba de juego automática (se ejecuta DENTRO del editor con UI).

Uso:
  UnrealEditor <Proyecto>.uproject -ExecutePythonScript="unity2ue_import/play_test.py"
  (nivel: variable de entorno UNITY2UE_PLAY_LEVEL; por defecto el mapa por defecto de settings.json)

Abre el nivel, pulsa Play (PIE), hace capturas a los segundos indicados en UNITY2UE_PLAY_SHOTS
(por defecto 3,8,15) en ``Unity2UE/play``, para el juego y cierra el editor.
"""

from __future__ import annotations

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

import unreal  # noqa: E402

from unity2ue_import.common import data_dir, settings  # noqa: E402

OUT = os.path.join(data_dir(), "play")
SHOTS = [float(s) for s in os.environ.get("UNITY2UE_PLAY_SHOTS", "3,8,15").split(",")]


class PlayTest:
    def __init__(self) -> None:
        os.makedirs(OUT, exist_ok=True)
        self.level = os.environ.get("UNITY2UE_PLAY_LEVEL") or settings().get("default_map")
        self.les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        self.ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        self.state = "load"
        self.t0 = 0.0
        self.shots = list(SHOTS)
        self.done: list[str] = []
        self.frames = 0
        unreal.EditorPythonScripting.set_keep_python_script_alive(True)
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def tick(self, _dt: float) -> None:
        # load_level/Play hacen tick de Slate por dentro: sin esta guarda el callback se
        # reentra y carga el nivel varias veces a la vez (fatal en AsyncLoading2).
        if getattr(self, "_busy", False):
            return
        self._busy = True
        try:
            self._tick()
        finally:
            self._busy = False

    def _tick(self) -> None:
        try:
            self.frames += 1
            if self.state == "load":
                self.state = "loading"
                if self.level:
                    self.les.load_level(self.level)
                self.state, self.frames = "warm", 0
            elif self.state == "warm" and self.frames > 60:
                unreal.log(f"[unity2ue][play] Play en {self.level}")
                self.les.editor_request_begin_play()
                self.state, self.t0 = "playing", time.time()
            elif self.state == "playing":
                elapsed = time.time() - self.t0
                if self.shots and elapsed >= self.shots[0]:
                    sec = self.shots.pop(0)
                    world = self.ues.get_game_world()
                    name = os.path.join(OUT, f"play_{int(sec):02d}s.png").replace("\\", "/")
                    if world:
                        unreal.SystemLibrary.execute_console_command(world, f"HighResShot 1280x720 filename={name}")
                        self.done.append(name)
                    else:
                        unreal.log_error("[unity2ue][play] No hay mundo de juego (¿no arrancó el Play?)")
                if not self.shots and elapsed >= SHOTS[-1] + 2:
                    self.les.editor_request_end_play()
                    self.state, self.frames = "ending", 0
            elif self.state == "ending" and self.frames > 30:
                self.finish()
        except Exception as exc:  # noqa: BLE001
            unreal.log_error(f"[unity2ue][play] {exc}")
            self.finish()

    def finish(self) -> None:
        unreal.unregister_slate_post_tick_callback(self.handle)
        with open(os.path.join(OUT, "play.json"), "w", encoding="utf-8") as fh:
            json.dump({"level": self.level, "shots": self.done}, fh, indent=2)
        unreal.log(f"[unity2ue][play] Terminado: {len(self.done)} capturas en {OUT}")
        unreal.EditorPythonScripting.set_keep_python_script_alive(False)


PLAY = PlayTest()
