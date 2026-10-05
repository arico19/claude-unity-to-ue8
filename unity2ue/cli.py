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


def _print_issues(issues: list[tuple[str, str]]) -> None:
    for sev, msg in issues:
        print(f"  {'ERROR' if sev == 'error' else 'aviso'}: {msg}")


def _cmd_steam(args: argparse.Namespace) -> int:
    """Kit de publicación en Steam sobre el proyecto UE generado."""
    from .steam import config as steam_config

    ue = Path(args.ue_project)
    if args.steam_cmd == "init":
        from .steam.init import init_steam

        try:
            path, _cfg = init_steam(ue, unity_project=args.unity, app_id=args.app_id, game_name=args.name,
                                    force=args.force)
        except FileExistsError as exc:
            print(exc)
            return 1
        print(f"Configuración creada: {path}")
        print("Revísala (AppID, depots, textos de logros) y ejecuta: python -m unity2ue steam integrate", ue)
        return 0

    try:
        cfg = steam_config.load(ue)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    if args.steam_cmd in ("integrate", "publish"):
        from .steam.integrate import integrate

        changed = integrate(ue, cfg)
        print("Integración de Steam aplicada" + (":" if changed else " (sin cambios)."))
        for c in changed:
            print(f"  {c}")
        if args.steam_cmd == "integrate":
            return 0

    if args.steam_cmd in ("check", "publish"):
        from .steam.check import write_checklist

        path, issues = write_checklist(ue, cfg)
        errors = sum(1 for s, _ in issues if s == "error")
        _print_issues(issues)
        print(f"\n{errors} errores, {len(issues) - errors} avisos. Lista de tareas: {path}")
        if args.steam_cmd == "check":
            return 1 if errors else 0
        if errors and not args.force:
            print("Corrige los errores (o usa --force para empaquetar y subir igualmente).")
            return 1

    if args.steam_cmd in ("build", "publish") and not getattr(args, "skip_build", False):
        from .steam.build import build

        plats = [p.strip() for p in args.platforms.split(",")] if args.platforms else None
        code = build(ue, ue_root=args.ue_root, platforms=plats, cfg=cfg, dry_run=args.dry_run)
        if code or args.steam_cmd == "build":
            return code

    if args.steam_cmd in ("upload", "publish"):
        from .steam.upload import upload

        return upload(ue, cfg=cfg, preview=args.preview, description=args.desc, branch=args.branch,
                      account=args.account, dry_run=args.dry_run)
    return 0


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

    st = sub.add_parser("steam", help="Publicar en Steam: init, integrate, check, build, upload, publish")
    st_sub = st.add_subparsers(dest="steam_cmd", required=True)
    si = st_sub.add_parser("init", help="Crea Steam/steam.json (detecta logros/stats de Steamworks.NET en Unity)")
    si.add_argument("ue_project")
    si.add_argument("--unity", help="Proyecto Unity original del que leer AppID, logros, estadísticas y marcadores")
    si.add_argument("--app-id", type=int, help="AppID de Steamworks")
    si.add_argument("--name", help="Nombre del juego")
    si.add_argument("--force", action="store_true", help="Sobrescribir steam.json si ya existe")
    st_sub.add_parser("integrate", help="Activa OnlineSubsystemSteam y genera el subsistema C++ de Steam") \
        .add_argument("ue_project")
    st_sub.add_parser("check", help="Valida configuración, imágenes de la tienda e iconos; escribe Steam/checklist.md") \
        .add_argument("ue_project")
    sb = st_sub.add_parser("build", help="Empaqueta el juego (BuildCookRun) para cada plataforma de steam.json")
    sup = st_sub.add_parser("upload", help="Genera el script de SteamPipe y sube la build con steamcmd")
    sp = st_sub.add_parser("publish", help="Todo: integrate + check + build + upload a la rama beta")
    for parser_ in (sb, sp):
        parser_.add_argument("--ue-root", help="Carpeta de UE 5.8 (por defecto: UE_ROOT o Epic Launcher)")
        parser_.add_argument("--platforms", help="Sólo estas plataformas, separadas por comas (Win64,Linux)")
    for parser_ in (sup, sp):
        parser_.add_argument("--branch", help="Rama en la que publicar (por defecto set_live_branch de steam.json)")
        parser_.add_argument("--desc", help="Descripción de la build en Steamworks")
        parser_.add_argument("--account", help="Cuenta de compilación de Steam (por defecto builder_account)")
        parser_.add_argument("--preview", action="store_true", help="Simula la subida en SteamPipe sin subir nada")
    sp.add_argument("--skip-build", action="store_true", help="Subir la última build empaquetada sin recompilar")
    sp.add_argument("--force", action="store_true", help="Seguir aunque `check` encuentre errores")
    for parser_ in (sb, sup, sp):
        parser_.add_argument("ue_project")
        parser_.add_argument("--dry-run", action="store_true", help="Mostrar los comandos sin ejecutarlos")
    st.set_defaults(func=_cmd_steam)

    g = sub.add_parser("gui", help="Aplicación de Windows: elegir proyecto Unity y destino y convertir todo")
    g.set_defaults(func=lambda _a: __import__("unity2ue.gui", fromlist=["main"]).main())

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
