// Generado por unity2ue (steam integrate). Se regenera: no lo edites, amplíalo en otra clase.
//
// Acceso a Steamworks desde C++ y Blueprints: logros, estadísticas, marcadores, presencia
// enriquecida, overlay, DLC, idioma y Steam Deck. Usa la API de Steamworks que inicializa el
// plugin OnlineSubsystemSteam; fuera de Steam (editor, PIE, consolas) todas las llamadas
// devuelven false/vacío sin fallar, así que el juego funciona igual sin Steam.
//
// Uso en C++:  USteamIntegrationSubsystem::Get(this)->UnlockAchievement(SteamIds::Achievements::ACH_WIN);
// Uso en BP:   nodo "Get SteamIntegrationSubsystem" (Game Instance Subsystem).
#pragma once

#include "CoreMinimal.h"
#include "Containers/Ticker.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "SteamIntegrationSubsystem.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_ThreeParams(FOnSteamLeaderboardScoreUploaded, const FString&, LeaderboardName,
                                               int32, Score, bool, bSuccess);

UCLASS()
class {{API}} USteamIntegrationSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** Atajo desde cualquier objeto con mundo (actor, componente, widget). Puede devolver nullptr. */
	static USteamIntegrationSubsystem* Get(const UObject* WorldContextObject);

	// ------------------------------------------------------------------ General
	/** true si el cliente de Steam está abierto y la API se inicializó (juego lanzado desde Steam). */
	UFUNCTION(BlueprintPure, Category = "Steam")
	bool IsSteamAvailable() const;

	UFUNCTION(BlueprintPure, Category = "Steam")
	int64 GetAppId() const;

	UFUNCTION(BlueprintPure, Category = "Steam")
	FString GetPlayerName() const;

	/** Idioma elegido en Steam para el juego ("spanish", "english"...). Vacío sin Steam. */
	UFUNCTION(BlueprintPure, Category = "Steam")
	FString GetSteamLanguage() const;

	UFUNCTION(BlueprintPure, Category = "Steam")
	bool IsRunningOnSteamDeck() const;

	// ------------------------------------------------------------------ Logros
	/** Desbloquea el logro y lo envía a Steam en el acto (aparece la notificación). */
	UFUNCTION(BlueprintCallable, Category = "Steam|Logros")
	bool UnlockAchievement(const FString& AchievementId);

	UFUNCTION(BlueprintCallable, Category = "Steam|Logros")
	bool IsAchievementUnlocked(const FString& AchievementId) const;

	/** Muestra la notificación de progreso ("3/10") sin desbloquear. */
	UFUNCTION(BlueprintCallable, Category = "Steam|Logros")
	bool ShowAchievementProgress(const FString& AchievementId, int32 Current, int32 Max);

	/** Sólo para pruebas: borra estadísticas (y logros si se indica) del usuario actual. */
	UFUNCTION(BlueprintCallable, Category = "Steam|Logros", meta = (DevelopmentOnly))
	bool ResetAllStats(bool bAlsoAchievements);

	// ------------------------------------------------------------------ Estadísticas
	// Se envían a Steam agrupadas cada pocos segundos (Steam limita la frecuencia de StoreStats).
	UFUNCTION(BlueprintCallable, Category = "Steam|Estadisticas")
	bool SetStatInt(const FString& StatId, int32 Value);

	UFUNCTION(BlueprintCallable, Category = "Steam|Estadisticas")
	bool SetStatFloat(const FString& StatId, float Value);

	UFUNCTION(BlueprintCallable, Category = "Steam|Estadisticas")
	bool AddToStatInt(const FString& StatId, int32 Amount = 1);

	UFUNCTION(BlueprintCallable, Category = "Steam|Estadisticas")
	int32 GetStatInt(const FString& StatId) const;

	UFUNCTION(BlueprintCallable, Category = "Steam|Estadisticas")
	float GetStatFloat(const FString& StatId) const;

	/** Fuerza el envío inmediato de estadísticas y logros pendientes. */
	UFUNCTION(BlueprintCallable, Category = "Steam|Estadisticas")
	bool StoreStats();

	// ------------------------------------------------------------------ Marcadores
	/** Sube una puntuación (el marcador debe existir en Steamworks). Resultado en OnLeaderboardScoreUploaded. */
	UFUNCTION(BlueprintCallable, Category = "Steam|Marcadores")
	void UploadLeaderboardScore(const FString& LeaderboardName, int32 Score, bool bKeepBest = true);

	UPROPERTY(BlueprintAssignable, Category = "Steam|Marcadores")
	FOnSteamLeaderboardScoreUploaded OnLeaderboardScoreUploaded;

	// ------------------------------------------------------------------ Presencia enriquecida
	/** Texto que ven los amigos: Token es una clave "#..." de Steam/richpresence/*.vdf. */
	UFUNCTION(BlueprintCallable, Category = "Steam|Presencia")
	bool SetRichPresenceStatus(const FString& Token);

	UFUNCTION(BlueprintCallable, Category = "Steam|Presencia")
	bool SetRichPresence(const FString& Key, const FString& Value);

	UFUNCTION(BlueprintCallable, Category = "Steam|Presencia")
	void ClearRichPresence();

	// ------------------------------------------------------------------ Overlay y DLC
	UFUNCTION(BlueprintCallable, Category = "Steam|Overlay")
	bool OpenOverlayWebPage(const FString& Url);

	/** Abre la página de la tienda en el overlay (AppId 0 = este juego; útil para DLC). */
	UFUNCTION(BlueprintCallable, Category = "Steam|Overlay")
	bool OpenStorePage(int64 AppId = 0);

	UFUNCTION(BlueprintPure, Category = "Steam|DLC")
	bool IsDlcInstalled(int64 DlcAppId) const;

private:
	bool Tick(float DeltaTime);
	void TickLeaderboards();

	struct FPendingScore
	{
		FString Leaderboard;
		int32 Score = 0;
		bool bKeepBest = true;
	};

	FTSTicker::FDelegateHandle TickHandle;
	bool bStatsDirty = false;
	double LastStoreTime = 0.0;

	TArray<FPendingScore> PendingScores;
	TMap<FString, uint64> LeaderboardHandles;
	uint64 CurrentCall = 0;
	bool bCurrentCallIsFind = false;
};
