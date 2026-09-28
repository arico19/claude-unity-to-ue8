"""Crea AnimSequences de UE a partir de los clips ``.anim`` de Unity (``anim_clips.json``).

Para cada clip se elige el esqueleto importado con más huesos en común y se escriben las pistas
de cada hueso. Conversión del espacio local de Unity al de UE (ambos importadores reflejan el FBX
por un eje distinto: Unity niega X, UE niega Y):
    rotación (x, y, z, w) -> (-x, -y, z, w)      posición (x, y, z) -> (-x, -y, z) * escala
La escala de unidades se deduce comparando las traslaciones del clip con las de la pose de
referencia del esqueleto. El hueso raíz del esqueleto conserva su pose de referencia (lleva la
corrección de ejes del FBX).
"""

from __future__ import annotations

import statistics

import unreal

from .anim_retarget import retarget_keys
from .common import ASSET_TOOLS, LOG, content_root, ensure_dir, load, save

STEP = "anim_clips"


def _norm(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _skeletons() -> list:
    out = []
    for p in unreal.EditorAssetLibrary.list_assets(content_root(), recursive=True, include_folder=False):
        data = unreal.EditorAssetLibrary.find_asset_data(p)
        if str(data.asset_class_path.asset_name) == "Skeleton":
            skel = load(p)
            if skel is not None:
                pose = unreal.AnimPoseExtensions.get_reference_pose(skel)
                names = [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(pose)]
                out.append((skel, pose, names))
    return out


def _best_skeleton(clip: dict, skeletons: list):
    wanted = {_norm(b) for b in clip["bones"]}
    best, score = None, 0
    for entry in skeletons:
        n = len(wanted & {_norm(b) for b in entry[2]})
        if n > score:
            best, score = entry, n
    return best if best and score >= max(1, len(wanted) // 2) else None


def _unit_scale(clip: dict, pose, by_norm: dict) -> float:
    ratios = []
    for bone, tr in clip["bones"].items():
        ue = by_norm.get(_norm(bone))
        if ue is None or not tr.get("pos"):
            continue
        p = tr["pos"][0]
        clip_len = (p[0] ** 2 + p[1] ** 2 + p[2] ** 2) ** 0.5
        ref = unreal.AnimPoseExtensions.get_bone_pose(pose, ue, unreal.AnimPoseSpaces.LOCAL).translation
        if clip_len > 1e-5 and ref.length() > 1e-3:
            ratios.append(ref.length() / clip_len)
    return statistics.median(ratios) if ratios else 100.0


def _naive_keys(clip: dict, pose, bone_names: list[str]):
    """Sin pose de reposo de Unity: rotaciones locales con el cambio de espejo (menos fiable)."""
    by_norm = {_norm(b): b for b in bone_names}
    scale = _unit_scale(clip, pose, by_norm)
    frames = int(clip["frames"])
    by_clip = {_norm(b): tr for b, tr in clip["bones"].items()}
    keys = {}
    for bone in bone_names:
        ref = unreal.AnimPoseExtensions.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.LOCAL)
        tr = by_clip.get(_norm(bone)) if bone != bone_names[0] else None
        rots = ([unreal.Quat(-q[0], -q[1], q[2], q[3]) for q in tr["rot"]] if tr and tr.get("rot")
                else [ref.rotation] * frames)
        poss = ([unreal.Vector(-p[0] * scale, -p[1] * scale, p[2] * scale) for p in tr["pos"]]
                if tr and tr.get("pos") else [ref.translation] * frames)
        scls = [unreal.Vector(*v) for v in tr["scale"]] if tr and tr.get("scale") else [ref.scale3d] * frames
        keys[bone] = (poss, rots, scls)
    return keys


def _build(clip: dict, skel, pose, bone_names: list[str]) -> object | None:
    folder, name = clip["ue_path"].rsplit("/", 1)
    ensure_dir(folder)
    seq = load(clip["ue_path"])
    if seq is None:
        factory = unreal.AnimSequenceFactory()
        factory.set_editor_property("target_skeleton", skel)
        seq = ASSET_TOOLS.create_asset(name, folder, unreal.AnimSequence, factory)
    if seq is None:
        return None
    keys = retarget_keys(clip, pose, bone_names) if clip.get("unity_rest") else None
    if keys is None:
        LOG.warn(STEP, clip["unity_path"], "Sin pose de reposo de Unity: conversión directa de rotaciones (revisar)")
        keys = _naive_keys(clip, pose, bone_names)
    ctrl = seq.controller
    ctrl.open_bracket(unreal.Text("unity2ue: clip de Unity"))
    try:
        ctrl.remove_all_bone_tracks()
        ctrl.set_frame_rate(unreal.FrameRate(int(clip["fps"]), 1))
        ctrl.set_number_of_frames(unreal.FrameNumber(int(clip["frames"]) - 1))
        for bone in bone_names:
            ctrl.add_bone_curve(bone)
            ctrl.set_bone_track_keys(bone, *keys[bone])
    finally:
        ctrl.close_bracket()
    save(seq)
    return seq


def run(data: dict | None) -> None:
    clips = (data or {}).get("clips", [])
    if not clips:
        return
    skeletons = _skeletons()
    for clip in clips:
        item = clip.get("unity_path", "?")
        try:
            match = _best_skeleton(clip, skeletons)
            if match is None:
                LOG.warn(STEP, item, "Ningún esqueleto importado coincide con sus huesos (¿anima objetos, no huesos?): "
                         "recrear como Level Sequence")
                continue
            seq = _build(clip, *match)
            if seq is not None:
                LOG.ok(STEP, item, f"-> {clip['ue_path']} (esqueleto {match[0].get_name()})")
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, item)
