---
name: unity-api-a-unreal
description: Tabla de equivalencias entre la API de Unity (C#) y la de Unreal Engine 5.8 (C++) para traducir scripts. Úsala al traducir o revisar código migrado desde Unity, o cuando el usuario pregunte "¿cómo se hace X de Unity en Unreal?".
---

# Equivalencias de API Unity → Unreal Engine 5.8

La tabla completa está en [reference.md](reference.md). Principios clave:

1. **Modelo de objetos:** GameObject = `AActor`; Component/MonoBehaviour = `UActorComponent`
   (con transform: `USceneComponent`); prefab = Blueprint (`TSubclassOf<AActor>`);
   ScriptableObject = `UPrimaryDataAsset`; escena = nivel (`UWorld`/`ULevel`).
2. **Unidades y ejes:** 1 unidad Unity = 1 m = 100 uu de UE. Vector Unity `(x,y,z)` →
   `FVector(z, x, y)`. Ángulos Euler: Unity `(x=pitch abajo, y=yaw, z=roll)` → `FRotator(-x, y, ±z)`
   (preferir cuaterniones: `(x,y,z,w)` → `FQuat(z,x,y,w)`).
3. **Ciclo de vida** (ya resuelto por `UUnityBehaviour`): Awake/OnEnable/Start en `BeginPlay`,
   Update/LateUpdate/FixedUpdate en `TickComponent`, OnDisable/OnDestroy en `EndPlay`.
4. **Memoria:** nunca `new` para UObjects (`NewObject<T>()`, `CreateDefaultSubobject<T>()` en
   constructor, `SpawnActor` para actores); miembros UObject con `UPROPERTY()` + `TObjectPtr`.
5. **null:** usa `IsValid(Ptr)` (cubre objetos pendientes de destrucción, como el `==` de Unity).
