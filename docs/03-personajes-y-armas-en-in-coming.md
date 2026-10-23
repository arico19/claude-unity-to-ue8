# Personajes y armas en in-coming: guía paso a paso

28 de septiembre de 2026

Esta guía explica cómo poner tus propios modelos con rig en el juego in-coming convertido a Unreal. Sirve para cuatro cosas:
- el personaje del jugador (su FBX);
- el arma del jugador;
- los enanos que se acercan (enemigos);
- el jefe.

Todo se hace editando dos ficheros de texto y ejecutando un comando; no hace falta tocar Unreal a mano.

**Proyecto:** `G:\unitytoue8_pruebas\InComingUE`. Los comandos se escriben en una terminal abierta en `H:\unitytoue8`.

## Lo que hay ahora en el juego

| Momento | Qué pasa | Daño por disparo |
| --- | --- | --- |
| Al empezar la partida | Soldado US con su TommyGun | ×1 |
| 1ª banderola amarilla | Los soldados US cambian el rifle por el lanzallamas | ×2 |
| 2ª banderola amarilla | Todo el grupo pasa a ser **Ch44** (20 cm más alto que el soldado), con lanzallamas | ×2 |
| 3ª banderola amarilla | Todo el grupo pasa a ser **titán** (40 cm más alto), con lanzallamas | ×3 |
| 4ª y siguientes | Sólo suman soldados, como las verdes | — |

- Las **banderolas amarillas** salen de las cajas de la derecha del puente, que aguantan 40 disparos (el doble que las de la izquierda).
- Las **banderolas verdes** (izquierda) suman soldados del tipo que tengas en ese momento: US, Ch44 o titán.
- Cada soldado dispara **recto** a lo largo del puente, desde la boca de su arma, y alcanza lo que tenga en su línea.

## Los ficheros que vas a tocar

