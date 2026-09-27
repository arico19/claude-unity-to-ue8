@echo off
REM Conversión completa Unity -> Unreal Engine 5.8 en un solo paso:
REM   convierte, compila el C++, importa en UE, verifica los niveles y hace capturas.
REM
REM Uso:  convertir.bat "C:\Proyectos\MiJuegoUnity" "C:\Proyectos\MiJuegoUE" MiJuego [opciones]
REM Opciones: --skip-build  --no-screenshots  --ue-root "G:\UE_5.8"
REM UE 5.8 se busca solo (UE_ROOT, Epic Launcher o rutas típicas).
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%~3"=="" (
  echo Uso: %~nx0 ProyectoUnity DestinoUE NombreProyecto [--skip-build] [--no-screenshots] [--ue-root RUTA]
  exit /b 2
)
cd /d "%~dp0"
python -c "import yaml" 2>nul || python -m pip install -q -e .
python -u -m unity2ue full "%~1" "%~2" --name %3 %4 %5 %6 %7
set CODE=%ERRORLEVEL%
echo.
if exist "%~2\Unity2UE\resultado_ue.md" echo Resultado: "%~2\Unity2UE\resultado_ue.md"
if exist "%~2\Unity2UE\screenshots" echo Capturas:  "%~2\Unity2UE\screenshots"
exit /b %CODE%
