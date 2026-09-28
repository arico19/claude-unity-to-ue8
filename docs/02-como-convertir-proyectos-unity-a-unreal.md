# Cómo convertir un proyecto Unity a Unreal Engine 5.8 con la aplicación

28 de septiembre de 2026

Se abre **"Unity a Unreal 5.8"** (acceso directo en el escritorio), se elige el proyecto Unity y la
carpeta de destino, y se pulsa **Convertir**: la aplicación hace todos los pasos y al terminar abre el
proyecto en Unreal.

## Antes de empezar

| Requisito | Para qué | En este PC |
| --- | --- | --- |
| Unreal Engine 5.8 | Compilar, importar y probar | `G:\UE_5.8` (se detecta solo) |
| Python 3.10+ con el conversor instalado | Ejecutar la aplicación | Instalado (`pip install -e H:\unitytoue8`) |
| Visual Studio 2022 (C++) | Compilar el módulo del juego | Instalado |
| Claude Code (`claude`, con la sesión iniciada) | Traducir los scripts C# a C++ | Instalado; opcional |
| Blender | Arreglar esqueletos con varios huesos raíz | `C:\Program Files\Blender Foundation\Blender 5.1`; opcional |
| Proyecto Unity con *Asset Serialization = Force Text* | Que el conversor pueda leer escenas y prefabs | Comprobar en *Project Settings → Editor* |

- **Destino en un SSD** (G: o D:). En un disco USB o mecánico una compilación tarda casi una hora en
  vez de unos minutos; la aplicación avisa si eliges uno.
- **Editor de Unreal cerrado** si vas a reconvertir un proyecto que ya tienes abierto.
- **Cierra lo pesado** (Chrome, Epic Games Launcher): compilar e importar usan mucha memoria.

## Pasos

1. Abre **"Unity a Unreal 5.8"** desde el escritorio (también está en `H:\unitytoue8` y en esta
   carpeta `docs`).
2. **Proyecto Unity → Examinar…**: la carpeta que contiene `Assets` y `ProjectSettings`. El proyecto
   Unity sólo se lee; no se modifica.
3. **Guardar el proyecto UE en → Examinar…**: una carpeta vacía en un SSD, por ejemplo
   `G:\ProyectosUE\MiJuego`. Si no eliges ninguna, propone `<proyecto>_UE` junto al original.
4. **Nombre del proyecto UE**: se rellena solo a partir de la carpeta (sólo letras, números y `_`,
   empezando por letra).
5. **Unreal Engine 5.8**: se detecta solo; cámbialo sólo si tienes otra instalación.
6. Marca los **pasos** que quieras (por defecto, todos):

   | Paso | Qué hace | Tiempo orientativo |
   | --- | --- | --- |
   | Convertir el proyecto Unity | Genera el proyecto UE, los datos intermedios y los esqueletos C++ | 1 min |
   | Traducir scripts C# → C++ (Claude Code) | Agentes de IA escriben el código de cada script; consume tokens | 10–60 min según el nº de scripts |
   | Compilar el C++ | Compila el módulo del juego | 4–5 min la primera vez en SSD; segundos después |
   | Importar en Unreal | Modelos, texturas, sonidos, animaciones, materiales, Blueprints, niveles | 1–3 min |
   | Verificar niveles | Cuenta actores, luces, cámaras y mallas o materiales vacíos | 30 s |
   | Capturas de los niveles | Abre el editor y fotografía cada nivel | 1 min |
   | Prueba de juego | Pulsa Play en el nivel principal y hace capturas | 1 min |

7. Pulsa **▶ Convertir** y sigue el progreso en el registro de la ventana. **Cancelar** detiene el paso
   en curso.
8. Al terminar:
   - **Abrir en Unreal** abre el proyecto (también se abre solo si marcaste la casilla).
   - **Abrir carpeta** abre el destino.
   - **Ver resultado** abre `Unity2UE\resultado_ue.md`: compilación, importación, assets creados y una
     tabla por nivel.
   - Si se tradujeron scripts, la barra de estado muestra el **coste en tokens y en dólares** de Claude
     Code; también queda en `Unity2UE\coste_claude.json`.

## Qué encontrarás en el proyecto de Unreal

