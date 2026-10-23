"""Retratos de los personajes armados: cada uno congelado en reposo (Idle) y a mitad del disparo
(Shoot), de lado y de frente, para comprobar orientación, altura, texturas y cómo lleva el arma.

Uso (editor con render, no commandlet; el editor se cierra al terminar):
  UnrealEditor <Proyecto>.uproject -ExecutePythonScript="unity2ue_import/portraits.py"
o ``python -m unity2ue retratos <ProyectoUE>``. Capturas en ``Unity2UE/retratos``:
``<Blueprint>[_<arma alternativa>]_<reposo|disparo>_<lado|frente>.png``. Los personajes salen de
``armas.json`` (uno por modelo); los que tienen armas alternativas (p.ej. el lanzallamas oculto del
soldado) salen también con ellas. Se colocan en el primer nivel convertido, que no se guarda.
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

import unreal  # noqa: E402

from unity2ue_import.common import data_dir, load, load_json  # noqa: E402

OUT = os.path.join(data_dir(), "retratos")
WIDTH, HEIGHT = 900, 900
WAIT_FRAMES = 120
SPACING = 600.0  # cm entre personajes, en fila hacia el fondo (que no salgan en la foto del vecino)
ORIGIN = unreal.Vector(250.0, 0.0, 0.0)
# (sufijo, desplazamiento de la cámara respecto al personaje, rotación)
VIEWS = (("lado", unreal.Vector(0, -230, 115), unreal.Rotator(roll=0, pitch=-5, yaw=90)),
         ("frente", unreal.Vector(260, 0, 115), unreal.Rotator(roll=0, pitch=-5, yaw=180)))
POSES = (("reposo", ("idle",)), ("disparo", ("shoot", "fire")))


def _clip(mesh, words):
    folder = mesh.get_path_name().rsplit("/", 1)[0] + "/Anims"
    for p in unreal.EditorAssetLibrary.list_assets(folder, recursive=True):
        if any(w in p.lower() for w in words):
            return load(p)
    return None


def _show_alternative(actor, weapon: str) -> None:
    """Como en el juego al cambiar de arma: muestra Arma_<arma> y oculta las demás y la integrada."""
    for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
        name = comp.get_name()
        if name.startswith("Arma_"):
            comp.set_visibility(name == f"Arma_{weapon}", True)
        elif comp.get_attach_parent() and comp.get_attach_parent().get_name() == "TommyGun":
            comp.set_visibility(False, True)
    for skin in actor.get_components_by_class(unreal.SkeletalMeshComponent):
        if skin.get_bone_index("TommyGun") >= 0:
            skin.hide_bone_by_name("TommyGun", unreal.PhysBodyOp.PBO_NONE)


class Portraits:
    def __init__(self) -> None:
        self.queue: list = []
        self.wait = WAIT_FRAMES
        self.done: list[str] = []
        os.makedirs(OUT, exist_ok=True)
        levels = [e["ue_level_path"] for e in (load_json("levels.json") or {}).get("levels", [])]
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if levels:
            les.load_level(levels[0])
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        cfg = load_json("armas.json") or {}
        shots, meshes = [], set()  # (bp_path, arma alternativa o None)
        for bp_path, who in cfg.get("personajes", {}).items():
            if who.get("malla_personaje") in meshes:
                continue  # un retrato por modelo
            meshes.add(who.get("malla_personaje"))
            shots.append((bp_path, None))
            if not who.get("arma"):  # lleva el arma general: también con cada alternativa
                shots += [(bp_path, alt) for alt in cfg.get("alternativas", [])]
        slot = 0
        for bp_path, alt in shots:
            bp = load(bp_path)
            if bp is None:
                continue
            for pose, words in POSES:
                loc = ORIGIN + unreal.Vector(slot * SPACING, 0, 0)
                slot += 1
                actor = eas.spawn_actor_from_class(bp.generated_class(), loc, unreal.Rotator(0, 0, 0))
                if alt:
                    _show_alternative(actor, alt)
                for comp in actor.get_components_by_class(unreal.SkeletalMeshComponent):
                    clip = _clip(comp.get_editor_property("skeletal_mesh"), words)
                    if clip is not None:
                        comp.set_update_animation_in_editor(True)
                        t = clip.get_play_length() * (0.5 if pose == "disparo" else 0.0)
                        comp.override_animation_data(clip, False, False, t, 0.0)
                name = bp_path.rsplit("/", 1)[-1] + (f"_{alt}" if alt else "")
                for suffix, offset, rot in VIEWS:
                    self.queue.append((f"{name}_{pose}_{suffix}", loc + offset, rot))
        unreal.EditorPythonScripting.set_keep_python_script_alive(True)
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def tick(self, _dt: float) -> None:
        if getattr(self, "_busy", False):
            return
        self._busy = True
        try:
            if self.wait > 0:
                self.wait -= 1
                return
            if not self.queue:
                self.finish()
                return
            name, loc, rot = self.queue.pop(0)
            unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(loc, rot)
            path = os.path.join(OUT, f"{name}.png")
            unreal.AutomationLibrary.take_high_res_screenshot(WIDTH, HEIGHT, path)
            self.done.append(path)
            self.wait = 40
        except Exception as exc:  # noqa: BLE001
            unreal.log_error(f"[unity2ue][retratos] {exc}")
            self.finish()
        finally:
            self._busy = False

    def finish(self) -> None:
        unreal.unregister_slate_post_tick_callback(self.handle)
        with open(os.path.join(OUT, "retratos.json"), "w", encoding="utf-8") as fh:
            json.dump(self.done, fh, indent=2)
        unreal.log(f"[unity2ue][retratos] {len(self.done)} capturas en {OUT}")
        # Salir sin guardar el nivel (los personajes colocados son sólo para la foto).
        unreal.EditorPythonScripting.set_keep_python_script_alive(False)
        unreal.SystemLibrary.quit_editor()


PORTRAITS = Portraits()
