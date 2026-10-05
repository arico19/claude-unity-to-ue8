"""Detecta el uso de Steamworks en el proyecto Unity (Steamworks.NET y Facepunch.Steamworks).

Se extraen los identificadores que aparecen como literales en el código para rellenar
``steam.json``: AppID (``steam_appid.txt``), logros, estadísticas, marcadores y tokens de
presencia enriquecida. Lo que se construye en tiempo de ejecución (ids concatenados) no se ve:
el informe dice en qué ficheros mirar.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import ConversionConfig
from ..unity.project import UnityProject

_STR = r'"([^"\\]+)"'
ACHIEVEMENT_PATTERNS = [
    re.compile(r"SteamUserStats\.(?:SetAchievement|ClearAchievement|GetAchievement)\(\s*" + _STR),
    re.compile(r"new\s+(?:Steamworks\.Data\.)?Achievement\(\s*" + _STR),  # Facepunch
    re.compile(r"IndicateAchievementProgress\(\s*" + _STR),
]
STAT_PATTERN = re.compile(r"SteamUserStats\.(?:SetStat(?:Int|Float)?|AddStat|GetStat(?:Int|Float)?)\(\s*" + _STR + r"\s*(?:,\s*([^),]+))?")
LEADERBOARD_PATTERN = re.compile(
    r"(?:FindOrCreateLeaderboard(?:Async)?|FindLeaderboard(?:Async)?)\(\s*" + _STR + r"(?:\s*,\s*([\w.]+))?(?:\s*,\s*([\w.]+))?"
)
PRESENCE_PATTERN = re.compile(r'SetRichPresence\(\s*"steam_display"\s*,\s*"(#[^"]+)"')
DLC_PATTERN = re.compile(r"BIsDlcInstalled\(\s*(?:new\s+AppId_t\()?\s*\(?(?:AppId_t\))?\s*(\d+)")

PACKAGES = {
    "com.rlabrecque.steamworks.net": "Steamworks.NET",
    "com.facepunch.steamworks": "Facepunch.Steamworks",
}


def _stat_type(arg: str | None, src: str, name: str) -> str:
    if arg:
        a = arg.strip()
        if re.match(r"^-?\d+\.\d*f?$|^-?\d+f$", a) or a.endswith("f"):
            return "float"
        decl = re.search(r"\b(float|double|int|long|uint)\s+" + re.escape(a) + r"\b", src)
        if decl and decl.group(1) in ("float", "double"):
            return "float"
    if re.search(r"(SetStatFloat|GetStatFloat)\(\s*\"" + re.escape(name), src):
        return "float"
    return "int"


def _sort(token: str | None) -> str:
    return "ascending" if token and "ascending" in token.lower() else "descending"


def _display(token: str | None) -> str:
    t = (token or "").lower()
    if "milli" in t:
        return "time_milliseconds"
    if "second" in t or "time" in t:
        return "time_seconds"
    return "numeric"


def detect_unity_steam(project_path: str | Path, cfg: ConversionConfig | None = None) -> dict[str, Any]:
    cfg = cfg or ConversionConfig()
    p = UnityProject(Path(project_path))
    result: dict[str, Any] = {
        "sdk": None, "app_id": None, "achievements": [], "stats": [], "leaderboards": [],
        "rich_presence_tokens": [], "dlc_app_ids": [], "files": [],
        "game_name": (p.player_settings or {}).get("product_name") or "",
    }
    appid_file = p.root / "steam_appid.txt"
    if appid_file.exists():
        text = appid_file.read_text("utf-8", errors="replace").strip()
        if text.isdigit():
            result["app_id"] = int(text)
    for pkg in p.packages:
        if pkg in PACKAGES:
            result["sdk"] = PACKAGES[pkg]

    achievements: dict[str, None] = {}
    stats: dict[str, str] = {}
    boards: dict[str, dict[str, str]] = {}
    tokens: dict[str, None] = {}
    dlc: dict[int, None] = {}
    for a in p.guids.of_category("script"):
        if cfg.is_excluded(a.path):
            continue
        try:
            src = a.abs_path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        uses = False
        if re.search(r"\busing Steamworks\b|Steamworks\.", src):
            uses = True
            if result["sdk"] is None:
                result["sdk"] = "Facepunch.Steamworks" if "SteamClient.Init" in src or "Steamworks.Data" in src \
                    else "Steamworks.NET"
        for pat in ACHIEVEMENT_PATTERNS:
            for m in pat.finditer(src):
                achievements[m.group(1)] = None
                uses = True
        for m in STAT_PATTERN.finditer(src):
            name = m.group(1)
            t = _stat_type(m.group(2), src, name)
            if stats.get(name) != "float":
                stats[name] = t
            uses = True
        for m in LEADERBOARD_PATTERN.finditer(src):
            boards.setdefault(m.group(1), {"id": m.group(1), "sort": _sort(m.group(2)), "display": _display(m.group(3))})
            uses = True
        for m in PRESENCE_PATTERN.finditer(src):
            tokens[m.group(1)] = None
            uses = True
        for m in DLC_PATTERN.finditer(src):
            dlc[int(m.group(1))] = None
            uses = True
        if uses:
            result["files"].append(a.path)

    result["achievements"] = list(achievements)
    result["stats"] = [{"id": k, "type": v} for k, v in stats.items()]
    result["leaderboards"] = list(boards.values())
    result["rich_presence_tokens"] = list(tokens)
    result["dlc_app_ids"] = list(dlc)
    return result


def config_from_detection(det: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Rellena una configuración nueva con lo detectado en Unity (sin pisar lo que ya tenga)."""
    cfg = dict(base)
    if det.get("app_id"):
        cfg["app_id"] = det["app_id"]
        cfg["platforms"] = {"Win64": {"depot_id": det["app_id"] + 1 if det["app_id"] != 480 else 481,
                                      "config": "Shipping"}}
    if det.get("game_name") and not cfg.get("game_name"):
        cfg["game_name"] = det["game_name"]
    if det.get("achievements") and not cfg.get("achievements"):
        cfg["achievements"] = [
            {"id": a, "name": {"english": "", "spanish": ""}, "description": {"english": "", "spanish": ""},
             "hidden": False, "icon": f"{a}.png", "icon_locked": f"{a}_locked.png"}
            for a in det["achievements"]
        ]
    if det.get("stats") and not cfg.get("stats"):
        cfg["stats"] = [{"id": s["id"], "type": s["type"], "default": 0, "display_name": s["id"]} for s in det["stats"]]
    if det.get("leaderboards") and not cfg.get("leaderboards"):
        cfg["leaderboards"] = det["leaderboards"]
    if det.get("rich_presence_tokens") and not cfg.get("rich_presence"):
        cfg["rich_presence"] = {lang: {t: "" for t in det["rich_presence_tokens"]} for lang in ("english", "spanish")}
    if det.get("dlc_app_ids") and not cfg.get("dlc"):
        cfg["dlc"] = [{"app_id": d, "name": ""} for d in det["dlc_app_ids"]]
    return cfg
