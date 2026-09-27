// Actor genérico que representa un GameObject de Unity sin componente principal.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "UnityGameObject.generated.h"

UCLASS(Blueprintable)
class {{API}} AUnityGameObject : public AActor
{
	GENERATED_BODY()

public:
	AUnityGameObject();

	/** Capa (layer) original de Unity. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Unity")
	int32 UnityLayer = 0;

	/** GameObject.isStatic */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Unity")
	bool bUnityStatic = false;

	/** GameObject.SetActive(bool) */
	UFUNCTION(BlueprintCallable, Category = "Unity")
	void SetActive(bool bActive);

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Unity")
	TObjectPtr<USceneComponent> Root;
};
