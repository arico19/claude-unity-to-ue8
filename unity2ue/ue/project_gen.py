"""Generación del proyecto Unreal Engine 5.8 de destino (.uproject, módulo C++, configuración)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..config import ConversionConfig

TEMPLATES = Path(__file__).parent / "templates"
EDITOR_SCRIPTS = Path(__file__).resolve().parent.parent / "ue_editor" / "unity2ue_import"

# Nombres de tecla del InputManager de Unity -> FKey de UE
UNITY_KEY_TO_UE = {
    "space": "SpaceBar", "return": "Enter", "enter": "Enter", "escape": "Escape", "tab": "Tab",
    "backspace": "BackSpace", "delete": "Delete", "left shift": "LeftShift", "right shift": "RightShift",
    "left ctrl": "LeftControl", "right ctrl": "RightControl", "left alt": "LeftAlt", "right alt": "RightAlt",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "mouse 0": "LeftMouseButton", "mouse 1": "RightMouseButton", "mouse 2": "MiddleMouseButton",
    "joystick button 0": "Gamepad_FaceButton_Bottom", "joystick button 1": "Gamepad_FaceButton_Right",
    "joystick button 2": "Gamepad_FaceButton_Left", "joystick button 3": "Gamepad_FaceButton_Top",
    "joystick button 4": "Gamepad_LeftShoulder", "joystick button 5": "Gamepad_RightShoulder",
    "joystick button 6": "Gamepad_Special_Left", "joystick button 7": "Gamepad_Special_Right",
    "joystick button 8": "Gamepad_LeftThumbstick", "joystick button 9": "Gamepad_RightThumbstick",
}
# (tipo, eje) de Unity -> eje de UE (type 1 ratón, type 2 joystick)
UNITY_AXIS_TO_UE = {
    (1, 0): "MouseX", (1, 1): "MouseY", (1, 2): "MouseWheelAxis",
    (2, 0): "Gamepad_LeftX", (2, 1): "Gamepad_LeftY", (2, 3): "Gamepad_RightX", (2, 4): "Gamepad_RightY",
    (2, 8): "Gamepad_LeftTriggerAxis", (2, 9): "Gamepad_RightTriggerAxis",
}


def unity_key_to_ue(name: str) -> str | None:
    n = name.strip().lower()
    if not n:
        return None
    if n in UNITY_KEY_TO_UE:
        return UNITY_KEY_TO_UE[n]
    if len(n) == 1 and n.isalpha():
        return n.upper()
    if len(n) == 1 and n.isdigit():
        return ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"][int(n)]
    if n.startswith("f") and n[1:].isdigit():
        return n.upper()
    if n.startswith("[") and n.endswith("]"):  # teclado numérico: [1]
        inner = n[1:-1]
        if inner.isdigit():
            return "NumPad" + ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"][int(inner)]
    return None


def _write(path: Path, content: str) -> None:
    """Escribe sólo si cambia: reescribir un .h idéntico cambia su fecha y UE recompila todo el módulo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8", errors="replace") == content:
        return
    path.write_text(content, encoding="utf-8")


def uproject(cfg: ConversionConfig, uses_paper2d: bool) -> dict[str, Any]:
    plugins = [
        {"Name": "PythonScriptPlugin", "Enabled": True},
        {"Name": "EditorScriptingUtilities", "Enabled": True},
        {"Name": "EnhancedInput", "Enabled": True},
        {"Name": "Niagara", "Enabled": True},
        {"Name": "ModelingToolsEditorMode", "Enabled": True, "TargetAllowList": ["Editor"]},
    ]
    if uses_paper2d:
        plugins.append({"Name": "Paper2D", "Enabled": True})
    return {
        "FileVersion": 3,
        "EngineAssociation": cfg.engine_version,
        "Category": "",
        "Description": "Proyecto convertido desde Unity con unity2ue",
        "Modules": [{"Name": cfg.module_name, "Type": "Runtime", "LoadingPhase": "Default",
                     "AdditionalDependencies": ["Engine", "CoreUObject"]}],
        "Plugins": plugins,
    }


