// Generado por unity2ue (steam integrate). Se regenera: no lo edites, amplíalo en otra clase.
#include "Steam/SteamIntegrationSubsystem.h"

#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "HAL/PlatformTime.h"
#include "Modules/ModuleManager.h"

#if UNITY2UE_WITH_STEAM
#include "SteamSharedModule.h"
THIRD_PARTY_INCLUDES_START
#include "steam/steam_api.h"
THIRD_PARTY_INCLUDES_END
#endif

DEFINE_LOG_CATEGORY_STATIC(LogUnitySteam, Log, All);

namespace
{
	// Steam limita StoreStats: agrupar los cambios de estadísticas.
	constexpr double StoreStatsInterval = 10.0;

#if UNITY2UE_WITH_STEAM
	bool SteamReady()
	{
		// Sin las DLL de Steam cargadas (editor, plataforma sin Steam) no se toca la API.
		if (!FModuleManager::Get().IsModuleLoaded(TEXT("SteamShared")) || !FSteamSharedModule::Get().AreSteamDllsLoaded())
		{
			return false;
		}
		return SteamAPI_IsSteamRunning() && SteamUserStats() != nullptr && SteamUtils() != nullptr;
	}
#endif
}

void USteamIntegrationSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	TickHandle = FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateUObject(this, &USteamIntegrationSubsystem::Tick), 0.25f);
	UE_LOG(LogUnitySteam, Log, TEXT("Steam %s"), IsSteamAvailable() ? TEXT("disponible") : TEXT("no disponible (las llamadas no harán nada)"));
}

void USteamIntegrationSubsystem::Deinitialize()
{
	FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	if (bStatsDirty)
	{
		StoreStats();
	}
	Super::Deinitialize();
}

USteamIntegrationSubsystem* USteamIntegrationSubsystem::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	const UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
	return GI ? GI->GetSubsystem<USteamIntegrationSubsystem>() : nullptr;
}

bool USteamIntegrationSubsystem::IsSteamAvailable() const
{
#if UNITY2UE_WITH_STEAM
	return SteamReady();
#else
	return false;
#endif
}

int64 USteamIntegrationSubsystem::GetAppId() const
{
#if UNITY2UE_WITH_STEAM
	return SteamReady() ? static_cast<int64>(SteamUtils()->GetAppID()) : 0;
#else
	return 0;
#endif
}

FString USteamIntegrationSubsystem::GetPlayerName() const
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady() && SteamFriends())
	{
		return UTF8_TO_TCHAR(SteamFriends()->GetPersonaName());
	}
#endif
	return FString();
}

FString USteamIntegrationSubsystem::GetSteamLanguage() const
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady() && SteamApps())
	{
		return UTF8_TO_TCHAR(SteamApps()->GetCurrentGameLanguage());
	}
#endif
	return FString();
}

bool USteamIntegrationSubsystem::IsRunningOnSteamDeck() const
{
#if UNITY2UE_WITH_STEAM
	return SteamReady() && SteamUtils()->IsSteamRunningOnSteamDeck();
#else
	return false;
#endif
}

// ---------------------------------------------------------------------- Logros

bool USteamIntegrationSubsystem::UnlockAchievement(const FString& AchievementId)
{
#if UNITY2UE_WITH_STEAM
	if (!SteamReady())
	{
		return false;
	}
	if (!SteamUserStats()->SetAchievement(TCHAR_TO_UTF8(*AchievementId)))
	{
		UE_LOG(LogUnitySteam, Warning, TEXT("No se pudo desbloquear el logro '%s' (¿existe en Steamworks y está publicado?)"), *AchievementId);
		return false;
	}
	return StoreStats();
#else
	return false;
#endif
}

bool USteamIntegrationSubsystem::IsAchievementUnlocked(const FString& AchievementId) const
{
#if UNITY2UE_WITH_STEAM
	bool bAchieved = false;
	return SteamReady() && SteamUserStats()->GetAchievement(TCHAR_TO_UTF8(*AchievementId), &bAchieved) && bAchieved;
#else
	return false;
#endif
}

