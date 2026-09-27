// Capa de compatibilidad Unity -> Unreal generada por unity2ue.
#include "UnityCompat/UnityBehaviour.h"

#include "Components/PrimitiveComponent.h"
#include "Engine/World.h"
#include "TimerManager.h"

DEFINE_LOG_CATEGORY(LogUnity);

UUnityBehaviour::UUnityBehaviour()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.bStartWithTickEnabled = true;
	bAutoActivate = true;
}

USceneComponent* UUnityBehaviour::GetTransform() const
{
	return GetOwner() ? GetOwner()->GetRootComponent() : nullptr;
}

bool UUnityBehaviour::CompareTag(FName Tag) const
{
	return GetOwner() && GetOwner()->ActorHasTag(Tag);
}

AActor* UUnityBehaviour::Instantiate(TSubclassOf<AActor> Prefab, FVector Location, FRotator Rotation)
{
	UWorld* World = GetWorld();
	if (!World || !*Prefab)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	return World->SpawnActor<AActor>(Prefab, Location, Rotation, Params);
}

void UUnityBehaviour::DestroyActor(AActor* Target, float Delay)
{
	if (!IsValid(Target))
	{
		return;
	}
	if (Delay <= 0.f)
	{
		Target->Destroy();
	}
	else
	{
		Target->SetLifeSpan(Delay);
	}
}

void UUnityBehaviour::InvokeAfter(float Delay, TFunction<void()> Callback)
{
	if (UWorld* World = GetWorld())
	{
		FTimerHandle Handle;
		World->GetTimerManager().SetTimer(Handle, FTimerDelegate::CreateLambda(MoveTemp(Callback)), FMath::Max(Delay, KINDA_SMALL_NUMBER), false);
	}
}

FTimerHandle UUnityBehaviour::InvokeRepeating(float Delay, float Rate, TFunction<void()> Callback)
{
	FTimerHandle Handle;
	if (UWorld* World = GetWorld())
	{
		World->GetTimerManager().SetTimer(Handle, FTimerDelegate::CreateLambda(MoveTemp(Callback)), Rate, true, Delay);
	}
	return Handle;
}

void UUnityBehaviour::SetEnabled(bool bNewEnabled)
{
	if (bNewEnabled)
	{
		Activate();
	}
	else
	{
		Deactivate();
	}
}

void UUnityBehaviour::BeginPlay()
{
	Super::BeginPlay();

	if (AActor* Owner = GetOwner())
	{
		TArray<UPrimitiveComponent*> Primitives;
		Owner->GetComponents<UPrimitiveComponent>(Primitives);
		for (UPrimitiveComponent* Primitive : Primitives)
		{
			Primitive->OnComponentBeginOverlap.AddUniqueDynamic(this, &UUnityBehaviour::HandleBeginOverlap);
			Primitive->OnComponentEndOverlap.AddUniqueDynamic(this, &UUnityBehaviour::HandleEndOverlap);
			Primitive->OnComponentHit.AddUniqueDynamic(this, &UUnityBehaviour::HandleHit);
		}
		Owner->OnClicked.AddUniqueDynamic(this, &UUnityBehaviour::HandleClicked);
		Owner->OnBeginCursorOver.AddUniqueDynamic(this, &UUnityBehaviour::HandleCursorOver);
		Owner->OnEndCursorOver.AddUniqueDynamic(this, &UUnityBehaviour::HandleCursorOut);
	}

	Awake();
	if (IsActive())
	{
		OnEnable();
		Start();
		bStarted = true;
	}
}

void UUnityBehaviour::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (IsActive())
	{
		OnDisable();
	}
	if (EndPlayReason == EEndPlayReason::Quit || EndPlayReason == EEndPlayReason::EndPlayInEditor)
	{
		OnApplicationQuit();
	}
	OnDestroy();
	Super::EndPlay(EndPlayReason);
}

void UUnityBehaviour::Activate(bool bReset)
{
	const bool bWasActive = IsActive();
	Super::Activate(bReset);
	if (!bWasActive && IsActive() && HasBegunPlay())
	{
		OnEnable();
		if (!bStarted)
		{
			Start();
			bStarted = true;
		}
	}
}

void UUnityBehaviour::Deactivate()
{
	const bool bWasActive = IsActive();
	Super::Deactivate();
	if (bWasActive && !IsActive() && HasBegunPlay())
	{
		OnDisable();
	}
}

void UUnityBehaviour::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	if (FixedDeltaTime > 0.f)
	{
		FixedTimeAccumulator += DeltaTime;
		int32 Steps = 0;
		while (FixedTimeAccumulator >= FixedDeltaTime && Steps < 8)
		{
			FixedUpdate(FixedDeltaTime);
			FixedTimeAccumulator -= FixedDeltaTime;
			++Steps;
		}
	}

	Update(DeltaTime);
	LateUpdate(DeltaTime);

	if (AActor* Owner = GetOwner())
	{
		TArray<AActor*> Overlapping;
		Owner->GetOverlappingActors(Overlapping);
		for (AActor* Other : Overlapping)
		{
			OnTriggerStay(Other);
		}
	}
}

void UUnityBehaviour::HandleBeginOverlap(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor,
	UPrimitiveComponent* OtherComp, int32 OtherBodyIndex, bool bFromSweep, const FHitResult& SweepResult)
{
	if (IsActive() && OtherActor && OtherActor != GetOwner())
	{
		OnTriggerEnter(OtherActor);
	}
}

void UUnityBehaviour::HandleEndOverlap(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor,
	UPrimitiveComponent* OtherComp, int32 OtherBodyIndex)
{
	if (IsActive() && OtherActor && OtherActor != GetOwner())
	{
		OnTriggerExit(OtherActor);
	}
}

void UUnityBehaviour::HandleHit(UPrimitiveComponent* HitComponent, AActor* OtherActor, UPrimitiveComponent* OtherComp,
	FVector NormalImpulse, const FHitResult& Hit)
{
	if (IsActive() && OtherActor && OtherActor != GetOwner())
	{
		OnCollisionEnter(OtherActor, Hit);
	}
}

void UUnityBehaviour::HandleClicked(AActor* TouchedActor, FKey ButtonPressed)
{
	if (IsActive())
	{
		OnMouseDown();
	}
}

void UUnityBehaviour::HandleCursorOver(AActor* TouchedActor)
{
	if (IsActive())
	{
		OnMouseEnter();
	}
}

void UUnityBehaviour::HandleCursorOut(AActor* TouchedActor)
{
	if (IsActive())
	{
		OnMouseExit();
	}
}
