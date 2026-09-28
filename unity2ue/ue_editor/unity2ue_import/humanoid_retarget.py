"""Retarget "Humanoid": clips de un esqueleto (p.ej. Mixamo) al de cada personaje (``humanoid.json``).

Se emparejan los huesos por su nombre humano del Avatar de Unity (Hips, Spine, LeftUpperArm...) y se
transfiere cada fotograma con la diferencia respecto a la pose de reposo de cada esqueleto:

    rot_mundo_destino = rot_mundo_origen(t) · rot_reposo_origen⁻¹ · rot_reposo_destino

Las caderas conservan el desplazamiento del clip escalado por la altura de cada personaje. Después
se asignan los clips a las propiedades ``<Estado>Clip`` de los scripts del Blueprint del personaje
(Idle -> IdleClip, Walking/Run -> MoveClip, Shoot -> ShootClip, Dying -> DeathClip...).
"""

from __future__ import annotations

import unreal

from . import anim_retarget as R
from .common import ASSET_TOOLS, LOG, ensure_dir, load, save

STEP = "humanoid"
SDS = None
LIB = unreal.SubobjectDataBlueprintFunctionLibrary

# Estado del Animator -> grupo de propiedad del script (<grupo>_clip)
STATE_GROUPS = {
    "idle": ("idle",),
    "move": ("walk", "run", "move", "locomotion", "jog"),
    "shoot": ("shoot", "fire", "attack", "aim"),
    "death": ("dying", "death", "die", "dead"),
}


def _first(folder: str, cls):
    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        return None
    for p in unreal.EditorAssetLibrary.list_assets(folder, recursive=True, include_folder=False):
        a = load(p)
        if isinstance(a, cls):
            return a
    return None


def _bone_names(skeleton) -> tuple[object, list[str]]:
    pose = unreal.AnimPoseExtensions.get_reference_pose(skeleton)
    return pose, [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(pose)]


def _match(names: list[str], human: dict[str, str]) -> dict[str, str]:
    """{nombre humano: hueso de UE} buscando cada hueso del Avatar entre los nombres de UE."""
    by_norm = {R.norm(n): n for n in names}
    out = {}
    for h, bone in human.items():
        ue = by_norm.get(R.norm(bone)) or by_norm.get(R.norm(bone.split(":")[-1]))
        if ue:
            out[h] = ue
    return out


def _retarget(seq, src_human: dict, tgt_skel, tgt_human: dict):
    src_skel = seq.get_editor_property("skeleton")
    src_pose, src_names = _bone_names(src_skel)
    tgt_pose, tgt_names = _bone_names(tgt_skel)
    src_map, tgt_map = _match(src_names, src_human), _match(tgt_names, tgt_human)
    pairs = {tgt_map[h]: src_map[h] for h in tgt_map if h in src_map}  # hueso destino -> hueso origen
    if "Hips" not in tgt_map or "Hips" not in src_map or len(pairs) < 10:
        return None, len(pairs)
    parents, t_world0, t_local0 = R.ue_reference(tgt_pose, tgt_names)
    s_world0 = {b: R._t(unreal.AnimPoseExtensions.get_bone_pose(src_pose, b, unreal.AnimPoseSpaces.WORLD))
                for b in set(pairs.values())}
    t_hips, s_hips = tgt_map["Hips"], src_map["Hips"]
    height = t_world0[t_hips][0][2] / s_world0[s_hips][0][2] if abs(s_world0[s_hips][0][2]) > 1e-3 else 1.0
    frames = unreal.AnimationLibrary.get_num_frames(seq)
    opts = unreal.AnimPoseEvaluationOptions()
    keys = {b: ([], [], []) for b in tgt_names}
    for f in range(frames + 1):
        pose = seq.get_anim_pose_at_frame(min(f, frames), opts)
        world: dict = {}
        for b in tgt_names:
            parent = parents.get(b)
            pw = world.get(parent) if parent else None
            src = pairs.get(b)
            if pw is None:
                w = t_world0[b]
            elif src is not None:
                sw = R._t(unreal.AnimPoseExtensions.get_bone_pose(pose, src, unreal.AnimPoseSpaces.WORLD))
                rot = R.qmul(R.qmul(sw[1], R.qinv(s_world0[src][1])), t_world0[b][1])
                rest = R.compose(pw, t_local0[b])
                if b == t_hips:
                    d = (sw[0][0] - s_world0[src][0][0], sw[0][1] - s_world0[src][0][1], sw[0][2] - s_world0[src][0][2])
                    base = t_world0[b][0]
                    pos = (base[0] + d[0] * height, base[1] + d[1] * height, base[2] + d[2] * height)
                else:
                    pos = rest[0]
                w = (pos, rot, rest[2])
            else:
                w = R.compose(pw, t_local0[b])
            world[b] = w
            loc = R.relative(pw, w) if pw is not None else t_local0[b]
            keys[b][0].append(unreal.Vector(*loc[0]))
            keys[b][1].append(unreal.Quat(*loc[1]))
            keys[b][2].append(unreal.Vector(*loc[2]))
    return keys, len(pairs)


