"""Automatiza los pasos dentro de Unreal Engine: compilar, importar, verificar y capturar.

Lo usa ``unity2ue full`` (conversión completa de principio a fin) y ``unity2ue ue``
(sólo los pasos de Unreal sobre un proyecto ya convertido).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

EDITOR_SCRIPTS = Path(__file__).resolve().parent / "ue_editor" / "unity2ue_import"
LAUNCHER_DAT = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"


def find_ue_root(explicit: str | None = None, version: str = "5.8") -> Path:
    """Busca la instalación de UE: argumento, UE_ROOT, Epic Launcher o rutas típicas."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("UE_ROOT"):
        candidates.append(Path(os.environ["UE_ROOT"]))
    if LAUNCHER_DAT.exists():
        try:
            data = json.loads(LAUNCHER_DAT.read_text("utf-8"))
            for inst in data.get("InstallationList", []):
                if inst.get("AppName") == f"UE_{version}":
                    candidates.append(Path(inst["InstallLocation"]))
        except (OSError, ValueError):
            pass
    for drive in "CDEFGH":
        candidates += [Path(f"{drive}:/UE_{version}"), Path(f"{drive}:/Epic Games/UE_{version}"),
                       Path(f"{drive}:/Program Files/Epic Games/UE_{version}")]
    for c in candidates:
        if (c / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe").exists():
            return c
    raise FileNotFoundError(f"No se encuentra Unreal Engine {version}. Usa --ue-root o la variable UE_ROOT.")


class UERunner:
    def __init__(self, project_dir: Path, ue_root: Path, log=print) -> None:
        self.dir = Path(project_dir)
        uprojects = list(self.dir.glob("*.uproject"))
        if not uprojects:
            raise FileNotFoundError(f"No hay .uproject en {self.dir}")
        self.uproject = uprojects[0]
        self.module = self.uproject.stem
        self.ue = Path(ue_root)
        self.log = log
        self.logs = self.dir / "Unity2UE" / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- utilidades
    def _run(self, cmd: list[str], log_name: str, timeout: int) -> int:
        log_path = self.logs / log_name
        self.log(f"  -> {log_path}")
        start = time.time()
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout, cwd=self.dir)
        self.log(f"  código {proc.returncode} en {time.time() - start:.0f} s")
        return proc.returncode

    def sync_editor_scripts(self) -> None:
        """Copia la última versión de los scripts del editor al proyecto."""
        dest = self.dir / "Content" / "Python" / "unity2ue_import"
        extra = dest / "extra"
        keep = None
        if extra.exists():
            keep = self.dir / "Unity2UE" / "_extra_backup"
            shutil.rmtree(keep, ignore_errors=True)
            shutil.copytree(extra, keep)
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(EDITOR_SCRIPTS, dest, ignore=shutil.ignore_patterns("__pycache__"))
        if keep is not None:
            shutil.rmtree(dest / "extra", ignore_errors=True)
            shutil.copytree(keep, dest / "extra")
            shutil.rmtree(keep, ignore_errors=True)

    def _python(self, script: str, log_name: str, timeout: int = 3600) -> int:
        exe = self.ue / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
        return self._run([str(exe), str(self.uproject), "-run=pythonscript", f"-script={script}",
                          "-unattended", "-nosplash", "-nop4", "-stdout", "-FullStdOutLogOutput"], log_name, timeout)

    # ---------------------------------------------------------------- pasos
    def build(self) -> bool:
        self.log("[UE 1/4] Compilando el módulo C++...")
        bat = self.ue / "Engine" / "Build" / "BatchFiles" / "Build.bat"
        code = self._run([str(bat), f"{self.module}Editor", "Win64", "Development",
                          f"-Project={self.uproject}", "-WaitMutex", "-NoUBA"], "build.log", 7200)
        # -NoUBA: el ejecutor UBA (Unreal Build Accelerator) se queda esperando sin usar CPU en
        # algunos equipos y una compilación de minutos tarda casi una hora.
        if code != 0:
            errors = [ln.strip() for ln in (self.logs / "build.log").read_text("utf-8", "replace").splitlines()
                      if "error" in ln.lower()][:15]
            self.log("  La compilación falló:\n    " + "\n    ".join(errors))
        return code == 0

    def import_content(self) -> dict:
        self.log("[UE 2/4] Importando assets, materiales, Blueprints y niveles...")
        self._python("unity2ue_import/run_all.py", "import.log")
        path = self.dir / "Unity2UE" / "import_log.json"
        if not path.exists():
            self.log("  No se generó import_log.json: el editor se cerró antes de terminar (ver import.log)")
            return {}
        data = json.loads(path.read_text("utf-8"))
        self.log(f"  Resultado: {data.get('summary')}")
        return data

    def verify(self) -> dict:
        self.log("[UE 3/4] Verificando niveles y assets...")
        self._python("unity2ue_import/verify.py", "verify.log", 1800)
        path = self.dir / "Unity2UE" / "verify.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def screenshots(self) -> list[str]:
        self.log("[UE 4/4] Haciendo capturas de cada nivel (se abre el editor unos minutos)...")
        exe = self.ue / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        out = self.dir / "Unity2UE" / "screenshots"
        shutil.rmtree(out, ignore_errors=True)
        try:
            self._run([str(exe), str(self.uproject), "-ExecutePythonScript=unity2ue_import/screenshots.py",
                       "-unattended", "-nosplash", "-nop4", "-log"], "screenshots.log", 3600)
        except subprocess.TimeoutExpired:
            self.log("  El editor no terminó a tiempo; capturas parciales")
        return sorted(str(p) for p in out.glob("*.png")) if out.exists() else []

    def play_test(self, level: str | None = None) -> list[str]:
        """Pulsa Play en el nivel, hace capturas durante la partida y guarda el log del juego."""
        self.log("[UE] Prueba de juego (Play automático, se abre el editor ~1 min)...")
        exe = self.ue / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        out = self.dir / "Unity2UE" / "play"
        shutil.rmtree(out, ignore_errors=True)
        env = dict(os.environ)
        if level:
            env["UNITY2UE_PLAY_LEVEL"] = level
        log_path = self.logs / "play.log"
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
                subprocess.run([str(exe), str(self.uproject), "-ExecutePythonScript=unity2ue_import/play_test.py",
                                "-unattended", "-nosplash", "-nop4", "-log"], stdout=fh, stderr=subprocess.STDOUT,
                               timeout=900, cwd=self.dir, env=env)
        except subprocess.TimeoutExpired:
            self.log("  El editor no terminó a tiempo")
        game_log = self.dir / "Saved" / "Logs" / f"{self.module}.log"
        if game_log.exists():
            lines = [ln for ln in game_log.read_text("utf-8", "replace").splitlines()
                     if "LogUnity" in ln or "[unity2ue][play]" in ln or "Error" in ln]
            (self.logs / "play_game.log").write_text(chr(10).join(lines), encoding="utf-8")
        return sorted(str(p) for p in out.glob("*.png")) if out.exists() else []

    # ---------------------------------------------------------------- informe
    def write_summary(self, built: bool, imp: dict, ver: dict, shots: list[str]) -> Path:
        lines = ["# Resultado de la prueba en Unreal Engine", "",
                 f"- **Proyecto:** `{self.uproject}`", f"- **Motor:** `{self.ue}`",
                 f"- **Compilación C++:** {'OK' if built else 'FALLÓ (ver logs/build.log)'}",
                 f"- **Importación:** {imp.get('summary', 'no terminó')}", ""]
        errors = [e for e in imp.get("entries", []) if e["status"] == "error"]
        if errors:
            lines += ["## Errores de importación", ""]
            lines += [f"- `{e['step']}` {e['item']}: {e['message'].splitlines()[-1] if e['message'] else ''}"
                      for e in errors[:40]]
            lines.append("")
        if ver:
            lines += ["## Assets creados", ""]
            lines += [f"- {k}: {v}" for k, v in ver.get("assets", {}).get("by_class", {}).items()]
            bad = ver.get("assets", {}).get("blueprints_with_errors") or []
            if bad:
                lines.append(f"- Blueprints con errores de compilación: {', '.join(bad)}")
            lines += ["", "## Niveles", "", "| Nivel | Actores | Luces | Cámaras | Scripts C++ | Mallas vacías | Materiales vacíos |",
                      "|---|---:|---:|---:|---:|---:|---:|"]
            for path, r in ver.get("levels", {}).items():
                lines.append(f"| `{path}` | {r.get('actors', '-')} | {r.get('lights', '-')} | {r.get('cameras', '-')} | "
                             f"{r.get('script_components', '-')} | {len(r.get('empty_static_meshes', []))} | "
                             f"{len(r.get('missing_materials', []))} |")
            lines.append("")
        if shots:
            lines += ["## Capturas", ""] + [f"- `{s}`" for s in shots] + [""]
        path = self.dir / "Unity2UE" / "resultado_ue.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _load(self, name: str) -> dict:
        path = self.dir / "Unity2UE" / name
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def run_all(self, build: bool = True, screenshots: bool = True, steps: set[str] | None = None) -> int:
        """Pasos: build, import, verify, screenshots. Los omitidos reutilizan su último resultado."""
        steps = steps or ({"build", "import", "verify"} | ({"screenshots"} if screenshots else set()))
        if not build:
            steps.discard("build")
        self.sync_editor_scripts()
        built = self.build() if "build" in steps else True
        imp = self.import_content() if "import" in steps else self._load("import_log.json")
        ver = self.verify() if "verify" in steps else self._load("verify.json")
        shots = self.screenshots() if "screenshots" in steps else []
        if "play" in steps:
            shots += self.play_test()
        summary = self.write_summary(built, imp, ver, shots)
        self.log(f"\nResumen: {summary}")
        ok = built and imp and not imp.get("summary", {}).get("error")
        return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(UERunner(Path(sys.argv[1]), find_ue_root()).run_all())
