"""Animación "Humanoid" de Unity -> clips redirigidos (retarget) al esqueleto de cada personaje.

En Unity un personaje humanoide puede reproducir clips hechos para otro esqueleto (p.ej. Mixamo):
su Avatar asocia cada hueso a un nombre humano (Hips, LeftUpperLeg...), guardado en el ``.meta``
del modelo (``humanDescription``). Aquí se generan "trabajos" de retarget: para cada personaje con
Animator y malla humanoide, qué clip usa cada estado del Animator Controller y de qué modelo viene.
El editor de UE (``humanoid_retarget.py``) crea después un AnimSequence por estado en el esqueleto
del personaje, emparejando los huesos por su nombre humano.
"""

from __future__ import annotations

from typing import Any

from ..unity.yaml_parser import UnityBinaryAssetError, load_unity_file, ref_guid
from .context import ConversionContext


def human_bones(info: Any) -> dict[str, str]:
    """{nombre humano: hueso} de un modelo con rig Humanoid (animationType 3)."""
    imp = info.importer
    if int(imp.get("animationType", 0) or 0) != 3:
        return {}
    human = ((imp.get("humanDescription") or {}).get("human")) or []
    return {str(h.get("humanName")): str(h.get("boneName")) for h in human
            if isinstance(h, dict) and h.get("humanName") and h.get("boneName")}


def controller_states(ctx: ConversionContext, controller_path: str) -> list[dict[str, Any]]:
    """Estados del Animator Controller con el modelo del que sale su clip."""
    try:
        doc = load_unity_file(ctx.project.root / controller_path)
    except (OSError, UnityBinaryAssetError):
        return []
    states = []
    for st in doc.by_type("AnimatorState"):
        guid = ref_guid(st.get("m_Motion"))
        info = ctx.project.guids.get(guid) if guid else None
        if info is None:
            continue
        states.append({"name": str(st.get("m_Name") or ""), "source_model": info.path,
                       "source_category": info.category})
    return states


def _nodes(node: dict[str, Any]):
    yield node
    for c in node.get("children", []):
        yield from _nodes(c)


def retarget_jobs(ctx: ConversionContext, prefabs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs = []
    for p in prefabs:
        root = p.get("root")
        if not root:
            continue
        animator = next((c for n in _nodes(root) for c in n.get("components", []) if c.get("type") == "Animator"),
                        None)
        ctrl = (animator or {}).get("controller") or {}
        if not ctrl.get("unity_path"):
            continue
        target = next((c.get("mesh") for n in _nodes(root) for c in n.get("components", [])
                       if c.get("type") == "SkeletalMesh" and (c.get("mesh") or {}).get("kind") == "model"), None)
        if not target:
            continue
        tinfo = ctx.project.guids.get(target.get("guid"))
        if tinfo is None or not human_bones(tinfo):
            continue
        states = []
        for st in controller_states(ctx, ctrl["unity_path"]):
            sinfo = next((a for a in ctx.project.guids.of_category("model") if a.path == st["source_model"]), None)
            if sinfo is None or not human_bones(sinfo):
                continue  # sólo clips de modelos humanoides (los .anim genéricos van por anim_clips)
            states.append({"state": st["name"], "source_model": sinfo.path,
                           "source_folder": ctx.naming.model_folder(sinfo.path),
                           "source_human": human_bones(sinfo)})
        if states:
            jobs.append({
                "prefab": p.get("unity_path"),
                "blueprint": p.get("ue_blueprint_path"),
                "target_model": tinfo.path,
                "target_folder": ctx.naming.model_folder(tinfo.path),
                "target_human": human_bones(tinfo),
                "states": states,
            })
    return jobs
