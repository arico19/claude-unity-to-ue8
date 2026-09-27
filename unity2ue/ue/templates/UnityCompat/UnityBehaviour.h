// Capa de compatibilidad Unity -> Unreal generada por unity2ue.
// UUnityBehaviour reproduce el ciclo de vida de MonoBehaviour sobre UActorComponent.
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Engine/EngineTypes.h"
#include "Engine/TimerHandle.h"
#include "GameFramework/Actor.h"
#include "InputCoreTypes.h"
#include "UnityBehaviour.generated.h"

DECLARE_LOG_CATEGORY_EXTERN(LogUnity, Log, All);

/** Equivalente a UnityEvent sin parámetros. */
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FUnityEvent);

/** Debug.Log / LogWarning / LogError */
#define UNITY_LOG(Format, ...) UE_LOG(LogUnity, Log, TEXT(Format), ##__VA_ARGS__)
#define UNITY_LOG_WARNING(Format, ...) UE_LOG(LogUnity, Warning, TEXT(Format), ##__VA_ARGS__)
#define UNITY_LOG_ERROR(Format, ...) UE_LOG(LogUnity, Error, TEXT(Format), ##__VA_ARGS__)

/**
 * Base de todos los MonoBehaviour convertidos.
 *
 * Orden de llamadas (aproximado al de Unity):
 *   BeginPlay  -> Awake(), OnEnable(), Start()
 *   Tick       -> FixedUpdate() (paso fijo acumulado), Update(), LateUpdate(), OnTriggerStay()
 *   EndPlay    -> OnDisable(), OnDestroy()
 *   Overlaps / Hits de los UPrimitiveComponent del actor -> OnTriggerEnter/Exit, OnCollisionEnter
 */
UCLASS(Abstract, ClassGroup = (Unity))
class {{API}} UUnityBehaviour : public UActorComponent
{
	GENERATED_BODY()

public:
	UUnityBehaviour();

	/** Paso fijo de FixedUpdate (Time.fixedDeltaTime en Unity, 0.02 por defecto). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Unity")
	float FixedDeltaTime = 0.02f;

	/** behaviour.enabled */
	UFUNCTION(BlueprintCallable, Category = "Unity")
	void SetEnabled(bool bNewEnabled);

	UFUNCTION(BlueprintPure, Category = "Unity")
	bool IsEnabled() const { return IsActive(); }

	// --- Atajos estilo Unity -------------------------------------------------
	/** gameObject */
	AActor* GetGameObject() const { return GetOwner(); }
	/** transform */
	USceneComponent* GetTransform() const;
	/** GetComponent<T>() */
	template <typename T>
	T* GetComponent() const { return GetOwner() ? GetOwner()->FindComponentByClass<T>() : nullptr; }
	/** GetComponents<T>() */
	template <typename T>
	TArray<T*> GetComponents() const
	{
		TArray<T*> Out;
		if (GetOwner()) { GetOwner()->GetComponents<T>(Out); }
		return Out;
	}
	/** CompareTag(tag) — los tags de Unity se guardan en AActor::Tags */
	UFUNCTION(BlueprintPure, Category = "Unity")
	bool CompareTag(FName Tag) const;
	/** Instantiate(prefab, position, rotation) */
	UFUNCTION(BlueprintCallable, Category = "Unity")
	AActor* Instantiate(TSubclassOf<AActor> Prefab, FVector Location, FRotator Rotation);
	/** Destroy(obj, delay) */
	UFUNCTION(BlueprintCallable, Category = "Unity")
	void DestroyActor(AActor* Target, float Delay = 0.f);
	/** Invoke(name, delay) */
	void InvokeAfter(float Delay, TFunction<void()> Callback);
	/** InvokeRepeating(name, delay, rate) */
	FTimerHandle InvokeRepeating(float Delay, float Rate, TFunction<void()> Callback);

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
	virtual void Activate(bool bReset = false) override;
	virtual void Deactivate() override;

	// --- Mensajes de Unity: sobrescribir en las clases convertidas ------------
	virtual void Awake() {}
	virtual void Start() {}
	virtual void OnEnable() {}
	virtual void OnDisable() {}
	virtual void OnDestroy() {}
	virtual void Update(float DeltaTime) {}
	virtual void LateUpdate(float DeltaTime) {}
	virtual void FixedUpdate(float InFixedDeltaTime) {}
	virtual void OnTriggerEnter(AActor* Other) {}
	virtual void OnTriggerExit(AActor* Other) {}
	virtual void OnTriggerStay(AActor* Other) {}
	virtual void OnCollisionEnter(AActor* Other, const FHitResult& Hit) {}
	virtual void OnMouseDown() {}
	virtual void OnMouseEnter() {}
	virtual void OnMouseExit() {}
	virtual void OnApplicationQuit() {}

private:
	UFUNCTION()
	void HandleBeginOverlap(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor, UPrimitiveComponent* OtherComp,
		int32 OtherBodyIndex, bool bFromSweep, const FHitResult& SweepResult);
	UFUNCTION()
	void HandleEndOverlap(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor, UPrimitiveComponent* OtherComp,
		int32 OtherBodyIndex);
	UFUNCTION()
	void HandleHit(UPrimitiveComponent* HitComponent, AActor* OtherActor, UPrimitiveComponent* OtherComp,
		FVector NormalImpulse, const FHitResult& Hit);
	UFUNCTION()
	void HandleClicked(AActor* TouchedActor, FKey ButtonPressed);
	UFUNCTION()
	void HandleCursorOver(AActor* TouchedActor);
	UFUNCTION()
	void HandleCursorOut(AActor* TouchedActor);

	float FixedTimeAccumulator = 0.f;
	bool bStarted = false;
};
