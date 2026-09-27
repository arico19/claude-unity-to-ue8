// Funciones de ayuda para traducir llamadas habituales de la API de Unity.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "UnityCompatLibrary.generated.h"

UCLASS()
class {{API}} UUnityCompatLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Vector en espacio Unity (m, Y arriba) -> espacio UE (cm, Z arriba). */
	UFUNCTION(BlueprintPure, Category = "Unity|Math")
	static FVector UnityToUnrealLocation(FVector UnityVector) { return FVector(UnityVector.Z, UnityVector.X, UnityVector.Y) * 100.0; }

	/** Dirección en espacio Unity -> UE (sin cambio de unidades). */
	UFUNCTION(BlueprintPure, Category = "Unity|Math")
	static FVector UnityToUnrealDirection(FVector UnityVector) { return FVector(UnityVector.Z, UnityVector.X, UnityVector.Y); }

	/** GameObject.FindWithTag */
	UFUNCTION(BlueprintCallable, Category = "Unity", meta = (WorldContext = "WorldContextObject"))
	static AActor* FindWithTag(const UObject* WorldContextObject, FName Tag);

	/** GameObject.FindGameObjectsWithTag */
	UFUNCTION(BlueprintCallable, Category = "Unity", meta = (WorldContext = "WorldContextObject"))
	static TArray<AActor*> FindGameObjectsWithTag(const UObject* WorldContextObject, FName Tag);

	/** GameObject.Find(name) — busca por etiqueta de actor (nombre en el Outliner). */
	UFUNCTION(BlueprintCallable, Category = "Unity", meta = (WorldContext = "WorldContextObject"))
	static AActor* FindByName(const UObject* WorldContextObject, const FString& Name);

	/** Random.Range(float, float) */
	UFUNCTION(BlueprintPure, Category = "Unity|Math")
	static float RandomRange(float Min, float Max) { return FMath::FRandRange(Min, Max); }

	/** Random.Range(int, int) — máximo exclusivo como en Unity. */
	UFUNCTION(BlueprintPure, Category = "Unity|Math")
	static int32 RandomRangeInt(int32 Min, int32 MaxExclusive) { return FMath::RandRange(Min, FMath::Max(Min, MaxExclusive - 1)); }

	/** Mathf.MoveTowards */
	UFUNCTION(BlueprintPure, Category = "Unity|Math")
	static float MoveTowards(float Current, float Target, float MaxDelta);

	/** Time.time */
	UFUNCTION(BlueprintPure, Category = "Unity|Time", meta = (WorldContext = "WorldContextObject"))
	static float GetTime(const UObject* WorldContextObject);

	/** SceneManager.LoadScene(name) */
	UFUNCTION(BlueprintCallable, Category = "Unity|Scene", meta = (WorldContext = "WorldContextObject"))
	static void LoadScene(const UObject* WorldContextObject, FName LevelName);
};