def _write(path: str, skel, keys, frames: int, rate) -> object | None:
    folder, name = path.rsplit("/", 1)
    ensure_dir(folder)
    seq = load(path)
    if seq is None:
        factory = unreal.AnimSequenceFactory()
        factory.set_editor_property("target_skeleton", skel)
        seq = ASSET_TOOLS.create_asset(name, folder, unreal.AnimSequence, factory)
    if seq is None:
        return None
    ctrl = seq.controller
    ctrl.open_bracket(unreal.Text("unity2ue: retarget humanoide"))
    try:
        ctrl.remove_all_bone_tracks()
        ctrl.set_frame_rate(rate)
        ctrl.set_number_of_frames(unreal.FrameNumber(frames))
        for bone, (p, q, s) in keys.items():
            ctrl.add_bone_curve(bone)
            ctrl.set_bone_track_keys(bone, p, q, s)
    finally:
        ctrl.close_bracket()
    save(seq)
    return seq


def _group(state: str) -> str | None:
    s = state.lower()
    return next((g for g, words in STATE_GROUPS.items() if any(w in s for w in words)), None)


def _assign_to_blueprint(bp_path: str, clips: dict[str, object], item: str) -> None:
    global SDS
    bp = load(bp_path)
    if bp is None:
        return
    SDS = SDS or unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    assigned = []
    for h in SDS.k2_gather_subobject_data_for_blueprint(bp):
        comp = LIB.get_associated_object(LIB.get_data(h))
        if not isinstance(comp, unreal.ActorComponent) or comp.get_class().get_path_name().startswith("/Script/Engine"):
            continue
        for state, seq in clips.items():
            for prop in {f"{state.lower()}_clip", f"{_group(state) or state.lower()}_clip"}:
                try:
                    comp.set_editor_property(prop, seq)
                    assigned.append(f"{comp.get_class().get_name()}.{prop}")
                    break
                except Exception:  # noqa: BLE001
                    continue
    if assigned:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        save(bp)
        LOG.ok(STEP, item, f"Clips asignados: {', '.join(sorted(set(assigned)))}")
    else:
        LOG.warn(STEP, item, "Ningún script del Blueprint tiene propiedades <Estado>Clip: asigna los clips a mano "
                 "o crea un Animation Blueprint")


def run(data: dict | None) -> None:
    for job in (data or {}).get("jobs", []):
        item = job.get("prefab", "?")
        try:
            target = _first(job["target_folder"], unreal.SkeletalMesh)
            if target is None:
                LOG.warn(STEP, item, f"No hay SkeletalMesh en {job['target_folder']}")
                continue
            tgt_skel = target.get_editor_property("skeleton")
            clips = {}
            for st in job["states"]:
                seq = _first(st["source_folder"], unreal.AnimSequence)
                if seq is None:
                    LOG.warn(STEP, item, f"{st['state']}: no hay animación importada en {st['source_folder']}")
                    continue
                keys, n = _retarget(seq, st["source_human"], tgt_skel, job["target_human"])
                if keys is None:
                    LOG.warn(STEP, item, f"{st['state']}: sólo {n} huesos humanos en común; no se redirige")
                    continue
                path = f"{job['target_folder']}/Anims/{target.get_name()}_{st['state'].replace(' ', '_')}"
                n_frames = unreal.AnimationLibrary.get_num_frames(seq)
                length = unreal.AnimationLibrary.get_time_at_frame(seq, n_frames) or 1.0
                rate = unreal.FrameRate(max(1, round(n_frames / length)), 1)
                out = _write(path, tgt_skel, keys, n_frames, rate)
                if out is not None:
                    clips[st["state"]] = out
                    LOG.ok(STEP, item, f"{st['state']}: {seq.get_name()} -> {path} ({n} huesos)")
            if clips and job.get("blueprint"):
                _assign_to_blueprint(job["blueprint"], clips, item)
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, item)
