// GameMode de los proyectos convertidos desde Unity (generado por unity2ue).
// Unity no crea ningún "pawn" por defecto: sin esto UE pone un DefaultPawn (una esfera que vuela)
// en el origen de cada nivel. La vista del jugador la da la cámara convertida de la escena.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "UnityGameMode.generated.h"

UCLASS()
class {{API}} AUnityGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AUnityGameMode();
};
