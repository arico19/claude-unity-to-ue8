#include "UnityCompat/UnityCompatLibrary.h"
#include "UnityCompat/UnityGameObject.h"

#include "Engine/Engine.h"
#include "Misc/ConfigCacheIni.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Kismet/GameplayStatics.h"
#include "Camera/CameraActor.h"
#include "Components/SkeletalMeshComponent.h"
#include "Animation/AnimSequence.h"
#include "Engine/SkeletalMesh.h"
#include "GameFramework/PlayerController.h"
#include "Engine/Blueprint.h"
#include "Engine/SimpleConstructionScript.h"
#include "Engine/SCS_Node.h"

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

bool UUnityCompatLibrary::SetComponentAttachSocket(UBlueprint* Blueprint, FName ComponentName, FName SocketName)
{
#if WITH_EDITOR
	if (!Blueprint || !Blueprint->SimpleConstructionScript)
	{
		return false;
	}
	if (USCS_Node* Node = Blueprint->SimpleConstructionScript->FindSCSNode(ComponentName))
	{
		Blueprint->Modify();
		Node->Modify();
		Node->AttachToName = SocketName;
		return true;
	}
#endif
	return false;
}

void UUnityCompatLibrary::SetActive(AActor* Actor, bool bActive)
{
	if (!Actor)
	{
		return;
	}
	if (AUnityGameObject* Go = Cast<AUnityGameObject>(Actor))
	{
		Go->SetActive(bActive);
		return;
	}
	Actor->SetActorHiddenInGame(!bActive);
	Actor->SetActorEnableCollision(bActive);
	Actor->SetActorTickEnabled(bActive);
	for (UActorComponent* Component : Actor->GetComponents())
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

static const TCHAR* UnityPrefsSection = TEXT("UnityPlayerPrefs");

int32 UUnityCompatLibrary::PrefsGetInt(const FString& Key, int32 Default)
{
	int32 Value = Default;
	GConfig->GetInt(UnityPrefsSection, *Key, Value, GGameUserSettingsIni);
	return Value;
}

void UUnityCompatLibrary::PrefsSetInt(const FString& Key, int32 Value)
{
	GConfig->SetInt(UnityPrefsSection, *Key, Value, GGameUserSettingsIni);
}

float UUnityCompatLibrary::PrefsGetFloat(const FString& Key, float Default)
{
	float Value = Default;
	GConfig->GetFloat(UnityPrefsSection, *Key, Value, GGameUserSettingsIni);
	return Value;
}

void UUnityCompatLibrary::PrefsSetFloat(const FString& Key, float Value)
{
	GConfig->SetFloat(UnityPrefsSection, *Key, Value, GGameUserSettingsIni);
}

FString UUnityCompatLibrary::PrefsGetString(const FString& Key, const FString& Default)
{
	FString Value = Default;
	GConfig->GetString(UnityPrefsSection, *Key, Value, GGameUserSettingsIni);
	return Value;
}

void UUnityCompatLibrary::PrefsSetString(const FString& Key, const FString& Value)
{
	GConfig->SetString(UnityPrefsSection, *Key, *Value, GGameUserSettingsIni);
}

bool UUnityCompatLibrary::PrefsHasKey(const FString& Key)
{
	FString Value;
	return GConfig->GetString(UnityPrefsSection, *Key, Value, GGameUserSettingsIni);
}

void UUnityCompatLibrary::PrefsDeleteKey(const FString& Key)
{
	GConfig->RemoveKey(UnityPrefsSection, *Key, GGameUserSettingsIni);
}

void UUnityCompatLibrary::PrefsDeleteAll()
{
	GConfig->EmptySection(UnityPrefsSection, GGameUserSettingsIni);
}

void UUnityCompatLibrary::PrefsSave()
{
	GConfig->Flush(false, GGameUserSettingsIni);
}
