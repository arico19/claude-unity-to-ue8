"""Comprobación previa a la publicación y ``Steam/checklist.md``.

Valida ``steam.json``, las imágenes de la tienda (``Steam/store/``), los iconos de logros
(``Steam/achievements/``) y que la integración esté aplicada, y escribe una lista de tareas con
los valores exactos que hay que introducir en el panel de Steamworks.

Los tamaños son los que pide Steamworks (revisión de 2024 de las cápsulas). Si Valve los cambia,
se pueden sobrescribir en ``steam.json`` > ``store`` > ``asset_sizes``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import config as steam_config
from .images import image_info, png_has_alpha
from .integrate import required_plugins

# clave -> (descripción, ancho, alto, obligatorio)
STORE_ASSETS: dict[str, tuple[str, int, int, bool]] = {
    "header_capsule": ("Cápsula de cabecera (Store > Graphical Assets)", 920, 430, True),
    "small_capsule": ("Cápsula pequeña", 462, 174, True),
    "main_capsule": ("Cápsula principal", 1232, 706, True),
    "vertical_capsule": ("Cápsula vertical", 748, 896, True),
    "library_capsule": ("Cápsula de biblioteca", 600, 900, True),
    "library_header": ("Cabecera de biblioteca", 920, 430, True),
    "library_hero": ("Héroe de biblioteca (sin texto ni logo)", 3840, 1240, True),
    "library_logo": ("Logo de biblioteca (PNG transparente, 1280 de ancho o 720 de alto)", 1280, 720, True),
    "page_background": ("Fondo de la página de la tienda", 1438, 810, False),
}
MIN_SCREENSHOTS = 5
ACHIEVEMENT_ICON = 256
IMAGE_EXTS = (".png", ".jpg", ".jpeg")


def _find(folder: Path, stem: str) -> Path | None:
    for ext in IMAGE_EXTS:
        p = folder / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def check_store_assets(store: Path, sizes: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    assets = dict(STORE_ASSETS)
    for key, wh in (sizes or {}).items():
        if key in assets and isinstance(wh, (list, tuple)) and len(wh) == 2:
            desc, _w, _h, req = assets[key]
            assets[key] = (desc, int(wh[0]), int(wh[1]), req)
    for key, (desc, w, h, required) in assets.items():
        path = _find(store, key)
        if path is None:
            if required:
                issues.append(("error", f"Falta {desc}: Steam/store/{key}.png ({w}x{h})."))
            continue
        info = image_info(path)
        if info is None:
            issues.append(("error", f"{path.name}: no es un PNG/JPG válido."))
            continue
        fmt, iw, ih = info
        if key == "library_logo":
            if fmt != "png" or not png_has_alpha(path):
                issues.append(("error", f"{path.name}: el logo de biblioteca debe ser PNG con transparencia."))
            if iw != w and ih != h:
                issues.append(("error", f"{path.name}: {iw}x{ih}; debe medir {w} de ancho o {h} de alto."))
        elif (iw, ih) != (w, h):
            issues.append(("error", f"{path.name}: {iw}x{ih}, Steam pide {w}x{h}."))
    shots_dir = store / "screenshots"
    shots = sorted(p for p in shots_dir.glob("*") if p.suffix.lower() in IMAGE_EXTS) if shots_dir.exists() else []
    if len(shots) < MIN_SCREENSHOTS:
        issues.append(("error", f"Hay {len(shots)} capturas en Steam/store/screenshots; Steam pide al menos "
                                f"{MIN_SCREENSHOTS} (1920x1080, 16:9, del juego real)."))
    for p in shots:
        info = image_info(p)
        if info is None:
            issues.append(("error", f"screenshots/{p.name}: no es un PNG/JPG válido."))
            continue
        _f, iw, ih = info
        if iw < 1920 or abs(iw / ih - 16 / 9) > 0.01:
            issues.append(("warning", f"screenshots/{p.name}: {iw}x{ih}; se recomienda 1920x1080 o mayor en 16:9."))
    return issues


def check_achievement_icons(icons: Path, achievements: list[dict[str, Any]]) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    for a in achievements:
        for key, label in (("icon", "desbloqueado"), ("icon_locked", "bloqueado (gris)")):
            name = a.get(key) or (f"{a['id']}.png" if key == "icon" else f"{a['id']}_locked.png")
            path = icons / name
            if not path.exists():
                issues.append(("error", f"Logro {a['id']}: falta el icono {label} Steam/achievements/{name} "
                                        f"({ACHIEVEMENT_ICON}x{ACHIEVEMENT_ICON})."))
                continue
            info = image_info(path)
            if info is None or info[1:] != (ACHIEVEMENT_ICON, ACHIEVEMENT_ICON):
                got = f"{info[1]}x{info[2]}" if info else "formato no válido"
                issues.append(("error", f"Logro {a['id']}: {name} es {got}; debe ser "
                                        f"{ACHIEVEMENT_ICON}x{ACHIEVEMENT_ICON} PNG/JPG."))
    return issues


def check_integration(root: Path, cfg: dict[str, Any]) -> list[tuple[str, str]]:
    import json

    issues: list[tuple[str, str]] = []
    ups = sorted(root.glob("*.uproject"))
    if not ups:
        return [("error", f"No hay .uproject en {root}.")]
    up = json.loads(ups[0].read_text("utf-8"))
    enabled = {p.get("Name") for p in up.get("Plugins", []) if p.get("Enabled")}
    missing = [p for p in required_plugins(cfg) if p not in enabled]
    if missing:
        issues.append(("error", f"Plugins sin activar: {', '.join(missing)}. Ejecuta `unity2ue steam integrate`."))
    ini = root / "Config" / "DefaultEngine.ini"
    if not ini.exists() or f"SteamDevAppId={cfg['app_id']}" not in ini.read_text("utf-8", errors="replace"):
        issues.append(("error", "DefaultEngine.ini no tiene el AppID de steam.json. Ejecuta `unity2ue steam integrate`."))
    if not (root / "Source" / ups[0].stem / "Steam" / "SteamIntegrationSubsystem.h").exists():
        issues.append(("error", "Falta Source/<Módulo>/Steam/SteamIntegrationSubsystem.h. Ejecuta `unity2ue steam integrate`."))
    # Código traducido que aún llama a Steamworks.NET
    src = root / "Source" / ups[0].stem / "Unity"
    if src.exists():
        for f in sorted(src.rglob("*.cpp")):
            text = f.read_text("utf-8", errors="replace")
            if "SteamUserStats." in text or "SteamFriends." in text or "SteamManager.Initialized" in text:
                issues.append(("warning", f"{f.relative_to(root)}: aún contiene llamadas de Steamworks.NET; usa "
                                          "USteamIntegrationSubsystem (ver skill unity-api-a-unreal)."))
    return issues


def run_checks(ue_project: str | Path, cfg: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    root = Path(ue_project)
    cfg = cfg or steam_config.load(root)
    sdir = steam_config.steam_dir(root)
    store_cfg = cfg.get("store") or {}
    issues = steam_config.validate(cfg)
    issues += check_integration(root, cfg)
    issues += check_store_assets(sdir / store_cfg.get("assets_dir", "store"), store_cfg.get("asset_sizes"))
    issues += check_achievement_icons(sdir / store_cfg.get("achievement_icons_dir", "achievements"),
                                      cfg.get("achievements") or [])
    return issues


# ---------------------------------------------------------------------- checklist

def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def checklist_markdown(root: Path, cfg: dict[str, Any], issues: list[tuple[str, str]]) -> str:
    module = sorted(root.glob("*.uproject"))[0].stem if list(root.glob("*.uproject")) else "MiJuego"
    app = cfg["app_id"]
    errors = [m for s, m in issues if s == "error"]
    warnings = [m for s, m in issues if s == "warning"]
    out = [
        f"# Publicación en Steam: {cfg.get('game_name') or module} (AppID {app})",
        "",
        "Generado por `python -m unity2ue steam check`. Vuelve a ejecutarlo tras cada cambio.",
        "",
        f"**Estado:** {len(errors)} errores, {len(warnings)} avisos.",
        "",
    ]
    if errors or warnings:
        out += ["## Problemas detectados", ""]
        out += [f"- ❌ {m}" for m in errors] + [f"- ⚠️ {m}" for m in warnings] + [""]

    out += [
        "## 1. Cuenta y aplicación (una sola vez)",
        "",
        "- [ ] Cuenta de Steamworks creada, formularios fiscales y bancarios completados (https://partner.steamgames.com).",
        "- [ ] Tasa de Steam Direct pagada y AppID asignado; ponlo en `Steam/steam.json` > `app_id`.",
        "- [ ] Cuenta de compilación (builder) con permiso *Edit App Metadata* + *Publish App Changes To Steam* "
        "y Steam Guard activado; ponla en `builder_account` (la contraseña la pide steamcmd, nunca se guarda).",
        "",
        "## 2. SteamPipe (App Admin > SteamPipe > Depots)",
        "",
        "| Plataforma | Depot | Sistema operativo | Opción de lanzamiento (Installation > General) |",
        "|---|---:|---|---|",
    ]
    for plat, pcfg in (cfg.get("platforms") or {}).items():
        os_name = steam_config.PLATFORMS.get(plat, ("?",))[0]
        exe = f"{module}.exe" if plat == "Win64" else (f"{module}.sh" if plat == "Linux" else f"{module}.app")
        out.append(f"| {plat} | {pcfg.get('depot_id', '?')} | {os_name} | `{exe}` |")
    out += [
        "",
        "- [ ] Crea los depots con esos números y márcalos con su sistema operativo.",
        "- [ ] Crea la opción de lanzamiento de cada plataforma con el ejecutable de la tabla.",
        f"- [ ] Crea la rama `{cfg.get('set_live_branch') or 'beta'}` (Builds > Manage Branches) con contraseña para probar.",
        "- [ ] Windows: en *Installation > Redistributables* marca *Visual C++ Redist 2015-2022* y *DirectX* "
        "(así no hace falta el instalador de prerrequisitos de UE).",
        "- [ ] Publica los cambios (Publish > Prepare for Publishing).",
        "",
    ]

    ach = cfg.get("achievements") or []
    stats = cfg.get("stats") or []
    boards = cfg.get("leaderboards") or []
    if ach or stats:
        out += ["## 3. Estadísticas y logros (Stats & Achievements)", ""]
    if stats:
        out += ["| API Name | Tipo | Por defecto | Mín | Máx | Sólo incrementa | Nombre |", "|---|---|---:|---:|---:|---|---|"]
        for s in stats:
            out.append(f"| `{s['id']}` | {s.get('type', 'int').upper()} | {s.get('default', 0)} | "
                       f"{s.get('min', '')} | {s.get('max', '')} | {'sí' if s.get('increment_only') else 'no'} | "
                       f"{_md_escape(s.get('display_name', s['id']))} |")
        out.append("")
    if ach:
        langs = (cfg.get("store") or {}).get("languages") or ["english"]
        out += ["| API Name | Nombre | Descripción | Oculto | Iconos |", "|---|---|---|---|---|"]
        for a in ach:
            name = " / ".join(_md_escape(steam_config.localized(a.get("name"), lang)) for lang in langs)
            desc = " / ".join(_md_escape(steam_config.localized(a.get("description"), lang)) for lang in langs)
            out.append(f"| `{a['id']}` | {name} | {desc} | {'sí' if a.get('hidden') else 'no'} | "
                       f"`{a.get('icon', a['id'] + '.png')}`, `{a.get('icon_locked', a['id'] + '_locked.png')}` |")
        out += ["", f"- [ ] Crea cada logro con su API Name exacto e iconos de Steam/achievements/ ({ACHIEVEMENT_ICON}x{ACHIEVEMENT_ICON}).",
                "- [ ] Publica los cambios: sin publicar, `UnlockAchievement` devuelve false.", ""]
    if boards:
        out += ["## 4. Marcadores (Stats & Achievements > Leaderboards)", "",
                "| Nombre | Orden | Formato |", "|---|---|---|"]
        for b in boards:
            out.append(f"| `{b['id']}` | {b.get('sort', 'descending')} | {b.get('display', 'numeric')} |")
        out.append("")
    if cfg.get("rich_presence"):
        out += ["## 5. Presencia enriquecida (Community > Rich Presence)", "",
                "- [ ] Sube los ficheros de `Steam/richpresence/*.vdf` (uno por idioma).", ""]
    cloud = cfg.get("cloud") or {}
    if cloud.get("enabled"):
        patterns = ", ".join(f"`{p}`" for p in cloud.get("save_patterns") or ["*.sav"])
        out += [
            "## 6. Steam Cloud (Steam Cloud > Auto-Cloud, sin código)",
            "",
            "Las partidas guardadas con `UGameplayStatics::SaveGameToSlot` en un juego empaquetado van a:",
            "",
            "| SO | Raíz | Subdirectorio | Patrón |",
            "|---|---|---|---|",
            f"| Windows | `WinAppDataLocal` | `{module}/Saved/SaveGames` | {patterns} |",
            f"| Linux | `LinuxHome` | `.config/Epic/{module}/Saved/SaveGames` | {patterns} |",
            f"| macOS | `MacAppSupport` | `Epic/{module}/Saved/SaveGames` | {patterns} |",
            "",
            "- [ ] Activa Steam Cloud, pon una cuota (p.ej. 100 MB / 100 ficheros) y añade las rutas (Root Overrides "
            "para Linux/macOS a partir de la raíz de Windows).",
            "",
        ]
    if cfg.get("dlc"):
        out += ["## 7. DLC", ""] + [f"- [ ] DLC `{d.get('name', '')}` (AppID {d.get('app_id')}): página de tienda, "
                                     "depot propio si trae contenido, y comprueba `IsDlcInstalled` en el juego."
                                     for d in cfg["dlc"]] + [""]
    out += [
        "## 8. Página de la tienda",
        "",
        "- [ ] Imágenes en `Steam/store/` con los tamaños exactos (`steam check` las valida):",
    ]
    out += [f"  - `{k}.png` — {d} — {w}x{h}{'' if req else ' (opcional)'}" for k, (d, w, h, req) in STORE_ASSETS.items()]
    out += [
        f"- [ ] Al menos {MIN_SCREENSHOTS} capturas 1920x1080 en `Steam/store/screenshots/` (las de `Unity2UE/play` sirven de base).",
        "- [ ] Tráiler (MP4/H.264, 1920x1080, sin pantallas de logos largas al principio).",
        f"- [ ] Descripción corta ({len((cfg.get('store') or {}).get('short_description') or '')}/300) y larga, "
        "etiquetas, géneros, idiomas con su nivel de soporte (interfaz/audio/subtítulos) y requisitos del sistema.",
        "- [ ] Clasificación por edades (cuestionario IARC) y encuesta de contenido para adultos.",
        "- [ ] Envía la página a revisión y publícala como *Próximamente* cuanto antes (mínimo 2 semanas antes del "
        "lanzamiento) para acumular listas de deseados.",
        "",
        "## 9. Build y revisión",
        "",
        "```bash",
        f"python -m unity2ue steam build {root}          # empaqueta en Shipping",
        f"python -m unity2ue steam upload {root}         # sube a la rama {cfg.get('set_live_branch') or 'beta'}",
        "```",
        "",
        "- [ ] Prueba la build descargándola desde Steam (rama beta): logros, overlay (Mayús+Tab), guardado en la nube, "
        "mando y Steam Deck (1280x800, texto legible, sin teclado obligatorio).",
        "- [ ] Envía la build a revisión (Release > Request Review); Valve tarda unos días.",
        "- [ ] Pasa la build a la rama `default` en *Builds* y pulsa **Release** el día del lanzamiento.",
        "",
    ]
    return "\n".join(out)


def write_checklist(ue_project: str | Path, cfg: dict[str, Any] | None = None) -> tuple[Path, list[tuple[str, str]]]:
    root = Path(ue_project)
    cfg = cfg or steam_config.load(root)
    issues = run_checks(root, cfg)
    path = steam_config.steam_dir(root) / "checklist.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(checklist_markdown(root, cfg, issues), encoding="utf-8")
    return path, issues
