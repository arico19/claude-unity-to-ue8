# unity2ue — Conversor de proyectos Unity → Unreal Engine 5.8

Este repositorio es un proyecto de Claude Code para migrar un proyecto completo de Unity
(escenas, prefabs, GameObjects y todos sus componentes, materiales, assets y scripts C#)
a un proyecto de Unreal Engine 5.8.

## Arquitectura (léela antes de tocar nada)

La conversión tiene tres capas:

1. **Toolkit Python determinista (`unity2ue/`)** — se ejecuta fuera de Unreal.
   - `unity/` lee el proyecto Unity: YAML serializado (`yaml_parser.py`), GUIDs de `.meta`
     (`assets.py`), ajustes de `ProjectSettings/` (`project.py`).
   - `convert/` traduce a un formato intermedio JSON neutral:
     `hierarchy.py` (escenas/prefabs → árboles de nodos), `components.py` (un conversor por
     classID de Unity), `materials.py`, `animators.py`, `coords.py` (cambio de ejes/unidades),
     `csharp.py` (parser C#) + `cpp_gen.py`/`type_map.py` (esqueletos C++).
   - `ue/project_gen.py` genera el `.uproject`, el módulo C++ y `Config/*.ini`.
   - `pipeline.py` orquesta todo; `cli.py` expone `analyze`, `convert`, `scripts`.
2. **Scripts del editor de Unreal (`unity2ue/ue_editor/unity2ue_import/`)** — se copian a
   `<ProyectoUE>/Content/Python/` y se ejecutan DENTRO de Unreal (`import unreal`): importan
   assets, crean materiales maestros + instancias, Blueprints (prefabs) y niveles (escenas).
   En CI sólo se comprueba que compilan (`tests/test_ue_editor_scripts.py`); con UE 5.8 instalado
   se prueban de verdad con `python -m unity2ue ue <DestinoUE>` (`ue_runner.py`: compila, importa,
   `verify.py` y `screenshots.py`). Los reimports reutilizan Blueprints y niveles existentes: borrar
   y recrear un asset con el mismo nombre en la misma sesión falla en UE 5.8.
3. **Agentes de Claude Code (`.claude/`)** — hacen lo que no es determinista: traducir los
   cuerpos de los métodos C# a C++ de UE, recrear UI/animación/VFX, revisar el resultado.

## Comandos

```bash
python3 -m unity2ue analyze <ProyectoUnity>                    # inventario + riesgos (no escribe)
python3 -m unity2ue convert <ProyectoUnity> <DestinoUE> --name MiJuego
python3 -m unity2ue scripts <DestinoUE> --pending              # cola de traducción C# -> C++
python3 -m unity2ue full <ProyectoUnity> <DestinoUE> --name MiJuego  # todo: convert + UE (compilar, importar, verificar, capturas)
python3 -m unity2ue ue <DestinoUE> [--steps import,verify,screenshots]  # sólo los pasos dentro de UE
python3 -m pytest -q                                           # tests (fixture: tests/fixtures/SampleUnityProject)
ruff check unity2ue tests
```

Skills (slash commands) del proyecto:
- `/convertir-proyecto <ProyectoUnity> <DestinoUE>` — flujo completo de principio a fin.
- `/convertir-scripts <DestinoUE>` — traduce los scripts pendientes con subagentes en paralelo.
- `/tareas-manuales <DestinoUE>` — UI → UMG, Animator → AnimBP, partículas → Niagara, shaders.

Subagentes: `unity-analyzer`, `csharp-to-cpp`, `cpp-reviewer`, `ue-content-builder`.

## Convenciones de conversión (no cambiarlas sin actualizar tests)

- **Ejes:** Unity (Y arriba, Z adelante, m) → UE (Z arriba, X adelante, cm):
  `UE.X = Unity.Z·100`, `UE.Y = Unity.X·100`, `UE.Z = Unity.Y·100`. Ambos son de mano
  izquierda, así que los cuaterniones se transforman igual: `(x,y,z,w) → (z,x,y,w)`.
- **Rotator de UE** en Python: `unreal.Rotator(roll=, pitch=, yaw=)` (¡el orden posicional es
  roll, pitch, yaw!). En el JSON guardamos `rotation` como `[pitch, yaw, roll]` y
  `rotation_quat` como fuente de verdad.
- **Rutas:** `Assets/A/B/x.png` → `/Game/Unity/A/B/x`; materiales `MI_`, prefabs `BP_`,
  niveles `/Game/Unity/Maps/<Escena>`, modelos en carpeta propia `/Game/Unity/.../<Modelo>/`.
- **Scripts:** `MonoBehaviour` → `UActorComponent` derivado de `UUnityBehaviour`
  (`unity2ue/ue/templates/UnityCompat/`), que invoca Awake/Start/Update/FixedUpdate/
  OnTrigger*/OnCollisionEnter. `ScriptableObject` → `UPrimaryDataAsset`. `[Serializable]` →
  `USTRUCT`. Los nombres que chocan con el motor reciben sufijo (`Rotator` → `URotatorComponent`).
- **Estado de traducción:** cada `.h/.cpp` generado lleva `// UNITY2UE_STATUS: STUB`. Al
  traducirlo se cambia a `TRANSLATED` en ambos ficheros. `convert` **nunca** sobrescribe un
  fichero `TRANSLATED` (hay test que lo garantiza).
- **Nombres de UPROPERTY:** `moveSpeed` → `MoveSpeed` (`naming.cpp_property_name`). El mapa real
  por clase está en `ScriptPlan.field_maps` y se usa para asignar valores serializados en los
  niveles. Si renombras una propiedad al traducir, actualiza también los datos o el log del editor
  avisará de que no pudo asignar el valor.

## Reglas para trabajar en este repo

- Todo cambio en conversores necesita test en `tests/`. Amplía el fixture
  `tests/fixtures/SampleUnityProject` (YAML de Unity escrito a mano, con `.meta` y GUIDs
  de 32 hex) en lugar de mockear.
- Los scripts de `ue_editor/` usan sólo la API Python pública del editor de UE 5.x. Envuelve
  cada asignación en `set_prop()` y registra fallos con `LOG` en vez de abortar: un asset roto
  no debe detener la importación de los demás.
- Un componente de Unity sin conversor debe registrarse como incidencia `manual`, nunca
  ignorarse en silencio.
- Textos para el usuario (informes, logs, docs) en español.