bool USteamIntegrationSubsystem::ShowAchievementProgress(const FString& AchievementId, int32 Current, int32 Max)
{
#if UNITY2UE_WITH_STEAM
	return SteamReady() && Current >= 0 && Max > 0 &&
		SteamUserStats()->IndicateAchievementProgress(TCHAR_TO_UTF8(*AchievementId), static_cast<uint32>(Current), static_cast<uint32>(Max));
#else
	return false;
#endif
}

bool USteamIntegrationSubsystem::ResetAllStats(bool bAlsoAchievements)
{
#if UNITY2UE_WITH_STEAM && !UE_BUILD_SHIPPING
	return SteamReady() && SteamUserStats()->ResetAllStats(bAlsoAchievements) && StoreStats();
#else
	return false;
#endif
}

// ---------------------------------------------------------------------- Estadísticas

bool USteamIntegrationSubsystem::SetStatInt(const FString& StatId, int32 Value)
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady() && SteamUserStats()->SetStat(TCHAR_TO_UTF8(*StatId), Value))
	{
		bStatsDirty = true;
		return true;
	}
	UE_LOG(LogUnitySteam, Verbose, TEXT("SetStat '%s' ignorado"), *StatId);
#endif
	return false;
}

bool USteamIntegrationSubsystem::SetStatFloat(const FString& StatId, float Value)
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady() && SteamUserStats()->SetStat(TCHAR_TO_UTF8(*StatId), Value))
	{
		bStatsDirty = true;
		return true;
	}
#endif
	return false;
}

bool USteamIntegrationSubsystem::AddToStatInt(const FString& StatId, int32 Amount)
{
	return SetStatInt(StatId, GetStatInt(StatId) + Amount);
}

int32 USteamIntegrationSubsystem::GetStatInt(const FString& StatId) const
{
	int32 Value = 0;
#if UNITY2UE_WITH_STEAM
	if (SteamReady())
	{
		SteamUserStats()->GetStat(TCHAR_TO_UTF8(*StatId), &Value);
	}
#endif
	return Value;
}

float USteamIntegrationSubsystem::GetStatFloat(const FString& StatId) const
{
	float Value = 0.f;
#if UNITY2UE_WITH_STEAM
	if (SteamReady())
	{
		SteamUserStats()->GetStat(TCHAR_TO_UTF8(*StatId), &Value);
	}
#endif
	return Value;
}

bool USteamIntegrationSubsystem::StoreStats()
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady() && SteamUserStats()->StoreStats())
	{
		bStatsDirty = false;
		LastStoreTime = FPlatformTime::Seconds();
		return true;
	}
#endif
	return false;
}

// ---------------------------------------------------------------------- Marcadores

void USteamIntegrationSubsystem::UploadLeaderboardScore(const FString& LeaderboardName, int32 Score, bool bKeepBest)
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady())
	{
		PendingScores.Add({LeaderboardName, Score, bKeepBest});
		return;
	}
#endif
	OnLeaderboardScoreUploaded.Broadcast(LeaderboardName, Score, false);
}

