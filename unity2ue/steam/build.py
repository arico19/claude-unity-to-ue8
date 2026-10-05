"""Empaquetado del juego para Steam con BuildCookRun (Unreal Automation Tool)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import config as steam_config


def uat_path(ue_root: Path) -> Path:
    name = "RunUAT.bat" if os.name == "nt" else "RunUAT.sh"
    return Path(ue_root) / "Engine" / "Build" / "BatchFiles" / name


def find_engine(explicit: str | None) -> Path:
    """Como ``ue_runner.find_ue_root`` pero válido también en Linux/macOS (busca RunUAT)."""
    for cand in (explicit, os.environ.get("UE_ROOT")):
        if cand and uat_path(Path(cand)).exists():
            return Path(cand)
    from ..ue_runner import find_ue_root

    return find_ue_root(explicit)


def archive_dir(ue_project: Path, platform: str) -> Path:
    """Carpeta que se sube a Steam (BuildCookRun añade la subcarpeta Windows/Linux/Mac)."""
    return steam_config.steam_dir(ue_project) / "build" / platform / steam_config.PLATFORMS[platform][1]


def buildcookrun_command(ue_root: Path, uproject: Path, platform: str, configuration: str = "Shipping") -> list[str]:
    archive = steam_config.steam_dir(uproject.parent) / "build" / platform
    cmd = [
        str(uat_path(ue_root)), "BuildCookRun",
        f"-project={uproject.resolve()}",
        "-noP4", "-utf8output", "-unattended",
        f"-platform={platform}", f"-clientconfig={configuration}",
        "-build", "-cook", "-allmaps", "-stage", "-pak", "-iostore", "-compressed",
        "-archive", f"-archivedirectory={archive.resolve()}",
    ]
    if configuration == "Shipping":
        cmd.append("-nodebuginfo")
    if platform == "Win64":
        cmd.append("-prereqs")
    return cmd


def write_dev_appid(ue_project: Path, platform: str, app_id: int) -> Path | None:
    """steam_appid.txt junto al ejecutable: sólo para probar builds no-Shipping fuera de Steam."""
    out = archive_dir(ue_project, platform)
    if not out.exists():
        return None
    path = out / "steam_appid.txt"
    path.write_text(f"{app_id}\n", encoding="utf-8")
    return path


def build(ue_project: str | Path, *, ue_root: str | None = None, platforms: list[str] | None = None,
          cfg: dict[str, Any] | None = None, log=print, dry_run: bool = False) -> int:
    root = Path(ue_project).resolve()
    cfg = cfg or steam_config.load(root)
    uprojects = sorted(root.glob("*.uproject"))
    if not uprojects:
        raise FileNotFoundError(f"No hay .uproject en {root}")
    engine = Path(ue_root) if dry_run and ue_root else find_engine(ue_root)
    targets = platforms or list(cfg["platforms"])
    logs = steam_config.steam_dir(root) / "output"
    logs.mkdir(parents=True, exist_ok=True)
    for plat in targets:
        if plat not in cfg["platforms"]:
            log(f"{plat} no está en steam.json > platforms")
            return 1
        conf = cfg["platforms"][plat].get("config", "Shipping")
        cmd = buildcookrun_command(engine, uprojects[0], plat, conf)
        log(f"[steam build] {plat} {conf}")
        log("  " + " ".join(cmd))
        if dry_run:
            continue
        log_path = logs / f"build_{plat}.log"
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=root)
        if proc.returncode != 0:
            tail = log_path.read_text("utf-8", errors="replace").splitlines()[-25:]
            log(f"  Falló el empaquetado ({log_path}):\n    " + "\n    ".join(tail))
            return proc.returncode
        out = archive_dir(root, plat)
        if conf != "Shipping":
            write_dev_appid(root, plat, cfg["app_id"])
        log(f"  OK -> {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(build(sys.argv[1]))
