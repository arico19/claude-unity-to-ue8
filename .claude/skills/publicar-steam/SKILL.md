---
name: publicar-steam
description: Prepara y publica en Steam el juego convertido a Unreal Engine 5.8 (Steamworks: logros, estadísticas, marcadores, presencia, Steam Cloud, DLC, imágenes de la tienda, empaquetado y subida con SteamPipe a una rama beta). Úsalo cuando el usuario quiera publicar/subir su juego a Steam o usar funciones de Steamworks.
argument-hint: <ruta-proyecto-ue> [ruta-proyecto-unity]
---

# Publicar el juego en Steam

Argumentos: `$ARGUMENTS` → proyecto UE (generado por unity2ue) y, opcionalmente, el proyecto Unity
original (para recuperar AppID, logros, estadísticas, marcadores y presencia de Steamworks.NET).

Todo vive en `<UE>/Steam/`: `steam.json` (configuración), `store/` (imágenes de la tienda),
`achievements/` (iconos), `richpresence/` (generado), `checklist.md` (generado), `build/` y
`output/` (no versionar). Los pasos son idempotentes: repítelos cuando cambie algo.

1. **Configurar.** Si no existe `Steam/steam.json`:
   `python3 -m unity2ue steam init "<ue>" [--unity "<unity>"] [--app-id N]`.
   Después revisa el fichero con el usuario y pregúntale lo que falte (no lo inventes):
   - `app_id` y `depot_id` de cada plataforma (Steamworks > SteamPipe > Depots). 480 = Spacewar
     (sólo pruebas). Plataformas posibles: `Win64`, `Linux`, `Mac`.
   - `builder_account` (cuenta de compilación). **Nunca** pidas ni guardes la contraseña: steamcmd
     la pide en su terminal.
   - Nombres y descripciones de logros en cada idioma de `store.languages`, textos de los tokens
     de `rich_presence`, `stats` (tipo, mínimos/máximos), `leaderboards`, `dlc`.
   - `networking: true` sólo si el juego es multijugador (activa SteamSockets).
   Puedes redactar tú borradores de `store.short_description` (≤300 caracteres) y de los textos de
   logros/presencia a partir del juego, pero enséñaselos al usuario para que los apruebe.

2. **Integrar en UE:** `python3 -m unity2ue steam integrate "<ue>"`. Activa OnlineSubsystemSteam,
   escribe `DefaultEngine.ini`/`DefaultGame.ini`, la dependencia de Steamworks en `Build.cs` y genera
   `Source/<Módulo>/Steam/SteamIntegrationSubsystem.{h,cpp}` + `SteamIds.h`. `convert` la reaplica.

3. **Migrar las llamadas de Steamworks.NET.** Busca en `Source/<Módulo>/Unity/` los scripts que
   usaban Steam (los lista `steam init --unity` y avisa `steam check`). Lanza subagentes
   `csharp-to-cpp` indicándoles que usen la sección *Steamworks* de
   `.claude/skills/unity-api-a-unreal/reference.md` (`USteamIntegrationSubsystem` + `SteamIds::`).
   El `SteamManager` de Steamworks.NET se queda como componente vacío. Después, `cpp-reviewer`.

4. **Comprobar:** `python3 -m unity2ue steam check "<ue>"` → errores/avisos y `Steam/checklist.md`.
   - Imágenes: dile al usuario qué ficheros y tamaños faltan (`Steam/store/LEEME.txt`). Puedes
     proponer capturas de `Unity2UE/play/` o `Unity2UE/screenshots/` como base para `store/screenshots/`
     (deben ser 1920x1080 y del juego real). No generes arte de la tienda inventado.
   - Iconos de logros 256x256: `<ID>.png` y `<ID>_locked.png`. Si hay Pillow, puedes crear la
     versión gris a partir de la desbloqueada con un script en el scratchpad.
   Repite hasta 0 errores (los avisos de AppID 480 son normales mientras se prueba).

5. **Empaquetar:** `python3 -m unity2ue steam build "<ue>" [--platforms Win64,Linux]`
   (BuildCookRun en Shipping → `Steam/build/<Plataforma>/`). Si falla, lee
   `Steam/output/build_<Plataforma>.log` y corrige (normalmente C++ traducido: usa `cpp-reviewer`).
   Linux desde Windows necesita la toolchain cruzada de UE.

6. **Subir:** primero una simulación `python3 -m unity2ue steam upload "<ue>" --preview` y luego
   la real (sin `--preview`). Publica en `set_live_branch` (beta); **nunca** en `default`: pasar a
   `default` y pulsar *Release* lo hace el usuario en Steamworks. La subida es interactiva (Steam Guard):
   pide al usuario que la ejecute él en su terminal si tú no puedes interactuar con steamcmd.
   Atajo para repetir los pasos 2, 4, 5 y 6: `python3 -m unity2ue steam publish "<ue>"`.

7. **Panel de Steamworks.** Recorre `Steam/checklist.md` con el usuario: depots y opciones de
   lanzamiento, rama beta, logros/estadísticas/marcadores con los API names exactos, subir
   `richpresence/*.vdf`, Auto-Cloud con las rutas indicadas, redistribuibles, página de la tienda,
   clasificación por edades, revisión de la build, "Próximamente" ≥2 semanas antes del lanzamiento.

Termina con un resumen en español: qué está hecho, qué falta en el panel y qué tiene que hacer el
usuario a mano (contraseña de steamcmd, pagos, revisión de Valve, botón Release).
