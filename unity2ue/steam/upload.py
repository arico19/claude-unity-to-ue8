"""Subida a Steam con SteamPipe: genera ``app_build_<AppID>.vdf`` y ejecuta steamcmd.

La build se publica en una rama beta (``set_live_branch``); pasarla a ``default`` se hace a mano
en Steamworks (Valve no permite hacerlo desde un script).
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import config as steam_config
from .build import archive_dir
from .vdf import dumps

# Lo que nunca debe acabar en el depot.
EXCLUDE = ["*.pdb", "*.debug", "*.sym", "steam_appid.txt", "Manifest_*.txt", "*/Saved/*"]


def _git_rev(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _version(root: Path) -> str:
    ini = root / "Config" / "DefaultGame.ini"
    if ini.exists():
        for line in ini.read_text("utf-8", errors="replace").splitlines():
            if line.startswith("ProjectVersion="):
                return line.split("=", 1)[1].strip()
    return ""


def app_build_vdf(ue_project: Path, cfg: dict[str, Any], *, preview: bool = False,
                  description: str | None = None, branch: str | None = None) -> str:
    root = Path(ue_project).resolve()
    sdir = steam_config.steam_dir(root)
    if description is None:
        parts = [cfg.get("build_description") or cfg.get("game_name") or root.name, _version(root), _git_rev(root),
                 _dt.datetime.now().strftime("%Y-%m-%d %H:%M")]
        description = " ".join(p for p in parts if p)
    branch = cfg.get("set_live_branch", "") if branch is None else branch
    if branch.strip().lower() == "default":
        raise ValueError("Steam no permite publicar en 'default' desde SteamPipe: usa una rama beta.")
    depots: list[tuple[str, Any]] = []
    for plat, pcfg in cfg["platforms"].items():
        content = archive_dir(root, plat)
        node: list[tuple[str, Any]] = [
            ("FileMapping", {"LocalPath": f"{content.relative_to(sdir / 'build').as_posix()}/*",
                             "DepotPath": ".", "recursive": "1"}),
        ]
        node += [("FileExclusion", pattern) for pattern in EXCLUDE]
        depots.append((str(pcfg["depot_id"]), node))
    return dumps("AppBuild", [
        ("AppID", str(cfg["app_id"])),
        ("Desc", description),
        ("ContentRoot", (sdir / "build").as_posix()),
        ("BuildOutput", (sdir / "output").as_posix()),
        ("SetLive", branch or ""),
        ("Preview", "1" if preview else "0"),
        ("Depots", depots),
    ])


def write_app_build(ue_project: str | Path, cfg: dict[str, Any] | None = None, **kw: Any) -> Path:
    root = Path(ue_project).resolve()
    cfg = cfg or steam_config.load(root)
    path = steam_config.steam_dir(root) / "scripts" / f"app_build_{cfg['app_id']}.vdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(app_build_vdf(root, cfg, **kw), encoding="utf-8")
    return path


def find_steamcmd(cfg: dict[str, Any]) -> Path | None:
    for cand in (cfg.get("steamcmd"), os.environ.get("STEAMCMD")):
        if cand and Path(cand).exists():
            return Path(cand)
    for name in ("steamcmd", "steamcmd.exe", "steamcmd.sh"):
        found = shutil.which(name)
        if found:
            return Path(found)
    sdk = os.environ.get("STEAMWORKS_SDK")
    if sdk:
        for sub in ("builder/steamcmd.exe", "builder_linux/steamcmd.sh", "builder_osx/steamcmd.sh"):
            p = Path(sdk) / "tools" / "ContentBuilder" / sub
            if p.exists():
                return p
    return None


def steamcmd_command(steamcmd: Path, account: str, vdf: Path) -> list[str]:
    return [str(steamcmd), "+login", account, "+run_app_build", str(vdf.resolve()), "+quit"]


def upload(ue_project: str | Path, *, cfg: dict[str, Any] | None = None, preview: bool = False,
           description: str | None = None, branch: str | None = None, account: str | None = None,
           dry_run: bool = False, log=print) -> int:
    root = Path(ue_project).resolve()
    cfg = cfg or steam_config.load(root)
    missing = [p for p in cfg["platforms"] if not archive_dir(root, p).exists()]
    if missing and not preview:
        log(f"No hay build empaquetada para: {', '.join(missing)}. Ejecuta antes `unity2ue steam build`.")
        return 1
    vdf = write_app_build(root, cfg, preview=preview, description=description, branch=branch)
    log(f"Script de SteamPipe: {vdf}")
    account = account or cfg.get("builder_account") or os.environ.get("STEAM_BUILDER_ACCOUNT", "")
    steamcmd = find_steamcmd(cfg)
    if not account:
        log("Falta la cuenta de compilación: pon 'builder_account' en steam.json o usa --account.")
        return 1
    if steamcmd is None:
        log("No se encuentra steamcmd: instálalo (https://developer.valvesoftware.com/wiki/SteamCMD), "
            "ponlo en el PATH o indica su ruta en steam.json > steamcmd / variable STEAMCMD.")
        return 1
    cmd = steamcmd_command(steamcmd, account, vdf)
    log("  " + " ".join(cmd))
    if dry_run:
        return 0
    log("steamcmd pedirá la contraseña y el código de Steam Guard la primera vez (no se guardan aquí).")
    # Sin capturar la salida: steamcmd es interactivo para el inicio de sesión.
    code = subprocess.run(cmd, cwd=steamcmd.parent).returncode
    if code == 0:
        target = branch if branch is not None else cfg.get("set_live_branch")
        log(f"Build subida{' (vista previa, no se ha subido nada)' if preview else ''}"
            f"{f'; publicada en la rama {target}' if target and not preview else ''}.")
    return code
