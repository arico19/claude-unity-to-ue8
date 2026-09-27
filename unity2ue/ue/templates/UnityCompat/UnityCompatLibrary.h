// Funciones de ayuda para traducir llamadas habituales de la API de Unity.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "GameFramework/Actor.h"
#include "Components/SceneComponent.h"
#include "Engine/World.h"
#include "UnityCompatLibrary.generated.h"

class ACameraActor;
class UAnimSequence;

/** Unity trabaja en metros, UE en centímetros. Los valores serializados (UPROPERTY/DataAsset)
 *  se conservan en metros: multiplicar por UNITY_TO_UE al usarlos como distancia o velocidad. */
constexpr float UNITY_TO_UE = 100.f;

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

	/** new GameObject(name) [+ transform.SetParent(parent)]: actor vacío con raíz de escena. */
	UFUNCTION(BlueprintCallable, Category = "Unity", meta = (WorldContext = "WorldContextObject"))
	static AActor* NewGameObject(const UObject* WorldContextObject, const FString& Name, AActor* Parent = nullptr);

	/** gameObject.AddComponent<T>() */
	template <typename T>
	static T* AddComponent(AActor* Actor)
	{
		if (!Actor) { return nullptr; }
		T* Comp = NewObject<T>(Actor, T::StaticClass());
		if (USceneComponent* Scene = Cast<USceneComponent>(Comp))
		{
			Scene->SetupAttachment(Actor->GetRootComponent());
		}
		Actor->AddInstanceComponent(Comp);
		Comp->RegisterComponent();
		return Comp;
	}

	/** Object.Instantiate(prefab, parent/pos/rot) y devuelve GetComponent<T>() del actor creado. */
	template <typename T>
	static T* InstantiateAs(const UObject* WorldContextObject, TSubclassOf<AActor> Prefab, const FVector& Location,
		const FRotator& Rotation = FRotator::ZeroRotator, AActor* Parent = nullptr)
	{
		AActor* A = InstantiatePrefab(WorldContextObject, Prefab, Location, Rotation, Parent);
		return A ? A->FindComponentByClass<T>() : nullptr;
	}

	/** Object.Instantiate(prefab, position, rotation, parent) */
	UFUNCTION(BlueprintCallable, Category = "Unity", meta = (WorldContext = "WorldContextObject"))
	static AActor* InstantiatePrefab(const UObject* WorldContextObject, TSubclassOf<AActor> Prefab, FVector Location,
		FRotator Rotation, AActor* Parent = nullptr);

	/** Camera.main: primer CameraActor del nivel; lo pone como vista del jugador si bSetViewTarget. */
	UFUNCTION(BlueprintCallable, Category = "Unity", meta = (WorldContext = "WorldContextObject"))
	static ACameraActor* GetMainCamera(const UObject* WorldContextObject, bool bSetViewTarget = true);

	/** Animation.Play / CrossFade: reproduce el clip en el primer SkeletalMesh del actor (no hace nada si es null). */
	UFUNCTION(BlueprintCallable, Category = "Unity|Animation")
	static void PlayAnimation(AActor* Actor, UAnimSequence* Clip, bool bLoop = true);
};