def build_cs(module: str) -> str:
    return f"""// Generado por unity2ue
using UnrealBuildTool;

public class {module} : ModuleRules
{{
	public {module}(ReadOnlyTargetRules Target) : base(Target)
	{{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{{
			"Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput", "PhysicsCore",
			"UMG", "Slate", "SlateCore", "Niagara", "AIModule", "NavigationSystem"
		}});

		PublicIncludePaths.Add(ModuleDirectory);
	}}
}}
"""


def target_cs(module: str, editor: bool) -> str:
    name = f"{module}Editor" if editor else module
    ttype = "Editor" if editor else "Game"
    return f"""// Generado por unity2ue
using UnrealBuildTool;
using System.Collections.Generic;

public class {name}Target : TargetRules
{{
	public {name}Target(TargetInfo Target) : base(Target)
	{{
		Type = TargetType.{ttype};
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("{module}");
	}}
}}
"""


def module_files(module: str) -> dict[str, str]:
    api = f"{module.upper()}_API"
    return {
        f"{module}.h": '#pragma once\n\n#include "CoreMinimal.h"\n',
        f"{module}.cpp": (
            f'#include "{module}.h"\n#include "Modules/ModuleManager.h"\n\n'
            f'IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, {module}, "{module}");\n'
        ),
        "__api__": api,
    }


def default_engine_ini(cfg: ConversionConfig, default_map: str | None, gravity_z: float,
                       layers: dict[int, str]) -> str:
    lines = [
        "; Generado por unity2ue",
        "[/Script/EngineSettings.GameMapsSettings]",
    ]
    if default_map:
        lines += [f"GameDefaultMap={default_map}", f"EditorStartupMap={default_map}"]
    # Sin pawn por defecto (Unity no crea ninguno): ver UnityCompat/UnityGameMode.h
    lines.append(f"GlobalDefaultGameMode=/Script/{cfg.module_name}.UnityGameMode")
    lines += [
        "",
        "[/Script/Engine.RendererSettings]",
        "r.DefaultFeature.AutoExposure=False",
        "r.DynamicGlobalIlluminationMethod=1",
        "r.ReflectionMethod=1",
        # DX11 + SM5: DX12 provoca DXGI_ERROR_DEVICE_REMOVED en GPUs como la GTX 1070. Las
        # sombras virtuales exigen DX12 + SM6 (UE avisa de configuración incompleta), así que se
        # usan sombras clásicas; Lumen funciona en SM5 con trazado por software.
        "r.Shadow.Virtual.Enable=0",
        "r.GenerateMeshDistanceFields=True",
        "",
        "[/Script/WindowsTargetPlatform.WindowsTargetSettings]",
        "DefaultGraphicsRHI=DefaultGraphicsRHI_DX11",
        "-TargetedRHIs=PCD3D_SM6",
        "+TargetedRHIs=PCD3D_SM5",
        "",
        "[/Script/Engine.PhysicsSettings]",
        f"DefaultGravityZ={gravity_z:.3f}",
        "",
        "[/Script/Engine.CollisionProfile]",
    ]
    # Capas de Unity 8..31 (definidas por el usuario) -> canales de colisión de juego.
    channel = 1
    for idx in sorted(layers):
        if idx < 8 or channel > 18:
            continue
        name = layers[idx].replace(" ", "")
        lines.append(
            f"+DefaultChannelResponses=(Channel=ECC_GameTraceChannel{channel},DefaultResponse=ECR_Block,"
            f"bTraceType=False,bStaticObject=False,Name=\"{name}\")"
        )
        channel += 1
    lines += [
        "",
        "[/Script/PythonScriptPlugin.PythonScriptPluginSettings]",
        "bDeveloperMode=True",
        "",
    ]
    return "\n".join(lines)


