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


def _floats(text: str | None) -> list[float] | None:
    return [float(v) for v in text.split(",")] if text else None


def _cmd_arma(args: argparse.Namespace) -> int:
    """Cambia el arma que llevan en la mano los personajes (Unity2UE/armas.json)."""
    import json

    project = Path(args.ue_project)
    config = project / "Unity2UE" / "armas.json"
    if args.listar:
        if not config.exists():
            print("Aún no hay armas.json: se crea en la primera importación o al cambiar de arma.")
            return 0
        cfg = json.loads(config.read_text("utf-8"))
        for name, spec in cfg.get("armas", {}).items():
            mark = "*" if name == cfg.get("arma") else " "
            mark = "+" if name in cfg.get("alternativas", []) and mark == " " else mark
            print(f" {mark} {name:<16} {spec.get('malla') or spec.get('fichero') or 'integrada'}")
        print(f"\nPersonajes: {', '.join(cfg.get('personajes', {}))}")
        return 0
    spec: dict = {}
    if args.fichero:
        spec["fichero"] = str(Path(args.fichero).resolve()).replace("\\", "/")
    for key, value in (("posicion", _floats(args.posicion)), ("rotacion", _floats(args.rotacion)),
                       ("boca", _floats(args.boca))):
        if value is not None:
            spec[key] = value
    if args.malla:
        spec["malla"] = args.malla
    if args.alternativa:
        spec["alternativa"] = True
    if args.escala:
        spec["escala"] = _floats(args.escala) if "," in args.escala else float(args.escala)
    if spec and not args.nombre:
        print("Indica el nombre del arma para guardar esos datos.")
        return 2
    from .ue_runner import UERunner, find_ue_root

    runner = UERunner(project, find_ue_root(args.ue_root))
    result = runner.change_weapon(args.nombre, spec)
    entries = [e for e in result.get("entries", []) if e.get("step") == "weapons"]
    for e in entries:
        print(f"  {e['status'].upper():<8} {e['item']} {e.get('message', '')}".rstrip())
    return 0 if entries and not any(e["status"] == "error" for e in entries) else 1


def _cmd_personajes(args: argparse.Namespace) -> int:
    """Crea/actualiza los personajes de Unity2UE/personajes.json y sus armas (editor cerrado)."""
    from .ue_runner import UERunner, find_ue_root

    runner = UERunner(Path(args.ue_project), find_ue_root(args.ue_root))
    data = runner.characters(restore_data=args.restaurar)
    entries = [e for e in data.get("entries", []) if e.get("step") in ("characters", "weapons", "humanoid")]
    for e in entries:
        print(f"  {e['status'].upper():<8} {e['item']} {e.get('message', '')}".rstrip()[:220])
    if args.retratos:
        shots = runner.portraits()
        print(f"\n{len(shots)} retratos en {Path(args.ue_project) / 'Unity2UE' / 'retratos'}")
    return 0 if entries and not any(e["status"] == "error" for e in entries) else 1


def _cmd_retratos(args: argparse.Namespace) -> int:
    from .ue_runner import UERunner, find_ue_root

    shots = UERunner(Path(args.ue_project), find_ue_root(args.ue_root)).portraits()
    print(f"{len(shots)} retratos en {Path(args.ue_project) / 'Unity2UE' / 'retratos'}")
    return 0 if shots else 1


def _cmd_sonido(args: argparse.Namespace) -> int:
    """Pone un sonido tuyo (WAV) en lugar de uno del proyecto y lo reimporta (editor cerrado)."""
    import os
    import shutil

    from .ue_runner import UERunner, find_ue_root

    project = Path(args.ue_project)
    folder = project / "Unity2UE" / "custom_sounds"
    if args.listar or not args.nombre:
        print("Sonidos del proyecto (Unity2UE/custom_sounds):")
        for wav in sorted(folder.glob("*.wav")):
            print(f"  {wav.stem}")
        return 0
    if args.fichero:
        src = Path(args.fichero)
        if src.suffix.lower() != ".wav":
            print("Tiene que ser un .wav (UE no importa mp3); conviértelo antes, p.ej. con Audacity.")
            return 2
        shutil.copyfile(src, folder / f"{args.nombre}.wav")
        print(f"Copiado {src.name} -> {args.nombre}.wav")
    runner = UERunner(project, find_ue_root(args.ue_root))
    runner.sync_editor_scripts()
    os.environ["UNITY2UE_STEPS"] = "extra"
    try:
        data = runner.import_content()
    finally:
        os.environ.pop("UNITY2UE_STEPS", None)
    for e in data.get("entries", []):
        if e.get("step") == "custom_sounds":
            print(f"  {e['status'].upper():<8} {e['item']} {e.get('message', '')}")
    return 0


