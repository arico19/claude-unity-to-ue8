"""Orquestación de la conversión Unity -> Unreal Engine 5.8.

Fases:
  1. Scripts C#   -> esqueletos C++ (Source/<Modulo>/Unity) + cola de traducción.
  2. Prefabs      -> descripciones de Blueprint (orden topológico por anidamiento).
  3. Escenas      -> descripciones de nivel.
  4. Materiales   -> Material Instances sobre materiales maestros.
  5. Assets       -> copia a Unity2UE/SourceAssets + tareas de importación.
  6. Animators    -> JSON de máquinas de estado (para Animation Blueprints).
  7. Proyecto UE  -> .uproject, módulo, Config/*.ini, scripts Python del editor.
  8. Informe      -> Unity2UE/report.md + report.json
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from . import __version__
from .config import ConversionConfig
from .convert.anim_clips import convert_anim_clip
from .convert.animators import convert_animator
from .convert.context import ConversionContext, ScriptInfo
from .convert.cpp_gen import CppGenerator, build_plans
from .convert.csharp import CSFile, parse_csharp_file
from .convert.data_assets import convert_data_asset
from .convert.hierarchy import convert_prefab, convert_scene, iter_nodes
from .convert.materials import convert_material
from .naming import sanitize
from .report import write_report
from .ue.project_gen import generate_project, input_mappings, run_scripts
from .unity.assets import AssetInfo
from .unity.project import UnityProject
from .unity.yaml_parser import UnityBinaryAssetError

IMPORTABLE = {
    "texture": {".png", ".jpg", ".jpeg", ".tga", ".psd", ".tif", ".tiff", ".exr", ".hdr", ".bmp"},
    "model": {".fbx", ".obj", ".gltf", ".glb"},
    "audio": {".wav", ".ogg", ".flac", ".aif", ".aiff"},
    "font": {".ttf", ".otf"},
    "video": {".mp4", ".mov", ".webm", ".avi", ".m4v"},
}

Logger = Callable[[str], None]


@dataclass
class ConversionResult:
    out_dir: Path
    uproject: Path
    stats: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, str]] = field(default_factory=list)


def _json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")


def _json_default(o: Any) -> Any:
    if isinstance(o, set):
        return sorted(o)
    if isinstance(o, Path):
        return o.as_posix()
    raise TypeError(f"No serializable: {type(o)}")


def _topo_sort(prefabs: dict[str, dict[str, Any]]) -> list[str]:
    """Ordena prefabs para que los anidados/base se creen antes que quien los usa."""
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(p: str) -> None:
        if state.get(p) == 2:
            return
        if state.get(p) == 1:  # ciclo: lo rompemos
            return
        state[p] = 1
        data = prefabs.get(p) or {}
        deps = list(data.get("dependencies", []))
        if data.get("variant_of") and data["variant_of"].get("unity_path"):
            deps.append(data["variant_of"]["unity_path"])
        for d in deps:
            if d in prefabs and d != p:
                visit(d)
        state[p] = 2
        order.append(p)

    for p in sorted(prefabs):
        visit(p)
    return order


class Converter:
    def __init__(self, project_path: str | Path, cfg: ConversionConfig, log: Logger = print) -> None:
        self.cfg = cfg
        self.log = log
        self.project = UnityProject(Path(project_path))
        self.ctx = ConversionContext(self.project, cfg)

    # ------------------------------------------------------------------ utilidades
    def _assets(self, category: str) -> list[AssetInfo]:
        return [a for a in self.project.guids.of_category(category) if not self.cfg.is_excluded(a.path)]

    def _safe(self, fn: Callable[[], Any], source: str) -> Any:
        try:
            return fn()
        except UnityBinaryAssetError as exc:
            self.ctx.error(source, str(exc))
        except Exception as exc:  # noqa: BLE001 - un asset roto no debe parar la conversión
            self.ctx.error(source, f"Fallo al convertir: {type(exc).__name__}: {exc}")
        return None

    # ------------------------------------------------------------------ fases
    def phase_scripts(self, out: Path) -> dict[str, Any]:
        files: dict[str, CSFile] = {}
        for a in self._assets("script"):
            parsed = self._safe(lambda a=a: parse_csharp_file(a.abs_path), a.path)
            if parsed is not None:
                files[a.path] = parsed
        plans, project_types = build_plans(files, self.ctx.script_class_name)
        gen = CppGenerator(self.cfg.module_name, project_types)
        src_root = out / "Source" / self.cfg.module_name
        queue = []
        by_path = {a.path: a for a in self._assets("script")}
        kinds = Counter()
        for plan in plans:
            kinds[plan.kind] += 1
            asset = by_path.get(plan.unity_path)
            entry: dict[str, Any] = {"unity_path": plan.unity_path, "kind": plan.kind, "status": "skipped"}
            if plan.kind in ("editor", "empty"):
                msg = "Script de editor: no se convierte (reescribir como Editor Utility/plugin si hace falta)." \
                    if plan.kind == "editor" else "Fichero sin tipos."
                self.ctx.info(plan.unity_path, msg)
                queue.append(entry)
                continue
            if self.cfg.generate_cpp:
                header, cpp = self._safe(lambda plan=plan: gen.generate(plan), plan.unity_path) or (None, None)
                if header is None:
                    continue
                h_path = src_root / plan.header_rel
                c_path = h_path.with_suffix(".cpp")
                existing = h_path.read_text("utf-8") if h_path.exists() else ""
                if "UNITY2UE_STATUS: TRANSLATED" in existing:
                    # Nunca sobrescribir código ya traducido por el agente o a mano.
                    entry["status"] = "translated"
                else:
                    h_path.parent.mkdir(parents=True, exist_ok=True)
                    # Sólo si cambian: una fecha nueva obliga a UE a recompilar lo que los incluye.
                    for path, text in ((h_path, header), (c_path, cpp)):
                        if not path.exists() or path.read_text("utf-8", errors="replace") != text:
                            path.write_text(text, "utf-8")
                    entry["status"] = "stub"
                entry["header"] = h_path.relative_to(out).as_posix()
                entry["source"] = c_path.relative_to(out).as_posix()
            main = plan.main_type
            entry["cpp_class"] = project_types[main.name].cpp_name if main and main.name in project_types else None
            entry["unity_class"] = main.name if main else None
            entry["methods"] = sum(len(t.methods) for t in plan.file.all_types())
            queue.append(entry)
            if asset is not None and main is not None:
                cpp_name = project_types.get(main.name)
                self.ctx.scripts[asset.guid] = ScriptInfo(
                    guid=asset.guid,
                    unity_path=plan.unity_path,
                    unity_class=main.name,
                    base_class=main.base or "",
                    cpp_class=(cpp_name.cpp_name[1:] if cpp_name else plan.cpp_name),
                    kind=plan.kind,
                    header=plan.header_rel,
                    field_map=plan.field_maps.get(main.name, {}),
                )
        pending = [q for q in queue if q["status"] == "stub"]
        if pending:
            self.ctx.manual("scripts", f"{len(pending)} scripts con cuerpos pendientes de traducir "
                                       "(usa /convertir-scripts en Claude Code).")
        data = {"module": self.cfg.module_name, "scripts": queue}
        _json(out / "Unity2UE" / "scripts.json", data)
        return {"scripts": len(plans), "script_kinds": dict(kinds), "pending_translation": len(pending)}

    def phase_prefabs(self, out: Path) -> dict[str, Any]:
        prefabs: dict[str, dict[str, Any]] = {}
        for a in self._assets("prefab"):
            data = self._safe(lambda a=a: convert_prefab(self.ctx, a.path), a.path)
            if data is not None:
                prefabs[a.path] = data
        order = _topo_sort(prefabs)
        _json(out / "Unity2UE" / "blueprints.json", {"order": order, "prefabs": [prefabs[p] for p in order]})
        return {"prefabs": len(prefabs)}

    def phase_scenes(self, out: Path) -> dict[str, Any]:
        scenes = self._assets("scene")
        if self.cfg.scenes:
            wanted = set(self.cfg.scenes)
            scenes = [s for s in scenes if s.path in wanted or PurePosixPath(s.path).stem in wanted]
        levels = []
        ui: list[dict[str, Any]] = []
        for a in scenes:
            self.log(f"  escena {a.path}")
            data = self._safe(lambda a=a: convert_scene(self.ctx, a.path), a.path)
            if data is None:
                continue
            fname = f"{sanitize(PurePosixPath(a.path).stem)}.json"
            _json(out / "Unity2UE" / "levels" / fname, data)
            levels.append({"unity_path": a.path, "file": f"levels/{fname}", "ue_level_path": data["ue_level_path"]})
            for n in iter_nodes(data["roots"]):
                if any(c.get("type") == "UICanvas" for c in n.get("components", [])):
                    ui.append({"scene": a.path, "canvas": n})
        _json(out / "Unity2UE" / "levels.json", {"levels": levels})
        if ui:
            _json(out / "Unity2UE" / "ui.json", {"canvases": ui})
        return {"scenes": len(levels), "ui_canvases": len(ui)}

    def phase_materials(self, out: Path) -> tuple[dict[str, Any], dict[str, dict[str, bool]]]:
        mats = []
        texture_usage: dict[str, dict[str, bool]] = {}
        for a in self._assets("material"):
            if not self.cfg.include_unreferenced_assets and a.guid not in self.ctx.referenced_guids:
                continue
            data = self._safe(lambda a=a: convert_material(self.ctx, a.path), a.path)
            if data is None:
                continue
            mats.append(data)
            for tex in (data.get("textures") or {}).values():
                ref = tex.get("texture") or {}
                if ref.get("guid"):
                    use = texture_usage.setdefault(ref["guid"], {"normal": False, "linear": False})
                    use["normal"] |= bool(tex.get("is_normal"))
                    use["linear"] |= bool(tex.get("linear"))
        _json(out / "Unity2UE" / "materials.json", {"materials": mats})
        return {"materials": len(mats)}, texture_usage

    def phase_assets(self, out: Path, texture_usage: dict[str, dict[str, bool]]) -> dict[str, Any]:
        staging = out / "Unity2UE" / "SourceAssets"
        tasks: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        ffmpeg = shutil.which("ffmpeg")
        n = self.ctx.naming
        for category in ("texture", "model", "audio", "font", "video"):
            for a in self._assets(category):
                if not self.cfg.include_unreferenced_assets and a.guid not in self.ctx.referenced_guids \
                        and a.guid not in self.ctx.models:
                    continue
                ext = a.abs_path.suffix.lower()
                name = n.imported_name(a.path)
                rel_stage = PurePosixPath(a.path).parent / f"{name}{ext}"
                dst = staging / rel_stage
                convert_to = None
                if ext not in IMPORTABLE[category]:
                    if category == "audio" and ext == ".mp3" and ffmpeg:
                        convert_to = ".wav"
                    else:
                        hint = {"model": "exporta el modelo a FBX desde la aplicación de origen",
                                "audio": "convierte a WAV (instala ffmpeg para hacerlo automáticamente)",
                                "texture": "convierte a PNG"}.get(category, "convierte a un formato soportado")
                        self.ctx.manual(a.path, f"Formato {ext} no importable en UE: {hint}.")
                        continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                if convert_to:
                    dst = dst.with_suffix(convert_to)
                    rel_stage = rel_stage.with_suffix(convert_to)
                    res = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(a.abs_path), str(dst)],
                                         check=False, capture_output=True)
                    if res.returncode != 0:
                        self.ctx.error(a.path, "ffmpeg no pudo convertir el audio a WAV.")
                        continue
                else:
                    shutil.copy2(a.abs_path, dst)
                task: dict[str, Any] = {
                    "type": category,
                    "unity_path": a.path,
                    "guid": a.guid,
                    "file": f"Unity2UE/SourceAssets/{rel_stage.as_posix()}",
                    "destination_path": n.folder_for(a.path),
                    "destination_name": name,
                }
                imp = a.importer
                if category == "texture":
                    ttype = int(imp.get("textureType", 0) or 0)
                    usage = texture_usage.get(a.guid, {})
                    is_normal = ttype == 1 or usage.get("normal", False)
                    srgb = bool(int(imp.get("sRGBTexture", 1) if imp.get("sRGBTexture") is not None else 1))
                    settings = imp.get("textureSettings") or {}
                    task.update({
                        "normal_map": is_normal,
                        "srgb": srgb and not is_normal and not usage.get("linear", False),
                        "flip_green_channel": is_normal,  # Unity: OpenGL (Y+), UE: DirectX (Y-)
                        "sprite": ttype == 8,
                        "ui": ttype == 2,
                        "mipmaps": bool(int((imp.get("mipmaps") or {}).get("enableMipMap", 1) or 0)),
                        "max_size": imp.get("maxTextureSize"),
                        "wrap": {0: "Wrap", 1: "Clamp", 2: "Mirror"}.get(int(settings.get("m_WrapU", 0) or 0), "Wrap"),
                        "filter": {0: "Nearest", 1: "Bilinear", 2: "Trilinear"}.get(
                            int(settings.get("m_FilterMode", 1) or 0) if settings.get("m_FilterMode") is not None else 1,
                            "Bilinear"),
                    })
                    if ttype == 8:
                        task["sprite_pixels_per_unit"] = imp.get("spritePixelsToUnits", 100)
                elif category == "model":
                    meshes = imp.get("meshes") or {}
                    anim_type = int(imp.get("animationType", 0) or 0)
                    usage = self.ctx.models.get(a.guid)
                    skeletal = bool(usage["skeletal"]) if usage else anim_type in (2, 3)
                    use_file_scale = int(meshes.get("useFileScale", 1) or 0)
                    task.update({
                        "destination_path": n.model_folder(a.path),
                        "skeletal": skeletal,
                        "import_animations": skeletal and bool(int(imp.get("importAnimation", 1) or 0)),
                        "uniform_scale": float(meshes.get("globalScale", 1) or 1),
                        "generate_lightmap_uvs": bool(int(meshes.get("generateSecondaryUV", 0) or 0)),
                        "combine_meshes": a.mesh_count <= 1,
                        "humanoid": anim_type == 3,
                        "clips": [
                            {"name": c.get("name"), "first_frame": c.get("firstFrame"), "last_frame": c.get("lastFrame"),
                             "loop": bool(int(c.get("loopTime", 0) or 0))}
                            for c in ((imp.get("animations") or {}).get("clipAnimations") or [])
                            if isinstance(c, dict)
                        ],
                    })
                    if not use_file_scale:
                        self.ctx.manual(a.path, "El modelo usa 'Use File Scale = off' en Unity: revisar la escala en UE.")
                    if task["clips"]:
                        self.ctx.manual(a.path, f"{len(task['clips'])} clips definidos en Unity sobre el FBX: "
                                                "recortarlos en UE (AnimSequence > Crop) o exportarlos por separado.")
                    if anim_type == 3:
                        self.ctx.manual(a.path, "Rig humanoide: crear IK Rig + IK Retargeter hacia el esqueleto de UE (Manny/Quinn).")
                elif category == "audio":
                    task["loop_hint"] = bool(int(imp.get("loadInBackground", 0) or 0))
                tasks.append(task)
                counts[category] += 1
        _json(out / "Unity2UE" / "assets.json", {"imports": tasks})
        return {f"assets_{k}": v for k, v in counts.items()}

    def phase_animators(self, out: Path) -> dict[str, Any]:
        items = []
        for a in self._assets("animator"):
            if a.path.lower().endswith(".controller"):
                data = self._safe(lambda a=a: convert_animator(self.ctx, a.path), a.path)
                if data:
                    items.append(data)
        clips = [a.path for a in self._assets("animation") if a.path.lower().endswith(".anim")]
        converted = []
        for c in clips:
            data = self._safe(lambda c=c: convert_anim_clip(self.ctx, c), c)
            if data:
                converted.append(data)
        if converted:
            _json(out / "Unity2UE" / "anim_clips.json", {"clips": converted})
        if len(converted) < len(clips):
            self.ctx.manual("animations", f"{len(clips) - len(converted)} clips .anim sin curvas de huesos "
                                          "(propiedades/eventos): recrear como Level Sequence o Timeline.")
        if items or clips:
            _json(out / "Unity2UE" / "animators.json", {"controllers": items, "anim_clips": clips})
        return {"animator_controllers": len(items), "anim_clips": len(clips), "anim_clips_converted": len(converted)}

    def phase_data_assets(self, out: Path) -> dict[str, Any]:
        """Ficheros .asset de ScriptableObjects del proyecto -> DataAssets."""
        items = []
        for a in self._assets("asset"):
            data = self._safe(lambda a=a: convert_data_asset(self.ctx, a.path), a.path)
            if data:
                items.append(data)
        if items:
            _json(out / "Unity2UE" / "data_assets.json", {"data_assets": items})
        return {"data_assets": len(items)}

    def detect_features(self) -> None:
        pk = set(self.project.packages)
        flags = {
            "com.unity.shadergraph": "Shader Graph: recrear los shaders como materiales de UE.",
            "com.unity.visualeffectgraph": "VFX Graph: recrear como sistemas Niagara.",
            "com.unity.timeline": "Timeline: recrear como Level Sequences (Sequencer).",
            "com.unity.cinemachine": "Cinemachine: usar CameraComponent + SpringArm / Gameplay Cameras.",
            "com.unity.probuilder": "ProBuilder: exportar mallas a FBX o rehacer con Modeling Tools.",
            "com.unity.addressables": "Addressables: equivalente en UE = Asset Manager / Primary Assets / chunks.",
            "com.unity.netcode.gameobjects": "Netcode: migrar a replicación nativa de UE.",
            "com.unity.inputsystem": "Input System: mapear .inputactions a Enhanced Input (ver input_actions en settings.json).",
            "com.unity.ai.navigation": "AI Navigation: usar NavMeshBoundsVolume + RecastNavMesh.",
            "com.unity.textmeshpro": "TextMeshPro: usar UTextBlock (UMG) / TextRender con fuentes importadas.",
            "com.unity.ugui": "uGUI: recrear interfaces en UMG (Widget Blueprints).",
        }
        for pkg, msg in flags.items():
            if pkg in pk:
                self.ctx.manual(f"package:{pkg}", msg)
        if self.project.serialization_mode not in (None, 2):
            self.ctx.error("ProjectSettings/EditorSettings.asset",
                           "Asset Serialization no es 'Force Text': los assets binarios no se pueden leer.")
        if self.project.render_pipeline == "HDRP":
            self.ctx.info("render_pipeline", "HDRP usa unidades físicas: revisa light_intensity en la configuración.")

    # ------------------------------------------------------------------ run
    def run(self, out_dir: str | Path) -> ConversionResult:
        out = Path(out_dir).resolve()
        (out / "Unity2UE").mkdir(parents=True, exist_ok=True)
        p = self.project
        self.log(f"Proyecto Unity: {p.root} (Unity {p.unity_version or '?'}, {p.render_pipeline}, {len(p.guids)} assets)")
        stats: dict[str, Any] = {}
        self.detect_features()
        self.log("[1/7] Scripts C# -> C++")
        stats.update(self.phase_scripts(out))
        self.log("[2/7] Prefabs -> Blueprints")
        stats.update(self.phase_prefabs(out))
        self.log("[3/7] Escenas -> Niveles")
        stats.update(self.phase_scenes(out))
        self.log("[4/7] Materiales")
        mat_stats, tex_usage = self.phase_materials(out)
        stats.update(mat_stats)
        self.log("[5/7] Assets (texturas, modelos, audio, fuentes)")
        stats.update(self.phase_assets(out, tex_usage))
        self.log("[6/7] Animator Controllers")
        stats.update(self.phase_animators(out))
        self.log("      Datos (ScriptableObject .asset -> DataAsset)")
        stats.update(self.phase_data_assets(out))

        self.log("[7/7] Proyecto Unreal Engine")
        levels = json.loads((out / "Unity2UE" / "levels.json").read_text("utf-8"))["levels"]
        default_map = None
        level_by_path = {lv["unity_path"]: lv["ue_level_path"] for lv in levels}
        for s in p.build_scenes:
            if s["enabled"] and s["path"] in level_by_path:
                default_map = level_by_path[s["path"]]
                break
        if default_map is None and levels:
            default_map = levels[0]["ue_level_path"]
        settings = {
            "unity_version": p.unity_version,
            "render_pipeline": p.render_pipeline,
            "tags_and_layers": p.tags_and_layers,
            "physics": p.physics,
            "player": p.player_settings,
            "build_scenes": p.build_scenes,
            "input_actions": input_mappings(p.input_axes),
            "content_root": self.cfg.content_root,
            "module": self.cfg.module_name,
            "default_map": default_map,
        }
        _json(out / "Unity2UE" / "settings.json", settings)
        uses_paper2d = any(self.project.guids.get(g) and self.project.guids.get(g).importer.get("textureType") == 8
                           for g in self.ctx.referenced_guids)
        uproject = generate_project(out, self.cfg, settings=settings, default_map=default_map, uses_paper2d=uses_paper2d)
        run_scripts(out, self.cfg.module_name)

        issues = [i.to_dict() for i in self.ctx.issues]
        stats["issues"] = dict(Counter(i["severity"] for i in issues))
        _json(out / "Unity2UE" / "conversion.json", {
            "tool": "unity2ue", "version": __version__, "config": self.cfg.to_dict(),
            "unity_project": str(p.root), "stats": stats,
        })
        write_report(out / "Unity2UE", p, self.cfg, stats, issues)
        return ConversionResult(out, uproject, stats, issues)


def convert_project(project_path: str | Path, out_dir: str | Path, cfg: ConversionConfig,
                    log: Logger = print) -> ConversionResult:
    return Converter(project_path, cfg, log).run(out_dir)
