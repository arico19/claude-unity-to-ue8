#include "UnityCompat/UnityCompatLibrary.h"

#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Kismet/GameplayStatics.h"
#include "Camera/CameraActor.h"
#include "Components/SkeletalMeshComponent.h"
#include "Animation/AnimSequence.h"
#include "Engine/SkeletalMesh.h"
#include "GameFramework/PlayerController.h"

AActor* UUnityCompatLibrary::FindWithTag(const UObject* WorldContextObject, FName Tag)
{
	UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::LogAndReturnNull) : nullptr;
	if (!World)
	{
		return nullptr;
	}
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		if (It->ActorHasTag(Tag))
		{
			return *It;
		}
	}
	return nullptr;
}

TArray<AActor*> UUnityCompatLibrary::FindGameObjectsWithTag(const UObject* WorldContextObject, FName Tag)
{
	TArray<AActor*> Out;
	UGameplayStatics::GetAllActorsWithTag(WorldContextObject, Tag, Out);
	return Out;
}

AActor* UUnityCompatLibrary::FindByName(const UObject* WorldContextObject, const FString& Name)
{
	UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::LogAndReturnNull) : nullptr;
	if (!World)
	{
		return nullptr;
	}
	for (TActorIterator<AActor> It(World); It; ++It)
	{
#if WITH_EDITOR
		if (It->GetActorLabel() == Name)
		{
			return *It;
		}
#endif
		if (It->GetName() == Name || It->ActorHasTag(FName(*FString::Printf(TEXT("Name:%s"), *Name))))
		{
			return *It;
		}
	}
	return nullptr;
}

float UUnityCompatLibrary::MoveTowards(float Current, float Target, float MaxDelta)
{
	if (FMath::Abs(Target - Current) <= MaxDelta)
	{
		return Target;
	}
	return Current + FMath::Sign(Target - Current) * MaxDelta;
}

float UUnityCompatLibrary::GetTime(const UObject* WorldContextObject)
{
	return UGameplayStatics::GetTimeSeconds(WorldContextObject);
}

void UUnityCompatLibrary::LoadScene(const UObject* WorldContextObject, FName LevelName)
{
	UGameplayStatics::OpenLevel(WorldContextObject, LevelName);
}


AActor* UUnityCompatLibrary::NewGameObject(const UObject* WorldContextObject, const FString& Name, AActor* Parent)
{
	UWorld* World = GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::LogAndReturnNull);
	if (!World) { return nullptr; }
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AActor* Actor = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
	if (!Actor) { return nullptr; }
	USceneComponent* Root = NewObject<USceneComponent>(Actor, TEXT("Root"));
	Root->SetMobility(EComponentMobility::Movable);
	Actor->SetRootComponent(Root);
	Actor->AddInstanceComponent(Root);
	Root->RegisterComponent();
#if WITH_EDITOR
	Actor->SetActorLabel(Name);
#endif
	if (Parent)
	{
		Actor->AttachToActor(Parent, FAttachmentTransformRules::KeepWorldTransform);
	}
	return Actor;
}

AActor* UUnityCompatLibrary::InstantiatePrefab(const UObject* WorldContextObject, TSubclassOf<AActor> Prefab,
	FVector Location, FRotator Rotation, AActor* Parent)
{
	UWorld* World = GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::LogAndReturnNull);
	if (!World || !*Prefab) { return nullptr; }
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AActor* Actor = World->SpawnActor<AActor>(Prefab, Location, Rotation, Params);
	if (Actor && Parent)
	{
		Actor->AttachToActor(Parent, FAttachmentTransformRules::KeepWorldTransform);
	}
	return Actor;
}

ACameraActor* UUnityCompatLibrary::GetMainCamera(const UObject* WorldContextObject, bool bSetViewTarget)
{
	ACameraActor* Cam = Cast<ACameraActor>(UGameplayStatics::GetActorOfClass(WorldContextObject, ACameraActor::StaticClass()));
	if (Cam && bSetViewTarget)
	{
		if (APlayerController* PC = UGameplayStatics::GetPlayerController(WorldContextObject, 0))
		{
			PC->SetViewTarget(Cam);
		}
	}
	return Cam;
}

void UUnityCompatLibrary::PlayAnimation(AActor* Actor, UAnimSequence* Clip, bool bLoop)
{
	if (!Actor || !Clip) { return; }
	if (USkeletalMeshComponent* Mesh = Actor->FindComponentByClass<USkeletalMeshComponent>())
	{
		if (Mesh->GetSkeletalMeshAsset() && Clip->GetSkeleton() == Mesh->GetSkeletalMeshAsset()->GetSkeleton())
		{
			Mesh->PlayAnimation(Clip, bLoop);
		}
	}
}
