---
name: convertir-proyecto
description: Convierte un proyecto Unity completo (escenas, prefabs, GameObjects y componentes, materiales, assets y scripts C#) en un proyecto de Unreal Engine 5.8. Úsalo cuando el usuario quiera migrar/convertir/portar un proyecto de Unity a Unreal.
argument-hint: <ruta-proyecto-unity> <ruta-destino-ue> [nombre]
---

# Conversión completa Unity → Unreal Engine 5.8

Argumentos: `$ARGUMENTS` (ruta del proyecto Unity, carpeta destino del proyecto UE y,
opcionalmente, el nombre del proyecto/módulo). Si falta alguno, pregúntalo.

## 1. Comprobaciones previas
- La ruta Unity debe contener `Assets/` y `ProjectSettings/`.
- Los assets deben estar en texto: `ProjectSettings/EditorSettings.asset` → `m_SerializationMode: 2`.
  Si no, pide al usuario que en Unity active *Project Settings > Editor > Asset Serialization =
  Force Text* y guarde el proyecto; sin esto no se pueden leer escenas ni prefabs.
- El destino no debe ser un proyecto UE con trabajo manual no versionado (la conversión
  regenera `Unity2UE/`, `Content/Python/unity2ue_import/`, `Config/` y los stubs C++ no traducidos).

## 2. Análisis
Ejecuta `python3 -m unity2ue analyze "<unity>"`. Para proyectos medianos o grandes delega en el
subagente `unity-analyzer` para obtener un plan. Resume al usuario: tamaño, riesgos y decisiones
pendientes. Si hay riesgos bloqueantes (serialización binaria), detente aquí.

## 3. Conversión determinista
```
python3 -m unity2ue convert "<unity>" "<destino>" --name <Nombre>
```
Opciones útiles: `--scene <Escena>` (repetible), `--only-referenced`, `--config cfg.json`
(ver `unity2ue/config.py`: intensidades de luz, carpetas excluidas...). Lee
`<destino>/Unity2UE/report.md` y resume errores y tareas manuales.

## 4. Traducción de scripts C# → C++
Sigue la skill `convertir-scripts` (`/convertir-scripts <destino>`): traduce todos los stubs con
subagentes `csharp-to-cpp` en paralelo por lotes y revísalos con `cpp-reviewer`.

## 5. Importación en Unreal
El usuario (o tú, si `UE_ROOT` está definido y hay Unreal Engine 5.8 instalado en la máquina)
ejecuta `Unity2UE_Import.bat` (Windows) o `./Unity2UE_Import.sh` (Linux/macOS):
1. compila el módulo C++ (`<Nombre>Editor`),
2. lanza `UnrealEditor-Cmd ... -run=pythonscript -script="unity2ue_import/run_all.py"` que
   importa texturas/modelos/audio, crea `M_UnityLit`/`M_UnityUnlit` + Material Instances,
   Enhanced Input, Blueprints de prefabs y niveles.
Tras ejecutarlo, lee `<destino>/Unity2UE/import_log.json` y corrige lo que falle (si falla la
compilación, usa `cpp-reviewer` con los errores).

## 6. Tareas manuales
Usa `/tareas-manuales <destino>` para UI (UMG), Animator Controllers (AnimBP), partículas
(Niagara), shaders personalizados, terrenos, etc.

## 7. Cierre
Entrega al usuario: ruta del `.uproject`, resumen de lo convertido, lista de pendientes con
prioridad y cómo abrir el proyecto (doble clic en el `.uproject` → "Yes" a recompilar módulos).
