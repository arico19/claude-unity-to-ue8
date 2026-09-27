#include "UnityCompat/UnityGameObject.h"

#include "Components/SceneComponent.h"

AUnityGameObject::AUnityGameObject()
{
	PrimaryActorTick.bCanEverTick = false;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
}

void AUnityGameObject::SetActive(bool bActive)
{
	SetActorHiddenInGame(!bActive);
	SetActorEnableCollision(bActive);
	SetActorTickEnabled(bActive);
	for (UActorComponent* Component : GetComponents())
	{
		if (bActive)
		{
			Component->Activate();
		}
		else
		{
			Component->Deactivate();
		}
	}
}
