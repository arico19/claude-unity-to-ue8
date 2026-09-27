"""Interfaz de línea de comandos: ``python -m unity2ue <comando>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConversionConfig


def _cmd_analyze(args: argparse.Namespace) -> int:
    from .analyze import analyze_project, format_analysis

    cfg = ConversionConfig.load(args.config)
    data = analyze_project(args.unity_project, cfg)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(format_analysis(data))
    if args.output:
        Path(args.output).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


def _cmd_convert(args: argparse.Namespace) -> int:
    from .pipeline import convert_project

    cfg = ConversionConfig.load(
        args.config,
        project_name=args.name,
        engine_version=args.engine_version,
        content_root=args.content_root,
        scenes=args.scene or None,
    )
    if args.no_cpp:
        cfg.generate_cpp = False
    if args.only_referenced:
        cfg.include_unreferenced_assets = False
    result = convert_project(args.unity_project, args.output, cfg)
    print()
    print(f"Proyecto UE generado: {result.uproject}")
    print(f"Informe: {result.out_dir / 'Unity2UE' / 'report.md'}")
    for sev, n in sorted(result.stats.get("issues", {}).items()):
        print(f"  {sev}: {n}")
    return 1 if result.stats.get("issues", {}).get("error") and args.strict else 0


def _cmd_scripts(args: argparse.Namespace) -> int:
    """Lista el estado de la cola de traducción C# -> C++."""
    out = Path(args.ue_project)
    data = json.loads((out / "Unity2UE" / "scripts.json").read_text("utf-8"))
    rows = []
    for s in data["scripts"]:
        status = s["status"]
        if status == "stub" and s.get("header"):
            h = out / s["header"]
            if h.exists() and "UNITY2UE_STATUS: TRANSLATED" in h.read_text("utf-8"):
                status = "translated"
        rows.append((status, s["unity_path"], s.get("header") or "-"))
    if args.pending:
        rows = [r for r in rows if r[0] == "stub"]
    for status, path, header in rows:
        print(f"{status:<11} {path}  ->  {header}")
    pending = sum(1 for r in rows if r[0] == "stub")
    print(f"\n{pending} pendientes de traducción")
    return 0


def _cmd_ue(args: argparse.Namespace) -> int:
    """Pasos dentro de Unreal sobre un proyecto ya convertido."""
    from .ue_runner import UERunner, find_ue_root

    runner = UERunner(Path(args.ue_project), find_ue_root(args.ue_root))
    print(f"Unreal Engine: {runner.ue}")
    steps = {s.strip() for s in args.steps.split(",")} if args.steps else None
    return runner.run_all(build=not args.skip_build, screenshots=not args.no_screenshots, steps=steps)


def _cmd_full(args: argparse.Namespace) -> int:
    """Conversión completa: convert + compilar + importar + verificar + capturas."""
    from .ue_runner import UERunner, find_ue_root

    ue_root = find_ue_root(args.ue_root)  # falla pronto si no hay motor
    print(f"Unreal Engine: {ue_root}\n")
    code = _cmd_convert(args)
    if code:
        return code
    runner = UERunner(Path(args.output), ue_root)
    return runner.run_all(build=not args.skip_build, screenshots=not args.no_screenshots)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="unity2ue", description="Conversor de proyectos Unity a Unreal Engine 5.8")
    parser.add_argument("--version", action="version", version=f"unity2ue {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="Inventario y riesgos del proyecto Unity (no escribe nada)")
    a.add_argument("unity_project")
    a.add_argument("--json", action="store_true", help="Salida en JSON")
    a.add_argument("-o", "--output", help="Guardar el análisis JSON en un fichero")
    a.add_argument("--config")
    a.set_defaults(func=_cmd_analyze)

    c = sub.add_parser("convert", help="Convierte el proyecto Unity en un proyecto UE 5.8")
    c.add_argument("unity_project")
    c.add_argument("output", help="Carpeta del proyecto Unreal de destino")
    c.add_argument("--name", help="Nombre del proyecto/módulo UE (por defecto ConvertedProject)")
    c.add_argument("--engine-version", help="EngineAssociation del .uproject (por defecto 5.8)")
    c.add_argument("--content-root", help="Carpeta de contenido destino (por defecto /Game/Unity)")
    c.add_argument("--scene", action="append", help="Convertir sólo esta escena (repetible)")
    c.add_argument("--no-cpp", action="store_true", help="No generar esqueletos C++")
    c.add_argument("--only-referenced", action="store_true", help="Sólo assets referenciados por escenas/prefabs")
    c.add_argument("--strict", action="store_true", help="Código de salida 1 si hay errores")
    c.add_argument("--config", help="JSON con ConversionConfig")
    c.set_defaults(func=_cmd_convert)

    s = sub.add_parser("scripts", help="Estado de la traducción de scripts en un proyecto UE generado")
    s.add_argument("ue_project")
    s.add_argument("--pending", action="store_true")
    s.set_defaults(func=_cmd_scripts)

    u = sub.add_parser("ue", help="Compila, importa, verifica y captura un proyecto UE ya convertido")
    u.add_argument("ue_project")
    u.add_argument("--ue-root", help="Carpeta de UE 5.8 (por defecto: UE_ROOT o Epic Launcher)")
    u.add_argument("--skip-build", action="store_true", help="No compilar el módulo C++")
    u.add_argument("--no-screenshots", action="store_true", help="No abrir el editor para hacer capturas")
    u.add_argument("--steps", help="Sólo estos pasos, separados por comas: build,import,verify,screenshots,play")
    u.set_defaults(func=_cmd_ue)

    f = sub.add_parser("full", parents=[c], add_help=False, conflict_handler="resolve",
                       help="Todo de una vez: convert + compilar + importar en UE + verificar + capturas")
    f.add_argument("--ue-root", help="Carpeta de UE 5.8 (por defecto: UE_ROOT o Epic Launcher)")
    f.add_argument("--skip-build", action="store_true", help="No compilar el módulo C++")
    f.add_argument("--no-screenshots", action="store_true", help="No abrir el editor para hacer capturas")
    f.set_defaults(func=_cmd_full)

    g = sub.add_parser("gui", help="Aplicación de Windows: elegir proyecto Unity y destino y convertir todo")
    g.set_defaults(func=lambda _a: __import__("unity2ue.gui", fromlist=["main"]).main())

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
