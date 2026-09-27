"""Informe de conversión (Markdown + JSON) con las tareas pendientes agrupadas."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import ConversionConfig
from .unity.project import UnityProject

SEVERITY_TITLES = {
    "error": "Errores",
    "manual": "Tareas manuales / para agentes de Claude",
    "warning": "Avisos",
    "info": "Información",
}


def write_report(out: Path, project: UnityProject, cfg: ConversionConfig, stats: dict[str, Any],
                 issues: list[dict[str, str]]) -> Path:
    module = cfg.module_name
    lines = [
        f"# Informe de conversión Unity → Unreal Engine {cfg.engine_version}",
        "",
        f"- **Proyecto Unity:** `{project.root}`",
        f"- **Versión de Unity:** {project.unity_version or 'desconocida'}",
        f"- **Render pipeline:** {project.render_pipeline}",
        f"- **Módulo UE:** `{module}`  ·  **Contenido:** `{cfg.content_root}`",
        "",
        "## Resumen",
        "",
        "| Elemento | Cantidad |",
        "|---|---:|",
    ]
    for k, v in stats.items():
        if isinstance(v, dict):
            v = ", ".join(f"{a}: {b}" for a, b in v.items()) or "0"
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## Próximos pasos",
        "",
        "1. Traducir los cuerpos de los scripts C# pendientes (`Unity2UE/scripts.json`) con `/convertir-scripts`.",
        "2. Compilar el módulo: `Unity2UE_Import.bat` (Windows) o `./Unity2UE_Import.sh` (Linux/macOS).",
        "3. El mismo script lanza `unity2ue_import/run_all.py` dentro del editor: importa assets, crea",
        "   materiales maestros e instancias, Blueprints de prefabs y niveles.",
        "4. Revisar `Saved/Logs` y `Unity2UE/import_log.json` (generado por el editor).",
        "5. Resolver las tareas manuales listadas abajo (UI → UMG, Animator → AnimBP, partículas → Niagara...).",
        "",
    ]
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for i in issues:
        grouped[i["severity"]][i["source"]].append(i["message"])
    for sev in ("error", "manual", "warning", "info"):
        if sev not in grouped:
            continue
        total = sum(len(v) for v in grouped[sev].values())
        lines += [f"## {SEVERITY_TITLES[sev]} ({total})", ""]
        for source in sorted(grouped[sev]):
            msgs = grouped[sev][source]
            uniq = list(dict.fromkeys(msgs))
            if len(uniq) == 1:
                suffix = f" (×{len(msgs)})" if len(msgs) > 1 else ""
                lines.append(f"- `{source}`: {uniq[0]}{suffix}")
            else:
                lines.append(f"- `{source}`:")
                lines += [f"  - {m}" for m in uniq]
        lines.append("")
    path = out / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (out / "report.json").write_text(json.dumps({"stats": stats, "issues": issues}, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    return path