def default_game_ini(cfg: ConversionConfig, player: dict[str, Any]) -> str:
    return "\n".join(
        [
            "; Generado por unity2ue",
            "[/Script/EngineSettings.GeneralProjectSettings]",
            f"ProjectName={player.get('product_name') or cfg.project_name}",
            f"CompanyName={player.get('company_name') or ''}",
            f"ProjectVersion={player.get('bundle_version') or '1.0.0'}",
            "",
        ]
    )


def default_input_ini() -> str:
    return "\n".join(
        [
            "; Generado por unity2ue",
            "[/Script/Engine.InputSettings]",
            "DefaultPlayerInputClass=/Script/EnhancedInput.EnhancedPlayerInput",
            "DefaultInputComponentClass=/Script/EnhancedInput.EnhancedInputComponent",
            "",
        ]
    )


def gameplay_tags_ini(tags: list[str]) -> str:
    lines = ["; Generado por unity2ue: tags de Unity como Gameplay Tags", "[/Script/GameplayTags.GameplayTagsSettings]"]
    for t in tags:
        safe = "".join(c if c.isalnum() or c in "_." else "_" for c in t)
        lines.append(f'+GameplayTagList=(Tag="Unity.Tag.{safe}",DevComment="Tag de Unity: {t}")')
    return "\n".join(lines) + "\n"


