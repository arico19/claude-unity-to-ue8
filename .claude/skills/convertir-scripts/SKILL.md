---
name: convertir-scripts
description: Traduce a C++ de Unreal Engine 5.8 todos los scripts C# pendientes (stubs UNITY2UE_STATUS STUB) de un proyecto UE generado por unity2ue, usando subagentes csharp-to-cpp en paralelo. Úsalo tras `unity2ue convert` o cuando el usuario pida convertir/traducir scripts.
argument-hint: <ruta-proyecto-ue> [filtro-de-ruta]
---

# Traducción de scripts C# → C++ (UE 5.8)

Argumentos: `$ARGUMENTS` → ruta del proyecto UE generado y, opcionalmente, un filtro
(p.ej. `Assets/Scripts/Player`).

1. Lista la cola: `python -m unity2ue scripts "<ue>" --pending` (en Linux/macOS puede ser `python3`).
   Lee `Unity2UE/scripts.json`. Los ficheros STUB suelen traer ya parte de los métodos traducidos por
   el traductor de reglas (cabecera "Métodos traducidos por reglas: N; pendientes (TODO): M"): sólo
   hay que traducir los que conservan `// TODO(unity2ue)`.
2. Ordena por dependencias: primero enums/structs/ScriptableObjects/utilidades y clases base,
   después los componentes que los usan (mira `#include "Unity/..."` y las declaraciones
   adelantadas `class U...;` de cada header).
3. Agrupa en lotes de scripts independientes (≈3-6 scripts por subagente, relacionados entre sí
   en el mismo lote) y lanza varios subagentes `csharp-to-cpp` **en paralelo** en un único mensaje.
   A cada uno pásale: ruta del proyecto UE, lista de `unity_path` + `header` + `source` y el
   contexto de las clases de las que dependen (sus headers ya traducidos).
4. Cuando terminen, lanza `cpp-reviewer` sobre los ficheros traducidos (puede ser en paralelo
   por lotes). Aplica o confirma sus correcciones.
5. Vuelve a ejecutar `python -m unity2ue scripts "<ue>" --pending` hasta que no queden
   pendientes (o sólo queden los que el usuario decida dejar).
6. Informa: scripts traducidos, TODO manuales (`grep -rn "TODO(unity2ue-manual)" Source/`),
   UPROPERTY renombradas y acciones de input que hay que asignar en los Blueprints.

Nunca reescribas desde cero un fichero con `UNITY2UE_STATUS: TRANSLATED` salvo petición
explícita; edítalo.
