"""Análisis previo (sin escribir nada): inventario del proyecto Unity y riesgos de conversión."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .config import ConversionConfig
from .unity import class_ids as C
from .unity.project import UnityProject
from .unity.yaml_parser import UnityBinaryAssetError, ref_guid

# Patrones de API de Unity con coste de migración notable.
API_PATTERNS = {
    "coroutines": r"\bStartCoroutine\b|\bIEnumerator\b",
    "legacy_input": r"\bInput\.(GetAxis|GetKey|GetButton|GetMouseButton)",
    "new_input_system": r"\bInputAction\b|UnityEngine\.InputSystem",
    "physics_queries": r"\bPhysics2?D?\.(Raycast|SphereCast|OverlapSphere|BoxCast|CapsuleCast)",
    "find_calls": r"\bGameObject\.Find|FindObjectOfType|FindObjectsOfType|FindWithTag",
    "send_message": r"\bSendMessage\b|BroadcastMessage",
    "ui": r"UnityEngine\.UI|TMPro",
    "navmesh": r"NavMeshAgent|UnityEngine\.AI",
    "animator": r"\bAnimator\b|SetTrigger|SetFloat|SetBool",
    "scene_management": r"SceneManager\.",
    "player_prefs": r"PlayerPrefs\.",
    "linq": r"using System\.Linq",
    "async_await": r"\basync\b|\bawait\b",
    "reflection": r"System\.Reflection|GetType\(\)\.Get",
    "editor_only": r"UnityEditor|#if UNITY_EDITOR",
    "unsafe_or_native": r"\bunsafe\b|DllImport|NativeArray|Unity\.Jobs|Unity\.Burst",
    "dots_ecs": r"Unity\.Entities|IComponentData|SystemBase|ISystem",
}


def analyze_project(project_path: str | Path, cfg: ConversionConfig | None = None) -> dict[str, Any]:
    cfg = cfg or ConversionConfig()
    p = UnityProject(Path(project_path))
    cats = Counter(a.category for a in p.guids.by_guid.values() if not cfg.is_excluded(a.path))

    component_usage: Counter[str] = Counter()
    script_usage: Counter[str] = Counter()
    binary_files: list[str] = []
    for cat in ("scene", "prefab"):
        for a in p.guids.of_category(cat):
            if cfg.is_excluded(a.path):
                continue
            try:
                doc = p.load(a.path)
            except UnityBinaryAssetError:
                binary_files.append(a.path)
                continue
            except Exception:  # noqa: BLE001
                continue
            for obj in doc:
                if obj.stripped or obj.class_id in (C.GAME_OBJECT, C.PREFAB_INSTANCE):
                    continue
                component_usage[obj.type_name] += 1
                if obj.class_id == C.MONO_BEHAVIOUR:
                    info = p.guids.get(ref_guid(obj.get("m_Script")))
                    script_usage[info.path if info else f"guid:{ref_guid(obj.get('m_Script'))}"] += 1

    api_usage: Counter[str] = Counter()
    lines_of_code = 0
    for a in p.guids.of_category("script"):
        if cfg.is_excluded(a.path):
            continue
        try:
            src = a.abs_path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        lines_of_code += src.count("\n") + 1
        for key, pattern in API_PATTERNS.items():
            if re.search(pattern, src):
                api_usage[key] += 1

    shaders = Counter()
    for a in p.guids.of_category("material"):
        try:
            doc = p.load(a.path)
        except Exception:  # noqa: BLE001
            continue
        for obj in doc:
            if obj.type_name == "Material":
                from .convert.context import ConversionContext
                from .convert.materials import shader_family

                shaders[shader_family(ConversionContext(p, cfg), obj.get("m_Shader"))] += 1

    risks = []
    if p.serialization_mode not in (None, 2) or binary_files:
        risks.append("Serialización binaria detectada: activa Force Text y reserializa (Assets > Reserialize All).")
    if cats.get("shader"):
        risks.append(f"{cats['shader']} shaders/ShaderGraphs personalizados: requieren recreación manual como materiales.")
    if component_usage.get("Terrain"):
        risks.append("Terrain: exportar heightmaps y recrear como Landscape.")
    if api_usage.get("dots_ecs"):
        risks.append("DOTS/ECS: no tiene traducción directa (considerar Mass Entity de UE).")
    if api_usage.get("ui") or component_usage.get("Canvas"):
        risks.append("UI uGUI/TMP: recrear en UMG.")
    other_models = [a.path for a in p.guids.of_category("model") if a.abs_path.suffix.lower() in (".blend", ".max", ".ma", ".mb")]
    if other_models:
        risks.append(f"{len(other_models)} modelos en formato nativo (.blend/.max/.ma): exportar a FBX.")

    return {
        "project": str(p.root),
        "unity_version": p.unity_version,
        "render_pipeline": p.render_pipeline,
        "serialization_mode": {2: "ForceText", 1: "ForceBinary", 0: "Mixed"}.get(p.serialization_mode if p.serialization_mode is not None else -1, "desconocido"),
        "packages": p.packages,
        "asset_counts": dict(sorted(cats.items())),
        "scenes": [a.path for a in p.guids.of_category("scene")],
        "build_scenes": p.build_scenes,
        "component_usage": dict(component_usage.most_common()),
        "script_usage": dict(script_usage.most_common()),
        "api_usage": dict(api_usage.most_common()),
        "shader_families": dict(shaders.most_common()),
        "lines_of_code": lines_of_code,
        "tags_and_layers": p.tags_and_layers,
        "binary_files": binary_files,
        "risks": risks,
    }


def format_analysis(data: dict[str, Any]) -> str:
    out = [
        f"Proyecto: {data['project']}",
        f"Unity {data['unity_version'] or '?'} · {data['render_pipeline']} · serialización {data['serialization_mode']}",
        f"Líneas de C#: {data['lines_of_code']}",
        "",
        "Assets:",
        *[f"  {k:<20} {v}" for k, v in data["asset_counts"].items()],
        "",
        "Componentes usados en escenas/prefabs:",
        *[f"  {k:<28} {v}" for k, v in list(data["component_usage"].items())[:30]],
        "",
        "Uso de APIs de Unity (nº de scripts):",
        *[f"  {k:<20} {v}" for k, v in data["api_usage"].items()],
        "",
        "Shaders:",
        *[f"  {k:<20} {v}" for k, v in data["shader_families"].items()],
        "",
        "Riesgos:",
        *([f"  - {r}" for r in data["risks"]] or ["  (ninguno detectado)"]),
    ]
    return "\n".join(out)