| Ruta | Contenido |
| --- | --- |
| `<Nombre>.uproject` | El proyecto; ábrelo con UE 5.8 |
| `Content\Unity\Maps\` | Un nivel por escena de Unity |
| `Content\Unity\...` | Assets con la misma estructura de carpetas que en Unity (Blueprints `BP_`, materiales `MI_`, datos `DA_`) |
| `Source\<Nombre>\Unity\` | Un `.h/.cpp` por script C# (`STUB` sin traducir, `TRANSLATED` ya traducido) |
| `Unity2UE\report.md` | Informe de la conversión y tareas manuales pendientes |
| `Unity2UE\resultado_ue.md` | Resultado de compilar, importar y verificar |
| `Unity2UE\logs\` | Registro de cada paso (build, import, verify, play) |
| `Unity2UE\screenshots\`, `Unity2UE\play\` | Capturas de los niveles y de la prueba de juego |

## Qué se convierte solo y qué no

**Automático:** escenas, prefabs y variantes (con sus overrides y componentes añadidos), transforms,
mallas, luces, cámaras, colisiones, física, audio, materiales Standard y URP, texturas, modelos FBX,
sprites, textos 3D (TextMeshPro), ScriptableObjects como DataAssets, input, animaciones `.anim` y
animaciones Humanoid (Mixamo) redirigidas a cada personaje.

**Manual o asistido** (aparece en `report.md`):

- La interfaz uGUI (canvas, botones, textos de pantalla): recrearla en UMG.
- Sistemas de partículas: recrearlos en Niagara.
- Shaders personalizados y ShaderGraph: se usa un material aproximado.
- Terrenos: recrearlos como Landscape.
- Lógica que Unity hace sola y el C++ traducido no: revisar con una prueba de juego (por ejemplo, el
  estado inicial de un Animator).

## Repetir sólo una parte

Reconvertir es seguro: el C++ ya traducido (`TRANSLATED`) no se sobrescribe y los ficheros idénticos
no se reescriben, así que no se recompila todo. Desmarca en la aplicación los pasos que no necesites, o
desde una terminal en `H:\unitytoue8`:

```bat
REM Sólo los pasos de Unreal sobre un proyecto ya convertido
python -m unity2ue ue "G:\ProyectosUE\MiJuego" --steps build,import,verify

REM Prueba de juego en un nivel concreto, moviendo y disparando
set UNITY2UE_PLAY_LEVEL=/Game/Unity/Maps/claude_demo
set UNITY2UE_PLAY_CMDS=1.5:unity2ue.AutoMove -1;3:unity2ue.AutoFire 1
python -m unity2ue ue "G:\ProyectosUE\MiJuego" --steps play
```

`unity2ue.AutoMove` y `unity2ue.AutoFire` sólo existen si el juego traducido los define (in-coming los
tiene en su gestor de entrada).

## Retoques propios de cada proyecto

Lo que quieras cambiar respecto a Unity (materiales mejores, ajustes de un nivel…) va en scripts Python
dentro de `Content\Python\unity2ue_import\extra\` del proyecto UE, con una función `run()`. Se
ejecutan al final de cada importación y **no se borran al reconvertir**. Ejemplo real:
`extra\custom_materials.py` de in-coming (puente de madera, cajas, metal y banderolas
semitransparentes). Para aplicar sólo esos retoques: `set UNITY2UE_STEPS=extra` antes de
`python -m unity2ue ue <proyecto> --steps import`.

## Si algo falla

| Síntoma | Qué hacer |
| --- | --- |
| La compilación tarda mucho o parece colgada | El destino está en un disco USB o mecánico: muévelo a un SSD |
| "La compilación falló" | Mira `Unity2UE\logs\build.log`; los errores suelen estar en scripts traducidos. Pídele a Claude Code que los corrija (`/convertir-scripts` o el agente `cpp-reviewer`) |
| Unreal se cuelga al abrir (DXGI) | Este PC usa DX11 para todos los proyectos; no quites `UserEngine.ini` |
| "No se puede extraer desde el control de versiones" | Aviso inofensivo al guardar niveles; se guardan igual |
| Todo sale gris | El material maestro no compiló: reimporta (se reconstruye solo si cambia su versión) |
| Personajes sin animación o en pose de T | Revisa en `import_log.json` los pasos `anim_clips` y `humanoid` |
| Un paso concreto falla | Repite sólo ese paso con `--steps` y mira su log en `Unity2UE\logs\` |
| Importar con el editor abierto da errores | Cierra el editor de Unreal y repite |