def _find_blender() -> str | None:
    import glob
    import os
    import shutil

    cands = [os.environ.get("BLENDER", ""), shutil.which("blender") or ""]
    cands += sorted(glob.glob(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Blender Foundation", "*", "blender.exe")), reverse=True)
    return next((c for c in cands if c and os.path.isfile(c)), None)


def _cmd_glb2fbx(args: argparse.Namespace) -> int:
    """GLB/FBX con rig -> FBX para UE con Blender (un hueso raíz, una malla, texturas en PNG)."""
    import subprocess

    blender = _find_blender()
    if blender is None:
        print("No encuentro Blender (instálalo o indica su ruta en la variable BLENDER).")
        return 2
    script = Path(__file__).resolve().parent / "ue_editor" / "unity2ue_import" / "blender_glb_to_fbx.py"
    out = Path(args.salida).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([blender, "-b", "-P", str(script), "--", str(Path(args.entrada).resolve()), str(out),
                           *args.quitar], capture_output=True, text=True, errors="replace")
    for line in proc.stdout.splitlines():
        if line.startswith(("ARMATURE", "ROOTS", "QUITADA", "TEXTURAS", "HEIGHT", "EXPORTED", "NO SE")):
            print("  " + line)
    if not out.exists():
        print(proc.stdout[-2000:] + proc.stderr[-2000:])
        return 1
    print(f"Listo: {out}")
    return 0


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

    w = sub.add_parser("arma", help="Cambia el arma que llevan en la mano los personajes (editor cerrado)")
    w.add_argument("ue_project")
    w.add_argument("nombre", nargs="?", help="Arma de Unity2UE/armas.json (o nueva, con --fichero)")
    w.add_argument("--fichero", help="FBX/GLB/OBJ del arma nueva")
    w.add_argument("--posicion", help="Ajuste respecto al agarre, cm: x,y,z")
    w.add_argument("--rotacion", help="Ajuste respecto al agarre, grados: pitch,yaw,roll")
    w.add_argument("--escala", help="Escala: un número o x,y,z")
    w.add_argument("--boca", help="Boca del cañón en coordenadas de la malla del arma, cm: x,y,z")
    w.add_argument("--malla", help="StaticMesh ya importada en UE (/Game/...) para el arma")
    w.add_argument("--alternativa", action="store_true",
                   help="Prepararla oculta en los personajes para cambiarla en partida (no cambia el arma actual)")
    w.add_argument("--listar", action="store_true", help="Muestra las armas configuradas")
    w.add_argument("--ue-root", help="Carpeta de UE 5.8 (por defecto: UE_ROOT o Epic Launcher)")
    w.set_defaults(func=_cmd_arma)

    pj = sub.add_parser("personajes", help="Crea/actualiza los personajes de Unity2UE/personajes.json (editor cerrado)")
    pj.add_argument("ue_project")
    pj.add_argument("--restaurar", action="store_true",
                    help="Reescribe antes los DataAssets desde Unity (deshace un 'usar_como' que hayas quitado)")
    pj.add_argument("--retratos", action="store_true", help="Al terminar, hace los retratos de comprobación")
    pj.add_argument("--ue-root", help="Carpeta de UE 5.8 (por defecto: UE_ROOT o Epic Launcher)")
    pj.set_defaults(func=_cmd_personajes)

    rt = sub.add_parser("retratos", help="Fotos de lado y de frente de cada personaje armado (pose de disparo)")
    rt.add_argument("ue_project")
    rt.add_argument("--ue-root", help="Carpeta de UE 5.8 (por defecto: UE_ROOT o Epic Launcher)")
    rt.set_defaults(func=_cmd_retratos)

    gf = sub.add_parser("glb2fbx", help="Prepara un GLB/FBX con rig para UE con Blender")
    gf.add_argument("entrada")
    gf.add_argument("salida", help="FBX de salida (sus texturas quedan al lado)")
    gf.add_argument("--quitar", nargs="*", default=[], help="Huesos raíz sobrantes a quitar (p.ej. neutral_bone)")
    gf.set_defaults(func=_cmd_glb2fbx)

    sd = sub.add_parser("sonido", help="Pone tu WAV en lugar de un sonido del proyecto (S_Bloop...) y lo reimporta")
    sd.add_argument("ue_project")
    sd.add_argument("nombre", nargs="?", help="Nombre del sonido (p.ej. S_Disparo_Rifle); sin él, lista los que hay")
    sd.add_argument("fichero", nargs="?", help="Tu fichero .wav (sin él, sólo reimporta los de la carpeta)")
    sd.add_argument("--listar", action="store_true")
    sd.add_argument("--ue-root", help="Carpeta de UE 5.8 (por defecto: UE_ROOT o Epic Launcher)")
    sd.set_defaults(func=_cmd_sonido)

    g = sub.add_parser("gui", help="Aplicación de Windows: elegir proyecto Unity y destino y convertir todo")
    g.set_defaults(func=lambda _a: __import__("unity2ue.gui", fromlist=["main"]).main())

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
