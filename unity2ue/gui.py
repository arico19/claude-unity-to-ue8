"""Aplicación de Windows para convertir un proyecto Unity en un proyecto de Unreal Engine 5.8.

Se elige el proyecto Unity y la carpeta de destino, y la aplicación hace todos los pasos:
convertir, traducir los scripts C# con Claude Code (opcional), compilar, importar en Unreal,
verificar, capturas y prueba de juego. Al terminar abre el proyecto en Unreal si se quiere.

Lanzar con ``python -m unity2ue gui`` o con ``Unity2UE.pyw`` (doble clic).
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .naming import to_pascal
from .ue_runner import find_ue_root

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable.replace("pythonw.exe", "python.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STEPS = [
    ("convert", "Convertir el proyecto Unity"),
    ("scripts", "Traducir scripts C# → C++ (Claude Code)"),
    ("build", "Compilar el C++"),
    ("import", "Importar en Unreal (assets, Blueprints, niveles)"),
    ("verify", "Verificar niveles"),
    ("screenshots", "Capturas de los niveles"),
    ("play", "Prueba de juego (Play automático)"),
]


def _is_unity_project(path: Path) -> bool:
    return (path / "Assets").is_dir() and (path / "ProjectSettings").is_dir()


def _slow_drive(path: str) -> str | None:
    """Devuelve el tipo de disco si el destino está en un disco USB o mecánico (compilar ahí es muy lento:
    el PCH de UE pesa ~2,5 GB y se lee a trozos por fallos de página)."""
    drive = Path(path).drive.rstrip(":")
    if not drive:
        return None
    ps = (f"$d = Get-Partition -DriveLetter {drive} | Get-Disk; "
          f"$m = (Get-PhysicalDisk | Where-Object DeviceId -eq $d.Number).MediaType; "
          "Write-Output \"$($d.BusType)|$m\"")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=15, creationflags=NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    bus, _, media = out.partition("|")
    if bus.upper() == "USB":
        return "disco USB"
    if media.upper() == "HDD":
        return "disco mecánico (HDD)"
    return None


def _default_name(unity_path: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]", " ", Path(unity_path).name)
    name = to_pascal(name.strip()) or "ConvertedProject"
    return name if name[0].isalpha() else f"Game{name}"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Unity → Unreal Engine 5.8")
        self.geometry("900x680")
        self.minsize(760, 560)
        self.proc: subprocess.Popen | None = None
        self.cancelled = False
        self.lines: queue.Queue[str | tuple] = queue.Queue()

        self.unity = tk.StringVar()
        self.dest = tk.StringVar()
        self.name = tk.StringVar()
        try:
            ue = str(find_ue_root())
        except FileNotFoundError:
            ue = ""
        self.ue = tk.StringVar(value=ue)
        self.opts = {key: tk.BooleanVar(value=True) for key, _ in STEPS}
        self.opts["scripts"].set(shutil.which("claude") is not None)
        self.open_ue = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Elige el proyecto Unity y la carpeta de destino.")

        self._build()
        self.after(100, self._drain)

    # ------------------------------------------------------------------ interfaz
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        form = ttk.LabelFrame(self, text="Proyecto")
        form.pack(fill="x", **pad)
        form.columnconfigure(1, weight=1)
        rows = [
            ("Proyecto Unity:", self.unity, self._pick_unity),
            ("Guardar el proyecto UE en:", self.dest, self._pick_dest),
            ("Nombre del proyecto UE:", self.name, None),
            ("Unreal Engine 5.8:", self.ue, self._pick_ue),
        ]
        for r, (label, var, cmd) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=3)
            ttk.Entry(form, textvariable=var).grid(row=r, column=1, sticky="ew", padx=6, pady=3)
            if cmd:
                ttk.Button(form, text="Examinar…", command=cmd).grid(row=r, column=2, padx=6, pady=3)

        steps = ttk.LabelFrame(self, text="Pasos")
        steps.pack(fill="x", **pad)
        for i, (key, label) in enumerate(STEPS):
            ttk.Checkbutton(steps, text=label, variable=self.opts[key]).grid(
                row=i // 2, column=i % 2, sticky="w", padx=8, pady=2)
        ttk.Checkbutton(steps, text="Abrir el proyecto en Unreal al terminar", variable=self.open_ue).grid(
            row=(len(STEPS) + 1) // 2, column=0, sticky="w", padx=8, pady=2)

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.btn_run = ttk.Button(bar, text="▶  Convertir", command=self._run)
        self.btn_run.pack(side="left")
        self.btn_cancel = ttk.Button(bar, text="Cancelar", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=6)
        self.btn_open = ttk.Button(bar, text="Abrir en Unreal", command=self._open_ue, state="disabled")
        self.btn_open.pack(side="right")
        self.btn_folder = ttk.Button(bar, text="Abrir carpeta", command=self._open_folder, state="disabled")
        self.btn_folder.pack(side="right", padx=6)
        self.btn_report = ttk.Button(bar, text="Ver resultado", command=self._open_report, state="disabled")
        self.btn_report.pack(side="right")

        self.progress = ttk.Progressbar(self, maximum=len(STEPS))
        self.progress.pack(fill="x", padx=8)
        ttk.Label(self, textvariable=self.status).pack(fill="x", padx=8, pady=(2, 0))

        logf = ttk.Frame(self)
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, wrap="word", height=20, font=("Consolas", 9), state="disabled")
        scroll = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.log.tag_configure("step", foreground="#1f5fbf", font=("Consolas", 9, "bold"))
        self.log.tag_configure("err", foreground="#b00020")
        self.log.tag_configure("ok", foreground="#1b7f3b", font=("Consolas", 9, "bold"))

    def _pick_unity(self) -> None:
        path = filedialog.askdirectory(title="Carpeta del proyecto Unity")
        if not path:
            return
        if not _is_unity_project(Path(path)):
            messagebox.showwarning("Proyecto Unity", "Esa carpeta no parece un proyecto Unity (falta Assets o ProjectSettings).")
        self.unity.set(path)
        if not self.name.get():
            self.name.set(_default_name(path))
        if self.dest.get() == "" :
            self.dest.set(str(Path(path).parent / f"{Path(path).name}_UE"))

    def _pick_dest(self) -> None:
        path = filedialog.askdirectory(title="Carpeta donde guardar el proyecto de Unreal")
        if path:
            self.dest.set(path)

    def _pick_ue(self) -> None:
        path = filedialog.askdirectory(title="Carpeta de instalación de Unreal Engine 5.8 (p.ej. G:\\UE_5.8)")
        if path:
            self.ue.set(path)

    # ------------------------------------------------------------------ log
    def _write(self, text: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self) -> None:
        try:
            while True:
                item = self.lines.get_nowait()
                if isinstance(item, tuple):
                    kind, *args = item
                    if kind == "step":
                        self.progress["value"] = args[0]
                        self.status.set(args[1])
                        self._write(f"\n=== {args[1]} ===", "step")
                    elif kind == "done":
                        self._finish(*args)
                else:
                    tag = "err" if re.search(r"error|falló|traceback", item, re.I) else None
                    self._write(item, tag)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    # ------------------------------------------------------------------ ejecución
    def _validate(self) -> str | None:
        if not _is_unity_project(Path(self.unity.get())):
            return "Elige una carpeta de proyecto Unity válida."
        if not self.dest.get():
            return "Elige la carpeta de destino."
        if Path(self.dest.get()).resolve() == Path(self.unity.get()).resolve():
            return "La carpeta de destino no puede ser la del proyecto Unity."
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.name.get() or ""):
            return "El nombre del proyecto UE sólo puede tener letras, números y _, y empezar por letra."
        needs_ue = any(self.opts[k].get() for k in ("build", "import", "verify", "screenshots", "play"))
        if needs_ue and not (Path(self.ue.get()) / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe").exists():
            return "No encuentro Unreal Engine 5.8 en esa carpeta."
        if self.opts["scripts"].get() and not shutil.which("claude"):
            return "Para traducir los scripts hace falta Claude Code (comando 'claude')."
        return None

    def _run(self) -> None:
        error = self._validate()
        if error:
            messagebox.showerror("Unity → Unreal", error)
            return
        dest = Path(self.dest.get())
        slow = _slow_drive(str(dest)) if self.opts["build"].get() else None
        if slow and not messagebox.askyesno(
                "Disco lento",
                f"El destino está en un {slow}. Compilar un proyecto de Unreal ahí puede tardar casi una hora "
                "en vez de unos minutos. Se recomienda un SSD interno.\n\n¿Continuar igualmente?"):
            return
        if dest.exists() and any(dest.iterdir()) and not (dest / "Unity2UE").exists():
            if not messagebox.askyesno("Carpeta no vacía", f"{dest} no está vacía. ¿Convertir igualmente ahí?"):
                return
        self.cancelled = False
        self.usage_summary = None
        for b in (self.btn_open, self.btn_folder, self.btn_report):
            b.configure(state="disabled")
        self.btn_run.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        selected = [k for k, _ in STEPS if self.opts[k].get()]
        threading.Thread(target=self._worker, args=(selected,), daemon=True).start()

    def _exec(self, cmd: list[str], cwd: Path, env: dict | None = None, on_line=None) -> int:
        shown = [c if len(c) < 80 else c[:77] + "..." for c in cmd]
        self.lines.put("> " + " ".join(f'"{c}"' if " " in c else c for c in shown))
        self.proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", env=env,
                                     creationflags=NO_WINDOW)
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            if on_line is not None:
                on_line(line.rstrip())
            else:
                self.lines.put(line.rstrip())
        code = self.proc.wait()
        self.proc = None
        return code

    def _worker(self, selected: list[str]) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", UE_ROOT=self.ue.get())
        unity, dest, name = self.unity.get(), self.dest.get(), self.name.get()
        labels = dict(STEPS)
        ok = True
        ue_steps = [s for s in ("build", "import", "verify", "screenshots", "play") if s in selected]
        plan = [s for s in ("convert", "scripts") if s in selected] + (["ue"] if ue_steps else [])
        done = 0
        for step in plan:
            if self.cancelled:
                ok = False
                break
            if step == "convert":
                self.lines.put(("step", done, labels["convert"]))
                code = self._exec([PY, "-u", "-m", "unity2ue", "convert", unity, dest, "--name", name], REPO, env)
                done += 1
            elif step == "scripts":
                self.lines.put(("step", done, labels["scripts"] + " — puede tardar bastante"))
                prompt = (f"/convertir-scripts {dest}\n\nTrabaja sin preguntar: no compiles ni abras Unreal "
                          "(lo hace la aplicación después). Al terminar resume qué scripts has traducido.")
                self.usage = None
                code = self._exec(["claude", "-p", prompt, "--permission-mode", "acceptEdits",
                                   "--output-format", "stream-json", "--verbose"], REPO, env, self._claude_line)
                self._save_usage(Path(dest))
                done += 1
            else:
                for s in ue_steps:
                    self.lines.put(("step", done, labels[s]))
                    code = self._exec([PY, "-u", "-m", "unity2ue", "ue", dest, "--ue-root", self.ue.get(),
                                       "--steps", s], REPO, env)
                    done += 1
                    if code != 0 and s == "build":
                        self.lines.put("La compilación falló: revisa Unity2UE\\logs\\build.log. Se continúa sin C++ nuevo.")
                    if self.cancelled:
                        break
                code = 0
            if code != 0 and step == "convert":
                ok = False
                break
        self.lines.put(("done", ok and not self.cancelled))

    # ------------------------------------------------------------------ Claude Code
    def _claude_line(self, line: str) -> None:
        """Muestra el progreso de Claude Code (stream-json) y guarda el resumen de uso final."""
        try:
            ev = json.loads(line)
        except ValueError:
            if line.strip():
                self.lines.put(line)
            return
        if ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    self.lines.put("Claude: " + block["text"].strip())
                elif block.get("type") == "tool_use":
                    args = block.get("input") or {}
                    target = args.get("file_path") or args.get("description") or ""
                    if args.get("file_path"):
                        target = Path(target).name
                    self.lines.put(f"  · {block.get('name', '')} {target}")
        elif ev.get("type") == "result":
            self.usage = ev

    def _save_usage(self, dest: Path) -> None:
        ev = getattr(self, "usage", None)
        if not ev:
            self.lines.put("No se pudo obtener el uso de tokens de Claude Code.")
            return
        u = ev.get("usage") or {}
        summary = {
            "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
            "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": u.get("cache_read_input_tokens", 0),
            "total_cost_usd": ev.get("total_cost_usd"),
            "duration_s": round((ev.get("duration_ms") or 0) / 1000),
            "turns": ev.get("num_turns"),
            "model_usage": ev.get("modelUsage"),
        }
        summary["total_tokens"] = sum(summary[k] for k in ("input_tokens", "output_tokens",
                                                           "cache_creation_input_tokens", "cache_read_input_tokens"))
        self.usage_summary = summary
        try:
            (dest / "Unity2UE").mkdir(parents=True, exist_ok=True)
            (dest / "Unity2UE" / "coste_claude.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except OSError:
            pass
        self.lines.put(self._usage_text())

    def _usage_text(self) -> str:
        s = getattr(self, "usage_summary", None)
        if not s:
            return ""
        cost = f"{s['total_cost_usd']:.2f} US$" if isinstance(s.get("total_cost_usd"), (int, float)) else "?"
        text = (f"Coste de Claude Code: {s['total_tokens']:,} tokens "
                f"(entrada {s['input_tokens']:,}, salida {s['output_tokens']:,}, "
                f"caché escrita {s['cache_creation_input_tokens']:,}, caché leída {s['cache_read_input_tokens']:,})")
        return text.replace(",", ".") + f" — {cost} — {s['duration_s']} s"

    def _finish(self, ok: bool) -> None:
        self.progress["value"] = len(STEPS) if ok else self.progress["value"]
        self.btn_run.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        dest = Path(self.dest.get())
        has_project = any(dest.glob("*.uproject"))
        for b in (self.btn_open, self.btn_folder):
            b.configure(state="normal" if has_project else "disabled")
        report = dest / "Unity2UE" / "resultado_ue.md"
        if not report.exists():
            report = dest / "Unity2UE" / "report.md"
        self.btn_report.configure(state="normal" if report.exists() else "disabled")
        if self.cancelled:
            self.status.set("Cancelado.")
            self._write("Cancelado por el usuario.", "err")
        elif ok:
            usage = self._usage_text()
            self.status.set(f"Terminado. Proyecto en {dest}" + (f"   ·   {usage}" if usage else ""))
            self._write(f"\nTerminado. Proyecto de Unreal en {dest}", "ok")
            if usage:
                self._write(usage, "ok")
            if self.open_ue.get() and has_project:
                self._open_ue()
        else:
            self.status.set("La conversión falló: revisa el registro.")

    def _cancel(self) -> None:
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True,
                           creationflags=NO_WINDOW)

    # ------------------------------------------------------------------ abrir resultados
    def _open_ue(self) -> None:
        uproject = next(Path(self.dest.get()).glob("*.uproject"), None)
        editor = Path(self.ue.get()) / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        if uproject and editor.exists():
            subprocess.Popen([str(editor), str(uproject)], creationflags=NO_WINDOW)

    def _open_folder(self) -> None:
        os.startfile(self.dest.get())  # noqa: S606 - sólo Windows

    def _open_report(self) -> None:
        dest = Path(self.dest.get()) / "Unity2UE"
        report = dest / "resultado_ue.md" if (dest / "resultado_ue.md").exists() else dest / "report.md"
        os.startfile(str(report))  # noqa: S606


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
