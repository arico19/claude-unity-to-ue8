"""``unity2ue steam init``: crea ``Steam/steam.json`` y las carpetas de imágenes."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from . import config as steam_config
from .check import ACHIEVEMENT_ICON, MIN_SCREENSHOTS, STORE_ASSETS


def _store_readme() -> str:
    lines = ["Imágenes de la tienda de Steam (las valida `python -m unity2ue steam check`).", "",
             "Nombre del fichero (.png o .jpg) y tamaño exacto:", ""]
    lines += [f"  {k}.png  {w}x{h}  {d}{'' if req else ' (opcional)'}" for k, (d, w, h, req) in STORE_ASSETS.items()]
    lines += ["", f"screenshots/: al menos {MIN_SCREENSHOTS} capturas 1920x1080 del juego.", ""]
    return "\n".join(lines)


def init_steam(ue_project: str | Path, *, unity_project: str | Path | None = None, app_id: int | None = None,
               game_name: str | None = None, force: bool = False, log=print) -> tuple[Path, dict[str, Any]]:
    root = Path(ue_project)
    path = steam_config.config_path(root)
    if path.exists() and not force:
        raise FileExistsError(f"{path} ya existe (usa --force para regenerarlo).")
    cfg = copy.deepcopy(steam_config.DEFAULTS)
    if unity_project:
        from .detect import config_from_detection, detect_unity_steam

        det = detect_unity_steam(unity_project)
        log(f"Unity: SDK {det['sdk'] or 'no detectado'}, AppID {det['app_id'] or '?'}, "
            f"{len(det['achievements'])} logros, {len(det['stats'])} estadísticas, "
            f"{len(det['leaderboards'])} marcadores, {len(det['rich_presence_tokens'])} tokens de presencia")
        for f in det["files"]:
            log(f"  usa Steamworks: {f}")
        cfg = config_from_detection(det, cfg)
    if app_id:
        cfg["app_id"] = app_id
        cfg["platforms"] = {"Win64": {"depot_id": app_id + 1, "config": "Shipping"}}
    if game_name:
        cfg["game_name"] = game_name
    if not cfg["game_name"]:
        ups = sorted(root.glob("*.uproject"))
        cfg["game_name"] = ups[0].stem if ups else root.name
    steam_config.save(root, cfg)
    sdir = steam_config.steam_dir(root)
    store = sdir / cfg["store"]["assets_dir"]
    (store / "screenshots").mkdir(parents=True, exist_ok=True)
    (store / "LEEME.txt").write_text(_store_readme(), encoding="utf-8")
    icons = sdir / cfg["store"]["achievement_icons_dir"]
    icons.mkdir(parents=True, exist_ok=True)
    (icons / "LEEME.txt").write_text(
        f"Iconos de logros {ACHIEVEMENT_ICON}x{ACHIEVEMENT_ICON}: <ID>.png (desbloqueado) y <ID>_locked.png (gris).\n",
        encoding="utf-8")
    return path, cfg
