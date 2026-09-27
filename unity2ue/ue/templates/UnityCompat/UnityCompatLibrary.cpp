#include "UnityCompat/UnityCompatLibrary.h"

#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Kismet/GameplayStatics.h"

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
