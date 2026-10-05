"""Configuración de Steam del juego: ``<DestinoUE>/Steam/steam.json``.

El fichero lo crea ``unity2ue steam init`` y lo edita el usuario. Ninguna contraseña se guarda aquí:
steamcmd la pide (y el código de Steam Guard) la primera vez y luego reutiliza la sesión.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from . import CONFIG_NAME, STEAM_DIR

# Plataformas de UE que Steam distribuye -> (SO del depot en Steamworks, subcarpeta que crea -archive)
PLATFORMS = {
    "Win64": ("windows", "Windows"),
    "Linux": ("linux", "Linux"),
    "Mac": ("macos", "Mac"),
}
STAT_TYPES = ("int", "float", "avgrate")
LEADERBOARD_SORT = ("descending", "ascending")
LEADERBOARD_DISPLAY = ("numeric", "time_seconds", "time_milliseconds")
# Identificadores de la API de Steam: letras, dígitos y _ (los marcadores admiten espacios).
API_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

DEFAULTS: dict[str, Any] = {
    "app_id": 480,  # 480 = Spacewar, la app de pruebas pública de Valve
    "game_name": "",
    "builder_account": "",
    "steamcmd": "",
    "set_live_branch": "beta",
    "build_description": "",
    "networking": False,
    "relaunch_in_steam": False,
    "platforms": {"Win64": {"depot_id": 481, "config": "Shipping"}},
    "achievements": [],
    "stats": [],
    "leaderboards": [],
    "rich_presence": {},
    "dlc": [],
    "cloud": {"enabled": True, "save_patterns": ["*.sav"]},
    "store": {
        "short_description": "",
        "languages": ["english", "spanish"],
        "assets_dir": "store",
        "achievement_icons_dir": "achievements",
    },
}


def steam_dir(ue_project: str | Path) -> Path:
    return Path(ue_project) / STEAM_DIR


def config_path(ue_project: str | Path) -> Path:
    return steam_dir(ue_project) / CONFIG_NAME


def _merge(base: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("platforms", "rich_presence"):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(ue_project: str | Path) -> dict[str, Any]:
    path = config_path(ue_project)
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. Créalo con: python -m unity2ue steam init {ue_project}")
    return _merge(DEFAULTS, json.loads(path.read_text("utf-8")))


def save(ue_project: str | Path, cfg: dict[str, Any]) -> Path:
    path = config_path(ue_project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def localized(value: Any, lang: str = "english") -> str:
    """Los textos pueden ser una cadena o un dict por idioma de Steam ("english", "spanish"...)."""
    if isinstance(value, dict):
        return str(value.get(lang) or next(iter(value.values()), ""))
    return str(value or "")


def validate(cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """Errores de la configuración como (severidad, mensaje). Severidad: error | warning."""
    issues: list[tuple[str, str]] = []

    def err(msg: str) -> None:
        issues.append(("error", msg))

    def warn(msg: str) -> None:
        issues.append(("warning", msg))

    app_id = cfg.get("app_id")
    if not isinstance(app_id, int) or app_id <= 0:
        err("app_id debe ser el número de la aplicación en Steamworks.")
    elif app_id == 480:
        warn("app_id es 480 (Spacewar, la app de pruebas de Valve): pon el AppID real antes de subir builds.")
    if not cfg.get("platforms"):
        err("No hay plataformas en 'platforms' (p.ej. {\"Win64\": {\"depot_id\": 1234561}}).")
    depots = set()
    for plat, pcfg in (cfg.get("platforms") or {}).items():
        if plat not in PLATFORMS:
            err(f"Plataforma desconocida '{plat}' (válidas: {', '.join(PLATFORMS)}).")
        depot = (pcfg or {}).get("depot_id")
        if not isinstance(depot, int) or depot <= 0:
            err(f"{plat}: falta depot_id (número del depot en Steamworks > SteamPipe > Depots).")
        elif depot in depots:
            err(f"{plat}: depot_id {depot} repetido; cada plataforma necesita su propio depot.")
        else:
            depots.add(depot)
            if isinstance(app_id, int) and app_id != 480 and depot == app_id:
                warn(f"{plat}: el depot_id coincide con el AppID; normalmente el primer depot es AppID+1.")
        if (pcfg or {}).get("config", "Shipping") not in ("Shipping", "Development", "Test"):
            err(f"{plat}: config debe ser Shipping, Test o Development.")
    branch = (cfg.get("set_live_branch") or "").strip()
    if branch.lower() == "default":
        err("set_live_branch no puede ser 'default': Steam sólo permite publicar en la rama por defecto "
            "desde el panel de Steamworks. Usa una rama beta y pásala a default a mano.")

    seen: set[str] = set()
    for a in cfg.get("achievements") or []:
        aid = a.get("id", "")
        if not API_NAME_RE.match(aid):
            err(f"Logro '{aid}': el identificador sólo admite letras, dígitos y _.")
        if aid in seen:
            err(f"Logro '{aid}' repetido.")
        seen.add(aid)
        if not localized(a.get("name")):
            warn(f"Logro '{aid}': falta el nombre visible ('name').")
        if not localized(a.get("description")):
            warn(f"Logro '{aid}': falta la descripción.")
    seen.clear()
    for s in cfg.get("stats") or []:
        sid = s.get("id", "")
        if not API_NAME_RE.match(sid):
            err(f"Estadística '{sid}': el identificador sólo admite letras, dígitos y _.")
        if sid in seen:
            err(f"Estadística '{sid}' repetida.")
        seen.add(sid)
        if s.get("type", "int") not in STAT_TYPES:
            err(f"Estadística '{sid}': type debe ser {', '.join(STAT_TYPES)}.")
    for lb in cfg.get("leaderboards") or []:
        if not lb.get("id"):
            err("Hay un marcador sin 'id'.")
        if lb.get("sort", "descending") not in LEADERBOARD_SORT:
            err(f"Marcador '{lb.get('id')}': sort debe ser {', '.join(LEADERBOARD_SORT)}.")
        if lb.get("display", "numeric") not in LEADERBOARD_DISPLAY:
            err(f"Marcador '{lb.get('id')}': display debe ser {', '.join(LEADERBOARD_DISPLAY)}.")
    for lang, tokens in (cfg.get("rich_presence") or {}).items():
        for token in tokens:
            if not token.startswith("#"):
                err(f"Presencia ({lang}): el token '{token}' debe empezar por '#'.")
    short = cfg.get("store", {}).get("short_description") or ""
    if len(short) > 300:
        err(f"La descripción corta tiene {len(short)} caracteres (máximo 300).")
    elif not short:
        warn("Falta store.short_description (descripción corta de la tienda, máx. 300 caracteres).")
    for d in cfg.get("dlc") or []:
        if not isinstance(d.get("app_id"), int) or d["app_id"] <= 0:
            err(f"DLC '{d.get('name', '?')}': falta app_id numérico.")
    return issues