def input_mappings(axes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte el InputManager de Unity en acciones de Enhanced Input."""
    actions: dict[str, dict[str, Any]] = {}
    for a in axes:
        name = a["name"]
        if not name:
            continue
        entry = actions.setdefault(name, {"name": name, "value_type": "Boolean", "mappings": []})
        if a["type"] == 0:
            has_negative = bool(a["negative"] or a["alt_negative"])
            if has_negative:
                entry["value_type"] = "Axis1D"
            for key, negate in ((a["positive"], False), (a["alt_positive"], False),
                                (a["negative"], True), (a["alt_negative"], True)):
                ue_key = unity_key_to_ue(key)
                if ue_key:
                    entry["mappings"].append({"key": ue_key, "negate": negate != a["invert"]})
        else:
            ue_axis = UNITY_AXIS_TO_UE.get((a["type"], a["axis"]))
            if ue_axis:
                entry["value_type"] = "Axis1D"
                # El eje Y de ratón/joystick en Unity es positivo hacia arriba/adelante.
                entry["mappings"].append({"key": ue_axis, "negate": a["invert"]})
    return list(actions.values())


def generate_project(out_dir: Path, cfg: ConversionConfig, *, settings: dict[str, Any],
                     default_map: str | None, uses_paper2d: bool = False) -> Path:
    """Crea el esqueleto del proyecto UE. Devuelve la ruta del .uproject."""
    module = cfg.module_name
    out_dir.mkdir(parents=True, exist_ok=True)
    up = out_dir / f"{module}.uproject"
    _write(up, json.dumps(uproject(cfg, uses_paper2d), indent="\t") + "\n")

    src = out_dir / "Source"
    _write(src / f"{module}.Target.cs", target_cs(module, editor=False))
    _write(src / f"{module}Editor.Target.cs", target_cs(module, editor=True))
    mod_dir = src / module
    _write(mod_dir / f"{module}.Build.cs", build_cs(module))
    files = module_files(module)
    api = files.pop("__api__")
    for name, content in files.items():
        _write(mod_dir / name, content)
    for tpl in sorted((TEMPLATES / "UnityCompat").iterdir()):
        _write(mod_dir / "UnityCompat" / tpl.name, tpl.read_text("utf-8").replace("{{API}}", api))

    cfg_dir = out_dir / "Config"
    phys = settings.get("physics", {})
    gravity_y = (phys.get("gravity") or [0, -9.81, 0])[1]
    tl = settings.get("tags_and_layers", {})
    _write(cfg_dir / "DefaultEngine.ini", default_engine_ini(cfg, default_map, gravity_y * 100.0, tl.get("layers", {})))
    _write(cfg_dir / "DefaultGame.ini", default_game_ini(cfg, settings.get("player", {})))
    _write(cfg_dir / "DefaultInput.ini", default_input_ini())
    if tl.get("tags"):
        _write(cfg_dir / "DefaultGameplayTags.ini", gameplay_tags_ini(tl["tags"]))

    # Scripts Python del editor (UE añade Content/Python al sys.path automáticamente).
    # extra/ guarda las personalizaciones del proyecto: se conserva al reconvertir.
    py_dst = out_dir / "Content" / "Python" / "unity2ue_import"
    shutil.copytree(EDITOR_SCRIPTS, py_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "extra"),
                    dirs_exist_ok=True)
    (py_dst / "extra").mkdir(exist_ok=True)
    if not (py_dst / "extra" / "__init__.py").exists():
        shutil.copy2(EDITOR_SCRIPTS / "extra" / "__init__.py", py_dst / "extra" / "__init__.py")

    _write(out_dir / ".gitignore", "Binaries/\nDerivedDataCache/\nIntermediate/\nSaved/\n.vs/\n*.sln\n")
    return up


def run_scripts(out_dir: Path, module: str) -> None:
    """Scripts de conveniencia para compilar y lanzar la importación dentro de UE."""
    win = f"""@echo off
REM Generado por unity2ue. Requiere la variable UE_ROOT apuntando a la instalación de UE 5.8
REM (p.ej. set UE_ROOT=C:\\Program Files\\Epic Games\\UE_5.8)
if "%UE_ROOT%"=="" set UE_ROOT=C:\\Program Files\\Epic Games\\UE_5.8
set PROJECT=%~dp0{module}.uproject

if "%1"=="--skip-build" goto import
echo [1/2] Compilando el módulo C++...
call "%UE_ROOT%\\Engine\\Build\\BatchFiles\\Build.bat" {module}Editor Win64 Development -Project="%PROJECT%" -WaitMutex -NoUBA
if errorlevel 1 (
  echo La compilacion fallo. Revisa los scripts convertidos en Source\\{module}\\Unity
  echo Puedes continuar la importacion sin C++ con: %~nx0 --skip-build
  exit /b 1
)

:import
echo [2/2] Importando assets, materiales, blueprints y niveles...
"%UE_ROOT%\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" "%PROJECT%" -run=pythonscript -script="unity2ue_import/run_all.py" -unattended -nosplash -stdout -FullStdOutLogOutput
"""
    sh = f"""#!/usr/bin/env bash
# Generado por unity2ue. Requiere UE_ROOT apuntando a la instalación de UE 5.8.
set -euo pipefail
DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
PROJECT="$DIR/{module}.uproject"
: "${{UE_ROOT:?Define UE_ROOT con la ruta de Unreal Engine 5.8}}"
case "$(uname)" in
  Darwin) PLATFORM=Mac; EDITOR="$UE_ROOT/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor";;
  *) PLATFORM=Linux; EDITOR="$UE_ROOT/Engine/Binaries/Linux/UnrealEditor-Cmd";;
esac

if [[ "${{1:-}}" != "--skip-build" ]]; then
  echo "[1/2] Compilando el módulo C++..."
  "$UE_ROOT/Engine/Build/BatchFiles/RunUBT.sh" {module}Editor "$PLATFORM" Development -Project="$PROJECT" -WaitMutex
fi

echo "[2/2] Importando assets, materiales, blueprints y niveles..."
"$EDITOR" "$PROJECT" -run=pythonscript -script="unity2ue_import/run_all.py" -unattended -nosplash -stdout
"""
    _write(out_dir / "Unity2UE_Import.bat", win)
    _write(out_dir / "Unity2UE_Import.sh", sh)
    (out_dir / "Unity2UE_Import.sh").chmod(0o755)
