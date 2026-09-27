---
name: tareas-manuales
description: Resuelve las tareas manuales que deja una conversión unity2ue (UI uGUI → UMG, Animator → Animation Blueprint, ParticleSystem → Niagara, shaders personalizados, Terrain → Landscape, clips de animación, variantes de prefab). Úsalo cuando el informe Unity2UE/report.md tenga tareas "manual" pendientes.
argument-hint: <ruta-proyecto-ue> [categoria]
---

# Tareas manuales tras la conversión

1. Lee `<ue>/Unity2UE/report.md` (sección *Tareas manuales*) y, si existe, `import_log.json`.
   Agrupa por categoría y pregunta al usuario por dónde empezar si hay muchas.
2. Para cada categoría:
   - **UI (Canvas/uGUI/TMP)** → subagente `ue-content-builder` con `ui.json`: crea Widget
     Blueprints (`WBP_<Canvas>`) y documenta el cableado de eventos (OnClicked → funciones).
   - **Animator Controllers** → `ue-content-builder` con `animators.json`: AnimBP por
     controller (`ABP_<Nombre>`), variables = parámetros, estados y transiciones documentados;
     BlendTrees → BlendSpaces. Rigs humanoides: IK Rig + IK Retargeter hacia Manny/Quinn.
   - **ParticleSystem** → sistemas Niagara a partir de plantillas, ajustando duración, loop,
     tasa y color con los datos del JSON del nivel/prefab.
   - **Shaders personalizados / Shader Graph** → lee el `.shader`/`.shadergraph` original y
     recréalo como material de UE (grafo con `MaterialEditingLibrary` o guía paso a paso);
     sustituye el parent de las Material Instances afectadas.
   - **Terrain** → pide al usuario exportar el heightmap RAW 16-bit desde Unity e impórtalo como
     Landscape (resolución válida de UE: 1009, 2017, 4033...; escala Z = altura·100/512).
   - **Clips en FBX** (`clips` en `assets.json`) → crear AnimSequences recortadas.
   - **Paquetes** (Cinemachine, Timeline, Input System, NavMesh...) → sigue la acción del informe.
3. Tras cada bloque, indica al usuario qué script ejecutar en UE y cómo verificarlo.
