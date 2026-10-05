"""Kit de publicación en Steam para el proyecto UE generado.

Flujo (``python -m unity2ue steam <paso> <DestinoUE>``):

1. ``init``      crea ``Steam/steam.json`` (rellenado con lo detectado en Unity: AppID, logros,
                 estadísticas, marcadores y presencia de Steamworks.NET/Facepunch).
2. ``integrate`` activa OnlineSubsystemSteam, escribe la configuración y genera el subsistema
                 C++ ``USteamIntegrationSubsystem`` (logros, stats, marcadores, presencia, overlay, DLC).
3. ``check``     valida configuración, imágenes de la tienda e iconos de logros y escribe
                 ``Steam/checklist.md`` con lo que hay que hacer en el panel de Steamworks.
4. ``build``     empaqueta en Shipping con BuildCookRun para cada plataforma.
5. ``upload``    genera el script de SteamPipe y sube la build con steamcmd a una rama beta.
"""

STEAM_DIR = "Steam"
CONFIG_NAME = "steam.json"
