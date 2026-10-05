# Publicar el juego en Steam

El kit `unity2ue steam` lleva el proyecto de Unreal generado hasta Steam: configura Steamworks en
el proyecto, genera el código C++ para logros, estadísticas, marcadores y presencia, comprueba las
imágenes de la tienda, empaqueta el juego y lo sube con SteamPipe a una rama beta. Lo que sólo se
puede hacer en el panel de Steamworks queda en una lista de tareas con los valores exactos.

Con Claude Code basta con escribir:

```
/publicar-steam C:/Proyectos/MiJuegoUE C:/Proyectos/MiJuegoUnity
```

## Antes de empezar

- Cuenta de Steamworks (https://partner.steamgames.com) con los datos fiscales y bancarios, y la
  tasa de Steam Direct pagada: así se obtiene el **AppID**. Mientras tanto se puede probar todo con
  el AppID 480 (Spacewar, la app de pruebas de Valve).
- Una cuenta de Steam para compilar (*builder*) con permisos para editar y publicar la app, y
  Steam Guard activado.
- [steamcmd](https://developer.valvesoftware.com/wiki/SteamCMD) (o el SDK de Steamworks, que lo
  trae en `tools/ContentBuilder`), en el `PATH` o indicado en `steam.json` > `steamcmd`.
- Unreal Engine 5.8 instalado (para empaquetar).

## Pasos

```bash
python -m unity2ue steam init      <DestinoUE> --unity <ProyectoUnity>   # 1. crea Steam/steam.json
python -m unity2ue steam integrate <DestinoUE>                           # 2. Steam dentro del proyecto UE
python -m unity2ue steam check     <DestinoUE>                           # 3. validar + Steam/checklist.md
python -m unity2ue steam build     <DestinoUE>                           # 4. empaquetar (Shipping)
python -m unity2ue steam upload    <DestinoUE> --preview                 # 5a. simular la subida
python -m unity2ue steam upload    <DestinoUE>                           # 5b. subir a la rama beta
python -m unity2ue steam publish   <DestinoUE>                           # 2+3+4+5 de una vez
```

1. **`init`** crea `Steam/steam.json`. Con `--unity` lee del proyecto Unity el `steam_appid.txt` y
   las llamadas de Steamworks.NET o Facepunch.Steamworks (`SetAchievement("…")`, `SetStat("…")`,
   `FindOrCreateLeaderboard("…")`, `SetRichPresence("steam_display", "#…")`, `BIsDlcInstalled(…)`)
   y rellena logros, estadísticas, marcadores, tokens de presencia y DLC. Completa a mano los
   nombres y descripciones de los logros, los depots y la cuenta de compilación.
2. **`integrate`** activa los plugins OnlineSubsystemSteam/SteamShared (y SteamSockets si
   `networking` es `true`), escribe el AppID en `Config/DefaultEngine.ini`, el empaquetado en
   Shipping en `DefaultGame.ini`, la dependencia de Steamworks en el `Build.cs` y genera:
   - `Source/<Módulo>/Steam/SteamIntegrationSubsystem.{h,cpp}`: subsistema de Game Instance
     usable desde C++ y Blueprints (logros, estadísticas, marcadores, presencia, overlay, DLC,
     idioma de Steam, Steam Deck). Sin Steam (editor, PIE) no hace nada y no falla.
   - `Source/<Módulo>/Steam/SteamIds.h`: constantes con los identificadores de `steam.json`.
   - `Steam/richpresence/<idioma>.vdf`: ficheros de presencia enriquecida para subir a Steamworks.
   Volver a ejecutar `convert` mantiene la integración.
3. **`check`** valida `steam.json`, que la integración esté aplicada, que no quede código con
   llamadas de Steamworks.NET, las imágenes de la tienda y los iconos de logros, y escribe
   `Steam/checklist.md`.
4. **`build`** ejecuta BuildCookRun para cada plataforma de `steam.json` y deja el juego en
   `Steam/build/<Plataforma>/`. Log en `Steam/output/build_<Plataforma>.log`.
5. **`upload`** genera `Steam/scripts/app_build_<AppID>.vdf` (un depot por plataforma, sin `.pdb`
   ni `steam_appid.txt`) y ejecuta `steamcmd +login <cuenta> +run_app_build …`. La contraseña y el
   código de Steam Guard los pide steamcmd; no se guardan en ningún sitio. La build queda en la rama
   de `set_live_branch` (por defecto `beta`): Valve no permite publicar en `default` desde un script,
   eso se hace en el panel cuando la build esté probada.

## `Steam/steam.json`

| Clave | Para qué |
|---|---|
| `app_id` | AppID de la aplicación (480 = pruebas) |
| `platforms` | `{"Win64": {"depot_id": 1234561, "config": "Shipping"}, "Linux": {...}}` |
| `builder_account`, `steamcmd` | Cuenta de compilación y ruta de steamcmd (opcional) |
| `set_live_branch` | Rama en la que queda la build subida (`beta`) |
| `networking` | `true` para multijugador con SteamSockets |
| `relaunch_in_steam` | Relanzar a través de Steam si se abre el .exe directamente |
| `achievements` | `id`, `name`/`description` (texto o `{"english": …, "spanish": …}`), `hidden`, `icon`, `icon_locked` |
| `stats` | `id`, `type` (`int`/`float`/`avgrate`), `default`, `min`, `max`, `increment_only` |
| `leaderboards` | `id`, `sort` (`descending`/`ascending`), `display` (`numeric`/`time_seconds`/`time_milliseconds`) |
| `rich_presence` | `{"english": {"#Status_InMenu": "In the menu"}, "spanish": {…}}` |
| `dlc` | `[{"app_id": 1234570, "name": "SeasonPass"}]` |
| `cloud` | Steam Auto-Cloud (`enabled`, `save_patterns`) |
| `store` | `short_description` (≤300), `languages`, carpetas de imágenes y `asset_sizes` para sobrescribir tamaños |

## Usar Steam desde el juego

```cpp
#include "Steam/SteamIntegrationSubsystem.h"
#include "Steam/SteamIds.h"

if (auto* Steam = USteamIntegrationSubsystem::Get(this))
{
    Steam->UnlockAchievement(SteamIds::Achievements::ACH_WIN_ONE_GAME);
    Steam->AddToStatInt(SteamIds::Stats::NumGames);
    Steam->UploadLeaderboardScore(SteamIds::Leaderboards::HighScores, Score);
    Steam->SetRichPresenceStatus(SteamIds::RichPresence::Status_InMenu);
}
```

En Blueprints: nodo *Get SteamIntegrationSubsystem* y las funciones de la categoría *Steam*.
Las partidas guardadas con `SaveGameToSlot` se sincronizan con **Steam Auto-Cloud** sin código: la
lista de tareas trae la raíz y la carpeta exactas para cada sistema.

Para probar los logros: lanza el juego empaquetado (o el editor con `-game`) con Steam abierto;
en el editor normal (PIE) Steam no se inicializa y las llamadas devuelven `false`.

## Imágenes de la tienda (`Steam/store/`)

| Fichero | Tamaño |
|---|---|
| `header_capsule.png` | 920x430 |
| `small_capsule.png` | 462x174 |
| `main_capsule.png` | 1232x706 |
| `vertical_capsule.png` | 748x896 |
| `library_capsule.png` | 600x900 |
| `library_header.png` | 920x430 |
| `library_hero.png` | 3840x1240 (sin texto) |
| `library_logo.png` | PNG transparente, 1280 de ancho o 720 de alto |
| `page_background.png` | 1438x810 (opcional) |
| `screenshots/*.png` | al menos 5, 1920x1080 |
| `../achievements/<ID>.png`, `<ID>_locked.png` | 256x256 |

Si Valve cambia los tamaños, sobrescríbelos en `steam.json` > `store` > `asset_sizes`
(`{"header_capsule": [920, 430]}`).

## Limitaciones

- El código C++ generado usa la API de Steamworks que incluye UE 5.8; no se ha podido compilar en
  CI (no hay motor). Si una versión del SDK cambia alguna firma, `cpp-reviewer` lo corrige.
- Los logros, estadísticas y marcadores se crean a mano en el panel (Steamworks no tiene API para
  importarlos); `checklist.md` trae las tablas para copiarlos.
- Lobbies, matchmaking, Workshop y Steam Input no se generan: con `networking: true` el proyecto
  usa SteamSockets y el Online Subsystem estándar de UE (`IOnlineSession`).
