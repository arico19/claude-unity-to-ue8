"""Integra Steam en el proyecto UE generado (idempotente; ``convert`` lo vuelve a aplicar).

- ``.uproject``: activa OnlineSubsystem, OnlineSubsystemSteam y SteamShared (+ SteamSockets
  si hay multijugador).
- ``Config/DefaultEngine.ini``: bloque marcado con el AppID y el subsistema online.
- ``Source/<Módulo>/<Módulo>.Build.cs``: dependencia de Steamworks en Win64/Linux/Mac.
- ``Source/<Módulo>/Steam/``: ``USteamIntegrationSubsystem`` y ``SteamIds.h`` (constantes de los
  logros, estadísticas y marcadores de ``steam.json``).
- ``Steam/richpresence/*.vdf``: ficheros de localización de presencia para subir a Steamworks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import config as steam_config
from .vdf import dumps

TEMPLATES = Path(__file__).resolve().parent.parent / "ue" / "templates" / "Steam"
BEGIN = ">>> unity2ue steam"
END = "<<< unity2ue steam"


def upsert_block(text: str, block: str, comment: str, anchor: str | None = None) -> str:
    """Sustituye el bloque marcado si existe; si no, lo inserta antes de ``anchor`` (o al final)."""
    start, end = f"{comment} {BEGIN}", f"{comment} {END}"
    pattern = re.compile(r"[ \t]*" + re.escape(start) + r".*?" + re.escape(end) + r"[^\n]*\n?", re.S)
    if pattern.search(text):
        return pattern.sub(lambda _m: block, text, count=1)
    if anchor and anchor in text:
        i = text.rfind(anchor)
        return text[:i] + block + text[i:]
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text else "") + block


def engine_ini_block(cfg: dict[str, Any]) -> str:
    lines = [
        f"; {BEGIN} (generado por `unity2ue steam integrate` desde Steam/steam.json; no editar a mano)",
        "[OnlineSubsystem]",
        "DefaultPlatformService=Steam",
        "",
        "[OnlineSubsystemSteam]",
        "bEnabled=true",
        f"SteamDevAppId={cfg['app_id']}",
        f"bRelaunchInSteam={'true' if cfg.get('relaunch_in_steam') else 'false'}",
    ]
    if cfg.get("networking"):
        lines += [
            "bInitServerOnClient=true",
            "bUseSteamNetworking=true",
            "",
            "[/Script/Engine.GameEngine]",
            "!NetDriverDefinitions=ClearArray",
            '+NetDriverDefinitions=(DefName="GameNetDriver",DriverClassName="/Script/SteamSockets.SteamSocketsNetDriver",'
            'DriverClassNameFallback="/Script/OnlineSubsystemUtils.IpNetDriver")',
            '+NetDriverDefinitions=(DefName="DemoNetDriver",DriverClassName="/Script/Engine.DemoNetDriver",'
            'DriverClassNameFallback="/Script/Engine.DemoNetDriver")',
            "",
            "[/Script/SteamSockets.SteamSocketsNetDriver]",
            "bUseSteamNetworking=true",
        ]
    lines.append(f"; {END}")
    return "\n".join(lines) + "\n"


def game_ini_block(cfg: dict[str, Any]) -> str:
    return "\n".join([
        f"; {BEGIN}",
        "[/Script/UnrealEd.ProjectPackagingSettings]",
        "BuildConfiguration=PPBC_Shipping",
        "UsePakFile=True",
        "bUseIoStore=True",
        "bCompressed=True",
        "IncludeDebugFiles=False",
        "IncludePrerequisites=True",
        f"; {END}",
    ]) + "\n"


def build_cs_block() -> str:
    return (
        f"\t\t// {BEGIN}: Steamworks sólo existe en estas plataformas\n"
        "\t\tif (Target.Platform == UnrealTargetPlatform.Win64 || Target.Platform == UnrealTargetPlatform.Linux ||\n"
        "\t\t    Target.Platform == UnrealTargetPlatform.Mac)\n"
        "\t\t{\n"
        "\t\t\tPrivateDependencyModuleNames.AddRange(new string[] { \"Steamworks\", \"SteamShared\", \"OnlineSubsystem\" });\n"
        "\t\t\tDynamicallyLoadedModuleNames.Add(\"OnlineSubsystemSteam\");\n"
        "\t\t\tPublicDefinitions.Add(\"UNITY2UE_WITH_STEAM=1\");\n"
        "\t\t}\n"
        "\t\telse\n"
        "\t\t{\n"
        "\t\t\tPublicDefinitions.Add(\"UNITY2UE_WITH_STEAM=0\");\n"
        "\t\t}\n"
        f"\t\t// {END}\n"
    )


def cpp_identifier(name: str) -> str:
    ident = re.sub(r"\W", "_", name)
    return ident if ident and not ident[0].isdigit() else f"_{ident}"


def steam_ids_header(cfg: dict[str, Any]) -> str:
    def ns(title: str, ids: list[str]) -> list[str]:
        out = [f"\tnamespace {title}", "\t{"]
        out += [f'\t\tinline const TCHAR* const {cpp_identifier(i.lstrip("#"))} = TEXT("{i}");' for i in ids]
        return out + ["\t}"]

    lines = [
        "// Generado por unity2ue (steam integrate) desde Steam/steam.json. Se regenera: no editar.",
        "// Usa estas constantes en lugar de cadenas sueltas para que un error tipográfico no compile.",
        "#pragma once",
        "",
        '#include "CoreMinimal.h"',
        "",
        "namespace SteamIds",
        "{",
        f"\tinline constexpr int64 AppId = {cfg['app_id']};",
    ]
    lines += ns("Achievements", [a["id"] for a in cfg.get("achievements") or []])
    lines += ns("Stats", [s["id"] for s in cfg.get("stats") or []])
    lines += ns("Leaderboards", [b["id"] for b in cfg.get("leaderboards") or []])
    lines += ns("RichPresence", sorted({t for toks in (cfg.get("rich_presence") or {}).values() for t in toks}))
    lines += ["\tnamespace Dlc", "\t{"]
    lines += [f"\t\tinline constexpr int64 {cpp_identifier(d.get('name') or 'Dlc' + str(d['app_id']))} = {d['app_id']};"
              for d in cfg.get("dlc") or [] if isinstance(d.get("app_id"), int)]
    lines += ["\t}", "}", ""]
    return "\n".join(lines)


def rich_presence_files(cfg: dict[str, Any]) -> dict[str, str]:
    """Un fichero por idioma con el formato que acepta Steamworks (Community > Rich Presence)."""
    files = {}
    for lang, tokens in (cfg.get("rich_presence") or {}).items():
        files[f"{lang}.vdf"] = dumps("lang", {"Language": lang, "Tokens": dict(tokens)})
    return files


def _write(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text("utf-8", errors="replace") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _module_name(ue_project: Path) -> str:
    ups = sorted(ue_project.glob("*.uproject"))
    if not ups:
        raise FileNotFoundError(f"No hay .uproject en {ue_project}")
    return ups[0].stem


def required_plugins(cfg: dict[str, Any]) -> list[str]:
    plugins = ["OnlineSubsystem", "OnlineSubsystemUtils", "OnlineSubsystemSteam", "SteamShared"]
    if cfg.get("networking"):
        plugins.append("SteamSockets")
    return plugins


def integrate(ue_project: str | Path, cfg: dict[str, Any] | None = None, log=print) -> list[str]:
    """Aplica la integración. Devuelve las rutas (relativas) que han cambiado."""
    root = Path(ue_project)
    cfg = cfg or steam_config.load(root)
    module = _module_name(root)
    changed: list[str] = []

    up_path = root / f"{module}.uproject"
    up = json.loads(up_path.read_text("utf-8"))
    names = {p.get("Name") for p in up.get("Plugins", [])}
    for plugin in required_plugins(cfg):
        if plugin not in names:
            up.setdefault("Plugins", []).append({"Name": plugin, "Enabled": True})
    for p in up.get("Plugins", []):
        if p.get("Name") in required_plugins(cfg):
            p["Enabled"] = True
    if _write(up_path, json.dumps(up, indent="\t") + "\n"):
        changed.append(up_path.name)

    for ini, block in (("DefaultEngine.ini", engine_ini_block(cfg)), ("DefaultGame.ini", game_ini_block(cfg))):
        path = root / "Config" / ini
        text = path.read_text("utf-8") if path.exists() else ""
        if _write(path, upsert_block(text, block, ";")):
            changed.append(f"Config/{ini}")

    build_cs = root / "Source" / module / f"{module}.Build.cs"
    if build_cs.exists():
        text = build_cs.read_text("utf-8")
        new = upsert_block(text, build_cs_block(), "//", anchor="\t}\n}")
        if _write(build_cs, new):
            changed.append(str(build_cs.relative_to(root)))
    else:
        log(f"  Aviso: no existe {build_cs}; añade a mano la dependencia del módulo Steamworks")

    api = f"{module.upper()}_API"
    steam_src = root / "Source" / module / "Steam"
    for tpl in sorted(TEMPLATES.iterdir()):
        dst = steam_src / tpl.name
        if _write(dst, tpl.read_text("utf-8").replace("{{API}}", api)):
            changed.append(str(dst.relative_to(root)))
    if _write(steam_src / "SteamIds.h", steam_ids_header(cfg)):
        changed.append(str((steam_src / "SteamIds.h").relative_to(root)))

    sdir = steam_config.steam_dir(root)
    for name, content in rich_presence_files(cfg).items():
        if _write(sdir / "richpresence" / name, content):
            changed.append(f"Steam/richpresence/{name}")
    _write(sdir / ".gitignore", "build/\noutput/\nscripts/\n")
    return changed


def integrate_if_configured(ue_project: str | Path, log=print) -> list[str]:
    """Llamado por ``convert``: reaplica la integración si el proyecto ya tiene Steam/steam.json."""
    if not steam_config.config_path(ue_project).exists():
        return []
    try:
        return integrate(ue_project, log=log)
    except (OSError, ValueError, KeyError) as exc:
        log(f"  Aviso: no se pudo reaplicar la integración de Steam: {exc}")
        return []
