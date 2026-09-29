# Plugin de marketing: reproductor y organizador de vídeo

Adaptación del plugin [`marketing`](https://github.com/anthropics/knowledge-work-plugins/tree/main/marketing)
de Anthropic (v1.2.0, Apache-2.0) para un producto que reproduce y organiza vídeos:

- **Contexto de empresa en [`COMPANY.md`](COMPANY.md):** producto, audiencia, voz de marca,
  terminología, pilares de mensaje, competencia y métricas. Todas las skills lo leen
  antes de trabajar. **Rellena los `TODO`** (nombre, web, canal, plataformas, precio…).
- **Bilingüe:** por defecto todo sale en español y en inglés, adaptado a cada idioma.
- **YouTube como canal principal:** skill nueva `/youtube-content` y tipos de contenido
  nuevos en `/draft-content` (paquete de vídeo, Shorts/Reels/TikTok, fichas de tiendas de apps).
- **Conectores reducidos** a lo útil para YouTube: ver [`CONNECTORS.md`](CONNECTORS.md).

## Instalación

Desde Claude Code:

```bash
claude plugin marketplace add arico19/claude-unity-to-ue8
claude plugin install marketing@arico19-plugins
```

Si también tienes activado el plugin `marketing` original de Anthropic, desactívalo para
que los comandos no se dupliquen.

## Comandos

| Comando | Qué hace |
|---|---|
| `/youtube-content` | **Nuevo.** Ideas de vídeo, paquete completo de subida (títulos, miniatura, guion, descripción, capítulos, etiquetas, comentario fijado, Shorts) u optimización de un vídeo publicado |
| `/draft-content` | Blog, redes, newsletter, landing, nota de prensa, caso de éxito y, ahora, Shorts y fichas de tiendas de apps |
| `/campaign-plan` | Brief de campaña con objetivos, canales, calendario y métricas (p. ej. lanzamiento de versión) |
| `/brand-review` | Revisa un texto contra la voz, la terminología y las afirmaciones que requieren prueba de `COMPANY.md` |
| `/competitive-brief` | Comparativa de posicionamiento frente a la competencia listada en `COMPANY.md` |
| `/performance-report` | Informe de resultados (YouTube, web, descargas) con recomendaciones |
| `/seo-audit` | Auditoría SEO de la web; para SEO de YouTube usa `/youtube-content optimize` |
| `/email-sequence` | Secuencias de email: onboarding de nuevos usuarios, paso a pago, reactivación |

## Ejemplo

```
> /youtube-content
Modo: package
Tema: organizar automáticamente una biblioteca de 5.000 vídeos
Formato: tutorial, 8 minutos
```

## Qué se ha cambiado respecto al original

- `COMPANY.md` nuevo y referencia a él en las 8 skills (sustituye al «local settings file»).
- `skills/youtube-content/` nuevo.
- `draft-content`: tipos YouTube, Shorts y tiendas de apps; regla de idiomas.
- `.mcp.json`: sólo Supermetrics (incluye YouTube Analytics). Slack, Canva, Figma, HubSpot,
  Amplitude, Notion, Ahrefs, Similarweb y Klaviyo se han quitado; añádelos de nuevo si los usas.
- `CONNECTORS.md`: categoría `~~video platform` y vidIQ como conector recomendado.

El resto del texto de las skills es el original en inglés (instrucciones para Claude);
la salida se genera en los idiomas que marque `COMPANY.md`.
