# Estado del conversor y carpetas de in-coming

23 de octubre de 2026

Este documento responde a dos preguntas: **¿puede el conversor crear un proyecto de Unreal a partir de
cualquier proyecto de Unity, sin intervención?** y **¿cuál de las carpetas de in-coming es el juego avanzado?**

## 1. ¿Convierte cualquier proyecto Unity de forma automática?

**Sí en buena parte, pero no al cien por cien.** El conversor (`H:\unitytoue8`) es genérico: no lleva
nada propio de ningún juego. Con cualquier proyecto Unity, un solo comando genera el proyecto Unreal 5.8:

```bat
python -m unity2ue full "G:\ruta\MiProyectoUnity" "G:\unitytoue8_pruebas\MiJuegoUE" --name MiJuego
```

| Parte | Automática | Notas |
| --- | --- | --- |
| Escenas, prefabs, jerarquía, transforms | Sí | Niveles y Blueprints |
| Modelos, texturas, materiales, animaciones, sonidos | Sí | Humanoid (Mixamo) redirigido a cada personaje |
| ScriptableObjects, input, físicas, luces, cámaras | Sí | DataAssets, Enhanced Input |
| Estructura de los scripts C# (clases, campos, enums, métodos) | Sí | Siempre |
| **Cuerpos de los métodos C#** | **En parte (73% en in-coming)** | Traductor de reglas; el resto queda como TODO |
| Interfaz uGUI, partículas, shaders propios, terrenos | No | Se recrean a mano o con el agente |

**Traductor de reglas** (`unity2ue/convert/body_rules.py`, añadido hoy): traduce por tabla la API habitual de
Unity (transform, Vector3, Quaternion, Mathf, listas, eventos, Instantiate/Destroy, GetComponent, Invoke,
Debug.Log, PlayerPrefs, cadenas interpoladas, switch, `new[]`, constructores de clases auxiliares...).
Cada método se traduce entero o se deja como TODO con el C# original y el motivo. El código resultante
**compila en Unreal 5.8** (comprobado hoy con in-coming convertido desde cero).

**Lo que no cubren las reglas**, porque hace falta entender la intención: corrutinas, LINQ, lambdas,
Animator, interfaz de usuario, parámetros `out`. Para ese resto hay dos caminos:

1. **El agente de Claude Code:** `/convertir-scripts <ProyectoUE>`. Es lo que se usó con in-coming. No
   necesita clave de API; va con la suscripción de Claude Code.
2. **Un paso por API dentro del propio comando `full`** (pendiente de hacer): llamaría a Claude por API para
   cada método pendiente, compilaría y repetiría si falla. Sería "un programa y a esperar", pero necesita
   una clave de API y cuesta por tokens.

Cifras de hoy sobre in-coming (41 scripts, 302 cuerpos entre métodos y getters de propiedades):

| Versión del traductor | Cobertura |
| --- | --- |
| Primera pasada | 30% |
| Con eventos, PlayerPrefs, cadenas interpoladas, switch, getters | 74% |
| Tras corregir lo que no compilaba (estado final) | 73%, y compila |

## 2. Las tres carpetas de in-coming en Unreal

| Carpeta | Qué es | ¿Se toca? |
| --- | --- | --- |
| `G:\unitytoue8_pruebas\InComingUE` | **El juego avanzado y modificado.** Niveles con oleadas crecientes, lanzallamas con fuego, Ch44 y titán, puente de hormigón, sonidos, cambio de personajes y armas por `personajes.json` / `armas.json`, retratos. Su C++ lo tradujeron los agentes y luego se amplió a mano. Guías: `docs/ejemplos/in-coming/`. | Es el bueno. Las pruebas del conversor nunca se hacen aquí. |
| `G:\unitytoue8_pruebas\InComingUE_copia_2026-10-23` | Copia de seguridad completa del anterior (3,3 GB, con `Intermediate`, así compila al momento). | Sólo para restaurar: cerrar el editor, renombrar `InComingUE` y copiar esta de vuelta. |
| `G:\unitytoue8_pruebas\InComingReglas` | Banco de pruebas: in-coming convertido desde cero **sólo con el conversor automático**, sin ninguna modificación. Sirve para medir cuánto hace el programa por sí solo. | Se puede borrar o regenerar cuando se quiera. Si se regenera tras cambiar el conversor, borrar antes `Source\InComing\Unity`. |

## 3. Cómo seguir

- Para convertir otro juego: el comando `full` de arriba y después `/convertir-scripts` para los métodos
  pendientes (o el paso por API cuando exista).
- Para seguir con in-coming: trabajar en `InComingUE`, como hasta ahora.
- Para subir la cobertura automática: añadir reglas en `body_rules.py` midiendo con el script de cobertura
  (los motivos de rechazo salen en `Unity2UE/report.md` y en la cabecera de cada `.h` generado).