void USteamIntegrationSubsystem::TickLeaderboards()
{
#if UNITY2UE_WITH_STEAM
	// Las llamadas asíncronas de Steam se consultan desde el hilo de juego (sin CCallResult, que
	// OnlineSubsystemSteam despacharía en su propio hilo).
	if (CurrentCall != k_uAPICallInvalid)
	{
		bool bFailed = false;
		if (!SteamUtils()->IsAPICallCompleted(CurrentCall, &bFailed))
		{
			return;
		}
		const FPendingScore Pending = PendingScores.Num() ? PendingScores[0] : FPendingScore();
		bool bOk = false;
		if (bCurrentCallIsFind)
		{
			LeaderboardFindResult_t Result{};
			if (SteamUtils()->GetAPICallResult(CurrentCall, &Result, sizeof(Result), LeaderboardFindResult_t::k_iCallback, &bFailed)
				&& !bFailed && Result.m_bLeaderboardFound)
			{
				LeaderboardHandles.Add(Pending.Leaderboard, Result.m_hSteamLeaderboard);
				CurrentCall = k_uAPICallInvalid;
				return;  // el siguiente tick sube la puntuación
			}
			UE_LOG(LogUnitySteam, Warning, TEXT("Marcador '%s' no encontrado: créalo en Steamworks (ver Steam/checklist.md)"), *Pending.Leaderboard);
		}
		else
		{
			LeaderboardScoreUploaded_t Result{};
			bOk = SteamUtils()->GetAPICallResult(CurrentCall, &Result, sizeof(Result), LeaderboardScoreUploaded_t::k_iCallback, &bFailed)
				&& !bFailed && Result.m_bSuccess;
		}
		CurrentCall = k_uAPICallInvalid;
		if (PendingScores.Num())
		{
			PendingScores.RemoveAt(0);
		}
		OnLeaderboardScoreUploaded.Broadcast(Pending.Leaderboard, Pending.Score, bOk);
		return;
	}
	if (PendingScores.Num() == 0)
	{
		return;
	}
	const FPendingScore& Next = PendingScores[0];
	if (const uint64* Handle = LeaderboardHandles.Find(Next.Leaderboard))
	{
		bCurrentCallIsFind = false;
		CurrentCall = SteamUserStats()->UploadLeaderboardScore(
			static_cast<SteamLeaderboard_t>(*Handle),
			Next.bKeepBest ? k_ELeaderboardUploadScoreMethodKeepBest : k_ELeaderboardUploadScoreMethodForceUpdate,
			Next.Score, nullptr, 0);
	}
	else
	{
		bCurrentCallIsFind = true;
		CurrentCall = SteamUserStats()->FindLeaderboard(TCHAR_TO_UTF8(*Next.Leaderboard));
	}
	if (CurrentCall == k_uAPICallInvalid)
	{
		const FPendingScore Failed = Next;
		PendingScores.RemoveAt(0);
		OnLeaderboardScoreUploaded.Broadcast(Failed.Leaderboard, Failed.Score, false);
	}
#endif
}

// ---------------------------------------------------------------------- Presencia

bool USteamIntegrationSubsystem::SetRichPresenceStatus(const FString& Token)
{
	return SetRichPresence(TEXT("steam_display"), Token);
}

bool USteamIntegrationSubsystem::SetRichPresence(const FString& Key, const FString& Value)
{
#if UNITY2UE_WITH_STEAM
	return SteamReady() && SteamFriends() && SteamFriends()->SetRichPresence(TCHAR_TO_UTF8(*Key), TCHAR_TO_UTF8(*Value));
#else
	return false;
#endif
}

void USteamIntegrationSubsystem::ClearRichPresence()
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady() && SteamFriends())
	{
		SteamFriends()->ClearRichPresence();
	}
#endif
}

// ---------------------------------------------------------------------- Overlay y DLC

bool USteamIntegrationSubsystem::OpenOverlayWebPage(const FString& Url)
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady() && SteamFriends() && SteamUtils()->IsOverlayEnabled())
	{
		SteamFriends()->ActivateGameOverlayToWebPage(TCHAR_TO_UTF8(*Url), k_EActivateGameOverlayToWebPageMode_Default);
		return true;
	}
#endif
	return false;
}

bool USteamIntegrationSubsystem::OpenStorePage(int64 AppId)
{
#if UNITY2UE_WITH_STEAM
	if (SteamReady() && SteamFriends() && SteamUtils()->IsOverlayEnabled())
	{
		const AppId_t Target = AppId > 0 ? static_cast<AppId_t>(AppId) : SteamUtils()->GetAppID();
		SteamFriends()->ActivateGameOverlayToStore(Target, k_EOverlayToStoreFlag_None);
		return true;
	}
#endif
	return false;
}

bool USteamIntegrationSubsystem::IsDlcInstalled(int64 DlcAppId) const
{
#if UNITY2UE_WITH_STEAM
	return SteamReady() && SteamApps() && SteamApps()->BIsDlcInstalled(static_cast<AppId_t>(DlcAppId));
#else
	return false;
#endif
}

// ---------------------------------------------------------------------- Tick

bool USteamIntegrationSubsystem::Tick(float DeltaTime)
{
#if UNITY2UE_WITH_STEAM
	if (!SteamReady())
	{
		return true;
	}
	TickLeaderboards();
	if (bStatsDirty && FPlatformTime::Seconds() - LastStoreTime > StoreStatsInterval)
	{
		StoreStats();
	}
#endif
	return true;
}
