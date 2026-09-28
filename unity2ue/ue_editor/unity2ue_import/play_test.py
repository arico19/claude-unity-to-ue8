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
# Comandos de consola a lo largo de la partida: "segundo:comando;segundo:comando"
# (p.ej. "1:unity2ue.AutoMove -1;3:unity2ue.AutoFire 1" en juegos con ganchos de prueba).
CMDS = sorted(
    (float(t), c.strip()) for t, _, c in
    (part.partition(":") for part in os.environ.get("UNITY2UE_PLAY_CMDS", "").split(";") if ":" in part)
)


class PlayTest:
    def __init__(self) -> None:
        os.makedirs(OUT, exist_ok=True)
        self.level = os.environ.get("UNITY2UE_PLAY_LEVEL") or settings().get("default_map")
        self.les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        self.ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        self.state = "load"
        self.t0 = 0.0
        self.shots = list(SHOTS)
        self.cmds = list(CMDS)
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
                while self.cmds and elapsed >= self.cmds[0][0]:
                    _, cmd = self.cmds.pop(0)
                    world = self.ues.get_game_world()
                    if world:
                        unreal.SystemLibrary.execute_console_command(world, cmd)
                        unreal.log(f"[unity2ue][play] {elapsed:.1f}s: {cmd}")
                if self.shots and elapsed >= self.shots[0]:
                    sec = self.shots.pop(0)
                    world = self.ues.get_game_world()
                    name = os.path.join(OUT, f"play_{sec:04.1f}s.png").replace("\\", "/")
                    if world:
                        unreal.SystemLibrary.execute_console_command(world, f"HighResShot 1280x720 filename={name}")
                        self.done.append(name)
                    else:
                        unreal.log_error("[unity2ue][play] No hay mundo de juego (¿no arrancó el Play?)")
                if not self.shots and elapsed >= SHOTS[-1] + 2:
                    self._dump_actors()
                    self.les.editor_request_end_play()
                    self.state, self.frames = "ending", 0
            elif self.state == "ending" and self.frames > 30:
                self.finish()
        except Exception as exc:  # noqa: BLE001
            unreal.log_error(f"[unity2ue][play] {exc}")
            self.finish()

    def _dump_actors(self) -> None:
        """Guarda qué actores hay durante la partida (posición, rotación, mallas) en play/actors.json."""
        world = self.ues.get_game_world()
        if not world:
            return
        out = []
        for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
            meshes = []
            for c in a.get_components_by_class(unreal.PrimitiveComponent):
                mesh = None
                if isinstance(c, unreal.StaticMeshComponent):
                    mesh = c.get_editor_property("static_mesh")
                elif isinstance(c, unreal.SkeletalMeshComponent):
                    mesh = c.get_skeletal_mesh_asset() if hasattr(c, "get_skeletal_mesh_asset") else None
                if isinstance(c, (unreal.StaticMeshComponent, unreal.SkeletalMeshComponent)):
                    meshes.append({"comp": c.get_name(), "mesh": mesh.get_name() if mesh else None,
                                   "visible": c.is_visible()})
            loc, rot = a.get_actor_location(), a.get_actor_rotation()
            out.append({"name": a.get_name(), "class": a.get_class().get_name(),
                        "location": [round(loc.x), round(loc.y), round(loc.z)],
                        "yaw": round(rot.yaw), "hidden": a.is_hidden_ed() if hasattr(a, "is_hidden_ed") else None,
                        "meshes": meshes})
        with open(os.path.join(OUT, "actors.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        unreal.log(f"[unity2ue][play] {len(out)} actores en la partida -> actors.json")

    def finish(self) -> None:
        unreal.unregister_slate_post_tick_callback(self.handle)
        with open(os.path.join(OUT, "play.json"), "w", encoding="utf-8") as fh:
            json.dump({"level": self.level, "shots": self.done}, fh, indent=2)
        unreal.log(f"[unity2ue][play] Terminado: {len(self.done)} capturas en {OUT}")
        unreal.EditorPythonScripting.set_keep_python_script_alive(False)


PLAY = PlayTest()