Los dos están en `G:\unitytoue8_pruebas\InComingUE\Unity2UE\`. Se editan con el Bloc de notas; cuida las comas y las comillas (si falta una, el comando avisa del error).

| Fichero | Para qué |
| --- | --- |
| `personajes.json` | Qué modelos se convierten en personajes jugables, enemigos o jefe |
| `armas.json` | Qué arma lleva cada personaje, cómo se agarra y dónde está la boca del cañón |

Contenido actual de `personajes.json`:

```json
{
  "plantilla": "/Game/Unity/animations/BP_US_Soldier_Humanoid",
  "personajes": {
    "Ch44": {
      "fichero": "C:/Users/arico/Downloads/Ch44_nonPBR.fbx",
      "arma": "Lanzallamas",
      "mas_alto_cm": 20
    },
    "Titan": {
      "fichero": "G:/unitytoue8_pruebas/InComingUE/Unity2UE/personajes/Titan.fbx",
      "arma": "Lanzallamas",
      "mas_alto_cm": 40
    }
  }
}
```

Cada personaje admite estos datos:

| Dato | Obligatorio | Qué hace |
| --- | --- | --- |
| `fichero` | Sí | El FBX del modelo con rig (rutas con `/`, no con `\`) |
| `mas_alto_cm` | No | Cuántos cm más alto que el soldado US (negativo = más bajo) |
| `altura` | No | Altura total en metros, en lugar de `mas_alto_cm` |
| `arma` | No | Arma de `armas.json` que lleva en la mano derecha (sin ella, va sin arma) |
| `plantilla` | No | Blueprint del que copia el comportamiento. Por defecto, el del soldado US. Para enemigos y jefe se usa el suyo (ver más abajo) |
| `usar_como` | No | `"jugador"` (personaje inicial), `"enemigo"` (los enanos) o `"jefe"` |

## Antes de empezar (siempre)

1. **Cierra el editor de Unreal.** Los comandos abren Unreal por detrás y no pueden si está abierto.
2. Abre una terminal en `H:\unitytoue8` (en el Explorador, escribe `cmd` en la barra de dirección de esa carpeta y pulsa Intro).
3. El modelo tiene que tener **rig humanoide con nombres de hueso tipo Mixamo**: `Hips`, `Spine`, `LeftArm`, `RightHand`... Da igual que lleven el prefijo `mixamorig:` o no. Así salen los de Mixamo, Meshy o Tripo. Con otros nombres de hueso no se le pueden pasar las animaciones.

## Paso 0: preparar el modelo (sólo si es GLB o da error al importar)

- **FBX de Mixamo:** no hace falta nada, se usa tal cual (como el Ch44).
- **GLB, o FBX con varios huesos raíz** (Unreal exige uno solo; es el caso de los rigs automáticos que traen `neutral_bone`): pásalo por Blender con este comando.

  ```bat
  python -m unity2ue glb2fbx "C:\Users\arico\Downloads\mi_modelo.glb" "G:\unitytoue8_pruebas\InComingUE\Unity2UE\personajes\MiModelo.fbx" --quitar neutral_bone
  ```

  Qué hace:
  - quita la raíz sobrante y lo que cuelga de ella;
  - junta todas las piezas en una sola malla;
  - guarda las texturas en ficheros junto al FBX.

  Muestra cuántos huesos raíz quedan (`ROOTS ['Hips']` es lo correcto) y la altura del modelo. Usa el FBX de salida en `fichero`.

## 1. Cambiar el FBX del jugador

Hay dos casos.

### 1a. Cambiar el modelo que aparece con la 2ª o la 3ª banderola amarilla

Es lo más sencillo: reutilizas el nombre `Ch44` (2ª banderola) o `Titan` (3ª).

1. Si es GLB, haz el paso 0.
2. En `personajes.json`, cambia el `fichero` de `Ch44` o de `Titan` por tu FBX. Si quieres, ajusta también `mas_alto_cm`.
3. Borra la carpeta del modelo anterior (con el editor cerrado): `G:\unitytoue8_pruebas\InComingUE\Content\Personajes\Ch44` (o `Titan`). Si no la borras, sigue usando el modelo que ya importó.
4. Ejecuta este comando.

   ```bat
   python -m unity2ue personajes G:\unitytoue8_pruebas\InComingUE --retratos
   ```

   Qué hace:
   - importa el modelo y rehace sus materiales;
   - crea su Blueprint, mirando hacia delante y con los pies en el suelo;
   - le pasa las animaciones del soldado (parado, correr, disparar, morir);
   - le pone el arma apuntando hacia delante.

   Tarda 1–2 minutos y otro minuto para los retratos.
5. Mira los retratos en `G:\unitytoue8_pruebas\InComingUE\Unity2UE\retratos\`: de lado debe apuntar hacia la izquierda de la foto (hacia los enanos) y de frente mirarte.
6. Abre el proyecto, dale a Play y comprueba en el juego (ver "Comprobar en el juego").

### 1b. Un modelo nuevo como personaje inicial (en lugar del soldado US)

1. Si es GLB, haz el paso 0.
2. Añade una entrada nueva en `personajes.json` con `"usar_como": "jugador"`. Los nombres van sin espacios.

   ```json
       "MiSoldado": {
         "fichero": "C:/Users/arico/Downloads/mi_soldado.fbx",
         "mas_alto_cm": 0,
         "usar_como": "jugador"
       }
   ```

   Pon una coma detrás de la `}` de la entrada anterior.
3. Ejecuta `python -m unity2ue personajes G:\unitytoue8_pruebas\InComingUE --retratos`.
4. La partida empezará con ese personaje. Sin `arma` va con las manos vacías, porque el TommyGun forma parte del modelo del soldado US. Para armarlo, añade `"arma": "Lanzallamas"` (o la que hayas importado).
5. **Para volver al soldado US:** quita la línea `"usar_como": "jugador"` (o la entrada entera) y ejecuta `python -m unity2ue personajes G:\unitytoue8_pruebas\InComingUE --restaurar`. El `--restaurar` devuelve los datos del juego a los de Unity.

## 2. Cambiar el arma del jugador

Todas las armas se agarran con la mano derecha. El agarre se calcula para que, en la animación de disparo, el cañón apunte hacia delante.

1. Deja el arma en un FBX, GLB u OBJ (una sola pieza o varias; se juntan).
2. Impórtala y pónsela a los personajes que llevan esa arma.

   ```bat
   python -m unity2ue arma G:\unitytoue8_pruebas\InComingUE Escopeta --fichero "C:\Users\arico\Downloads\escopeta.fbx"
   ```

   - Se importa en `/Game/Armas/Escopeta` y queda anotada en `armas.json`.
   - Sin más opciones, **la llevan los personajes que no tienen arma propia** (los soldados US).
3. Revisa cómo queda con `python -m unity2ue retratos G:\unitytoue8_pruebas\InComingUE`.
4. Si sale girada, grande o con la boca mal, ajústala y repite el comando sin `--fichero`.

   ```bat
   python -m unity2ue arma G:\unitytoue8_pruebas\InComingUE Escopeta --rotacion 0,-90,0 --escala 0.8 --boca 0,53,11
   ```

   | Opción | Qué ajusta | Pista |
   | --- | --- | --- |
   | `--rotacion p,y,r` | Giro del arma (pitch, yaw, roll en grados) | Si el cañón mira de lado, prueba `0,-90,0` o `0,90,0`. Si mira atrás, `0,180,0` |
   | `--escala s` | Tamaño (1 = el del fichero) | |
   | `--posicion x,y,z` | Desplazamiento en cm respecto a la mano | x = hacia delante, z = arriba |
   | `--boca x,y,z` | Punto del cañón del que salen los disparos, en coordenadas del arma | Si no lo pones, se toma el extremo más largo del arma |

   Referencia: el lanzallamas (el lanzagranadas de la plantilla FPS de UE 5.8) usa `--rotacion 0,-90,0 --boca 0,53,11.3`.
5. **Para que un personaje concreto lleve un arma distinta:** pon `"arma": "Escopeta"` en su entrada de `personajes.json` y ejecuta `python -m unity2ue personajes G:\unitytoue8_pruebas\InComingUE`.
6. **Para que un arma se ponga en partida** (como el lanzallamas con la 1ª banderola amarilla): se prepara oculta con `--alternativa`.

   ```bat
   python -m unity2ue arma G:\unitytoue8_pruebas\InComingUE Lanzallamas --alternativa
   ```

   El nombre `Lanzallamas` es el que busca el juego. Si quieres otra arma en ese papel, cambia el fichero de esa entrada: `... arma ... Lanzallamas --fichero "C:\...\otra_arma.fbx" --alternativa`.
7. Ver las armas configuradas: `python -m unity2ue arma G:\unitytoue8_pruebas\InComingUE --listar`.
8. Volver al TommyGun: `python -m unity2ue arma G:\unitytoue8_pruebas\InComingUE TommyGun`.

## 3. Cambiar los enanos que se acercan

1. Si es GLB, haz el paso 0.
2. Añade en `personajes.json` una entrada con la plantilla del enano y `"usar_como": "enemigo"`. La plantilla es el Blueprint original del enano, así se conserva su comportamiento.

   ```json
       "Enano": {
         "fichero": "C:/Users/arico/Downloads/mi_enano.fbx",
         "plantilla": "/Game/Unity/RoyalCod/Template_RunnerClash/Prefabs/Units/BP_Man_Enemy",
         "usar_como": "enemigo",
         "mas_alto_cm": -60
       }
   ```

   `mas_alto_cm: -60` lo hace 60 cm más bajo que el soldado. Sin `arma`, va sin arma.
3. Ejecuta `python -m unity2ue personajes G:\unitytoue8_pruebas\InComingUE`.
4. Dale a Play: los enanos de cada oleada serán tu modelo. Andan con la animación de correr del soldado y mueren con la suya.
5. **Para volver a los stickmen:** quita la entrada (o sólo su `usar_como`) y ejecuta `python -m unity2ue personajes G:\unitytoue8_pruebas\InComingUE --restaurar`.

Esto lo he probado con el Ch44 como enano: aparecen en cada oleada, avanzan por el puente y caen con los disparos.

## 4. Cambiar el jefe

El jefe sale cada 5 oleadas (`BossEveryNWaves` en `DA_Horde_Data`).

1. Si es GLB, haz el paso 0.
2. Añade una entrada con la plantilla del jefe y `"usar_como": "jefe"`.

   ```json
       "Jefe": {
         "fichero": "C:/Users/arico/Downloads/mi_jefe.fbx",
         "plantilla": "/Game/Unity/RoyalCod/Template_RunnerClash/Prefabs/Units/BP_Boss_Stickman_2",
         "usar_como": "jefe",
         "mas_alto_cm": 150
       }
   ```

   Un jefe suele ser grande: `mas_alto_cm: 150` lo hace 1,5 m más alto que el soldado.
3. Ejecuta `python -m unity2ue personajes G:\unitytoue8_pruebas\InComingUE`.
4. **Para volver al jefe original:** quita la entrada y usa `--restaurar`, como con los enanos.

Lo he probado hasta crear el Blueprint del jefe y asignarlo en `DA_Horde_Data`, pero no he llegado a verlo en partida. En la prueba automática no se alcanzan 5 oleadas; revísalo tú la primera vez.

## Comprobar en el juego

1. Abre `G:\unitytoue8_pruebas\InComingUE\InComing.uproject` (o el acceso directo de Unreal) y el nivel `claude_demo`.
2. Dale a **Play**.
3. Para ver las etapas amarillas sin romper cajas: pulsa la tecla **º** (consola) y escribe `unity2ue.YellowBanner`. Cada vez avanza una etapa: lanzallamas, Ch44, titán.
4. Juega como siempre (mover el grupo y disparar) y fíjate en la orientación, el arma y las animaciones.

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| El comando dice que no puede abrir Unreal o tarda y falla | El editor está abierto | Ciérralo y repite |
| "No se pudo importar ... como SkeletalMesh" | FBX sin rig, o con varios huesos raíz | Paso 0 (`glb2fbx`) |
| Sale el modelo anterior aunque cambié el fichero | La carpeta del personaje ya existe | Borra `Content\Personajes\<Nombre>` con el editor cerrado y repite |
| Sale gris o sin texturas | Texturas incrustadas que no se leen | Paso 0: las saca a ficheros |
| Se queda en pose de T o no anima | Nombres de hueso distintos de Mixamo | Renombra los huesos en Blender o riguéalo con Mixamo |
| Mira hacia atrás o el arma apunta mal | Modelo exportado con un giro raro (no de 90°) | Revisa los retratos. Puedes corregir el arma con `agarre_manual` en su entrada de `armas.json` (mismo formato que `agarre`) |
| Trozos sueltos flotando (le pasa un poco al titán) | Piezas del modelo sin pesos de hueso | Asígnales pesos en Blender |
| El juego sigue con enanos/jefe/jugador cambiados tras quitar la entrada | Falta restaurar | Ejecuta el comando con `--restaurar` |

## Dónde queda cada cosa

| Qué | Dónde |
| --- | --- |
| Personajes importados, sus Blueprints y animaciones | `Content\Personajes\<Nombre>\` (`BP_<Nombre>`, `Anims\`) |
| Armas importadas | `Content\Armas\<Nombre>\` |
| Lanzallamas (lanzagranadas de la plantilla FPS) | `Content\Weapons\GrenadeLauncher\` |
| Retratos de comprobación | `Unity2UE\retratos\` |
| Registro del último comando | `Unity2UE\import_log.json` y `Unity2UE\logs\import.log` |
| Etapas amarillas (qué modelo y qué daño) | C++: `PlayerShooter.cpp` (constructor), rutas `/Game/Personajes/Ch44/BP_Ch44` y `/Game/Personajes/Titan/BP_Titan` |
| Cajas de la derecha | `Content\Python\unity2ue_import\extra\right_cubes.py` y `BP_Cube_Derecha` |

Las herramientas (`characters.py`, `weapons.py`, `portraits.py`, `blender_glb_to_fbx.py`) están en `H:\unitytoue8\unity2ue\ue_editor\unity2ue_import\` y sirven para cualquier proyecto convertido con el conversor.
