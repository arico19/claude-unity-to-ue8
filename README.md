# unity2ue — Unity → Unreal Engine 5.8 con Claude Code

Proyecto de Claude Code para convertir **un proyecto completo de Unity** (escenas,
prefabs, GameObjects con todos sus componentes, materiales, texturas, modelos, audio,
ajustes y scripts C#) en un **proyecto de Unreal Engine 5.8** listo para abrir.

Combina tres piezas:

| Capa | Qué hace | Dónde |
|---|---|---|
| Toolkit Python | Lee el proyecto Unity (YAML + `.meta`) y genera el proyecto UE, JSON intermedio y esqueletos C++ | `unity2ue/` |
| Scripts del editor UE | Dentro de Unreal: importa assets y crea materiales, Blueprints y niveles | `unity2ue/ue_editor/` → `Content/Python/` |
| Agentes de Claude Code | Traducen la lógica C# → C++, recrean UI/animación/VFX y revisan | `.claude/` |

## Requisitos

- Python 3.10+ y `pip install -e .` (sólo depende de PyYAML).
- Proyecto Unity con **Asset Serialization = Force Text** (*Project Settings → Editor*).
- Para la importación final: Unreal Engine 5.8 con los plugins *Python Editor Script Plugin*
  y *Editor Scripting Utilities* (el `.uproject` generado ya los activa) y un compilador C++
  configurado para UE (Visual Studio 2022 en Windows, Xcode en macOS, clang en Linux).

## Uso con Claude Code (recomendado)

Abre este repositorio con Claude Code y escribe:

```
/convertir-proyecto C:/Proyectos/MiJuegoUnity C:/Proyectos/MiJuegoUE MiJuego
```

Claude analizará el proyecto, ejecutará la conversión, traducirá los scripts con subagentes en
paralelo (`/convertir-scripts`), te guiará en la importación dentro de Unreal y en las tareas
manuales (`/tareas-manuales`).

| Skill / agente | Función |
|---|---|
| `/convertir-proyecto` | Flujo completo de principio a fin |
| `/convertir-scripts` | Traduce los stubs C++ pendientes con `csharp-to-cpp` en paralelo + revisión |
| `/tareas-manuales` | UI → UMG, Animator → AnimBP, partículas → Niagara, shaders, terrenos |
| `unity-api-a-unreal` | Tabla de equivalencias de API Unity → UE 5.8 |
| agente `unity-analyzer` | Plan de migración y riesgos (sólo lectura) |
| agente `csharp-to-cpp` | Traduce cuerpos de métodos C# a C++ de UE |
| agente `cpp-reviewer` | Revisa errores de compilación/UHT y fidelidad al C# |
| agente `ue-content-builder` | Scripts Python de editor para contenido no automatizable |

## Conversión automática completa (un solo comando)

```bat
convertir.bat "C:\Proyectos\MiJuegoUnity" "C:\Proyectos\MiJuegoUE" MiJuego
```

o `python -m unity2ue full <ProyectoUnity> <DestinoUE> --name MiJuego`. Hace todo sin intervención:

1. Convierte el proyecto Unity (igual que `convert`).
2. Localiza UE 5.8 (`--ue-root`, `UE_ROOT` o la instalación del Epic Launcher) y compila el módulo C++.
3. Importa dentro del editor (`run_all.py`): assets, materiales, input, Blueprints y niveles.
4. Verifica cada nivel (`verify.py` → `Unity2UE/verify.json`): actores, luces, cámaras, scripts,
   mallas y materiales vacíos, Blueprints con errores.
5. Abre el editor y captura cada nivel desde la cámara de Unity y en vista general
   (`screenshots.py` → `Unity2UE/screenshots/*.png`); el editor se cierra solo.

El resumen queda en `Unity2UE/resultado_ue.md` y los logs de cada paso en `Unity2UE/logs/`.
Opciones: `--skip-build`, `--no-screenshots`. Para repetir sólo los pasos de Unreal sobre un
proyecto ya convertido: `python -m unity2ue ue <DestinoUE>`.

## Uso manual (CLI)

```bash
pip install -e .
unity2ue analyze /ruta/ProyectoUnity                    # inventario y riesgos
unity2ue convert /ruta/ProyectoUnity /ruta/ProyectoUE --name MiJuego
unity2ue scripts /ruta/ProyectoUE --pending             # scripts por traducir
```

Después, en la carpeta del proyecto UE:

```bash
# Windows (UE_ROOT = carpeta de instalación de UE 5.8)
set UE_ROOT=C:\Program Files\Epic Games\UE_5.8
Unity2UE_Import.bat
# Linux / macOS
UE_ROOT=/opt/UnrealEngine ./Unity2UE_Import.sh
```

El script compila el módulo C++ y ejecuta `unity2ue_import/run_all.py` en el editor. Se puede
repetir un paso concreto con `UNITY2UE_STEPS=materials,levels`.

## Qué se convierte

| Unity | Unreal Engine 5.8 |
|---|---|
| Escena `.unity` | Nivel `/Game/Unity/Maps/<Escena>` con jerarquía de actores adjuntos |
| Prefab / variante / prefab anidado | Blueprint `BP_<Nombre>` / Blueprint hijo / `ChildActorComponent` |
| Instancia de prefab + overrides de transform/nombre/activo | Actor del Blueprint (resto de overrides → JSON + informe) |
| Transform | Transform relativo (Y-up m → Z-up cm, cuaterniones exactos) |
| MeshFilter + MeshRenderer | `StaticMeshComponent` / `StaticMeshActor` (primitivas → `/Engine/BasicShapes`) |
| SkinnedMeshRenderer | `SkeletalMeshComponent` (FBX importado como skeletal) |
| Light (Directional/Point/Spot/Area) | Directional/Point/Spot/RectLight (color, intensidad, rango, conos, sombras) |
| Camera | `CameraComponent` (FOV vertical → horizontal, ortográfica) |
| Box/Sphere/Capsule/CharacterController Collider | `Box/Sphere/CapsuleComponent` (triggers → overlap) |
| MeshCollider | colisión de la malla (aviso para complex collision) |
| Rigidbody (+2D) | Simulate Physics en la raíz del actor, masa, damping, gravedad, bloqueos de ejes |
| AudioSource | `AudioComponent` (sonido, volumen, pitch, auto-activación) |
| MonoBehaviour | `UActorComponent` C++ (hereda de `UUnityBehaviour`) con valores serializados asignados |
| ScriptableObject / `[Serializable]` / enum | `UPrimaryDataAsset` / `USTRUCT` / `UENUM` |
| Material (Standard, URP Lit/Unlit, HDRP Lit) | Material Instance de `M_UnityLit`/`M_UnityUnlit` (albedo, normal, metallic/smoothness, AO, emisión, tiling, blend, two-sided) |
| Texturas | Importadas con sRGB, normal map (canal verde invertido), wrap, filtro, mipmaps |
| FBX / OBJ / glTF | Static o Skeletal Mesh (escala, lightmap UVs, colisión) |
| WAV/OGG/FLAC/AIFF (MP3 con ffmpeg) | Sound Wave |
| Tags / capas | Actor Tags + Gameplay Tags / canales de colisión |
| InputManager | Enhanced Input (`IA_*` + `IMC_UnityDefault`) |
| Gravedad, escenas del build, nombre/versión | `DefaultEngine.ini` / `DefaultGame.ini` |
| RenderSettings (niebla, ambiente) | SkyAtmosphere + SkyLight + ExponentialHeightFog |
| Animator Controller | `animators.json` (estados, transiciones, blend trees) → AnimBP con agente |
| uGUI / ParticleSystem / Terrain / NavMesh / LineRenderer | Tarea manual documentada (+ agentes) |

Todo lo que no se convierte automáticamente aparece en `Unity2UE/report.md`.

## Estructura del proyecto UE generado

```
MiJuego.uproject
Config/                      DefaultEngine.ini, DefaultGame.ini, DefaultInput.ini, DefaultGameplayTags.ini
Source/MiJuego/
  UnityCompat/               UUnityBehaviour, AUnityGameObject, UUnityCompatLibrary
  Unity/...                  un .h/.cpp por script C# (UNITY2UE_STATUS: STUB → TRANSLATED)
Content/Python/unity2ue_import/   scripts de importación del editor
Unity2UE/
  report.md                  informe con errores y tareas manuales
  scripts.json               cola de traducción C# → C++
  levels/*.json, blueprints.json, materials.json, assets.json, settings.json, animators.json, ui.json
  SourceAssets/              copia de los ficheros fuente a importar
Unity2UE_Import.bat / .sh
```

## Desarrollo

```bash
pip install -e ".[dev]"
pytest -q
ruff check unity2ue tests
```

El fixture `tests/fixtures/SampleUnityProject` es un proyecto Unity mínimo (escena, prefab con
Rigidbody y script, material URP, texturas, FBX, audio, scripts) escrito a mano en YAML de Unity.
Consulta `CLAUDE.md` para las convenciones internas.

## Limitaciones conocidas

- Los scripts del editor de Unreal se han probado con UE 5.8.1 en Windows (`unity2ue full`); en CI
  sólo se validan en sintaxis. La API Python de UE cambia entre versiones: si algo falla,
  `import_log.json` indica el paso.
- La lógica C# no se traduce de forma determinista: el toolkit genera declaraciones compilables
  y los cuerpos los traducen los agentes de Claude (revisa siempre el resultado).
- Shaders personalizados, UI, animación, VFX y terrenos requieren trabajo asistido.
