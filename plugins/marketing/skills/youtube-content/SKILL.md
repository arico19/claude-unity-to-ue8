---
name: youtube-content
description: Plan and package YouTube videos and Shorts for a video player / video organizer product, in Spanish and English — video ideas, script outline, titles, description, chapters, tags, thumbnail brief, pinned comment, and Shorts cut-downs. Use when preparing a YouTube upload, brainstorming channel content, optimizing an existing video's metadata, or turning a feature release into a video.
argument-hint: "<tema del vídeo, función o URL de un vídeo existente>"
---

# YouTube Content

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../../CONNECTORS.md).
>
> **Contexto de empresa:** antes de empezar, lee [COMPANY.md](../../COMPANY.md) (producto, audiencia, voz de marca, idiomas y canales). Aplícalo sin preguntar lo que ya responde; pregunta sólo lo que falte o esté marcado `TODO`.

Prepara todo lo necesario para publicar un vídeo en el canal de YouTube del producto, en
español y en inglés.

## Trigger

User runs `/youtube-content` or asks for YouTube titles, descriptions, scripts, thumbnails,
Shorts, or channel content ideas.

## Inputs

Ask only for what COMPANY.md does not answer:

1. **Modo** — uno de:
   - `idea`: proponer ideas de vídeo para el canal
   - `package`: paquete completo para un vídeo concreto (lo habitual)
   - `optimize`: mejorar título/descripción/miniatura de un vídeo ya publicado
   - `shorts`: sacar Shorts de un vídeo largo o de una función
2. **Tema** — función, novedad, tutorial, comparativa o caso de uso.
3. **Formato** — tutorial, novedades de versión, comparativa, «cómo organizo mi biblioteca», Short.
4. **Duración prevista** del vídeo.
5. **Idiomas** — por defecto ES + EN (según COMPANY.md). Pregunta si habrá un vídeo por
   idioma, o un único vídeo con título, descripción y subtítulos traducidos (las pistas
   de título/descripción multilingües de YouTube Studio).

## Data

- If ~~video platform or ~~marketing analytics is connected: pull the channel's recent
  videos, CTR, average view duration and top search terms; base titles and topics on what
  already works on the channel.
- If ~~SEO is connected (e.g. vidIQ): research search volume and competition for candidate
  keywords **separately in Spanish and English**.
- Otherwise: ask for a YouTube Studio export or the numbers, or proceed with best practices
  and say so.

## Ideas de contenido para un reproductor/organizador de vídeo

Use these as a starting bank in `idea` mode (adapt to the real features in COMPANY.md):

- Tutoriales: «Cómo organizar 10.000 vídeos en 10 minutos», «Reproduce MKV/HEVC sin instalar códecs».
- Problema → solución: «Por qué tu reproductor no abre este vídeo (y cómo arreglarlo)».
- Comparativas honestas con la competencia de COMPANY.md (sin afirmaciones sin prueba).
- Novedades de versión: una función por vídeo; changelog en la descripción.
- Casos de uso por segmento: creadores (archivo de clips), familias (vídeos del móvil), coleccionistas.
- Shorts: un truco en <45 s, antes/después de una biblioteca desordenada, atajos de teclado.

## Output for `package`

Deliver each block in **ES** and then **EN**, adapted rather than translated:

1. **Títulos** — 3 options per language, ≤ 60 characters, main keyword first, no clickbait
   the video doesn't pay off. Mark your recommendation.
2. **Miniatura (brief)** — one visual idea, ≤ 4 words of overlay text per language,
   focal point, contrast; note whether one thumbnail can serve both languages.
3. **Guion (esquema)** — hook in the first 15 s that restates the title's promise, sections
   with timestamps, where to show the product on screen, CTA (download link / subscribe).
4. **Descripción** — first 2 lines carry the keyword and the value (they show above "more");
   download link from COMPANY.md; chapters; related videos; 3 hashtags max.
5. **Capítulos** — start at `0:00`, ≥ 3 chapters, each ≥ 10 s, keyword-bearing names.
6. **Etiquetas** — 8–15 per language, from specific to broad, including the product name.
7. **Comentario fijado** — a question that invites replies, plus the download link.
8. **Shorts derivados** — 2–3 cut-down ideas with the timestamp to cut and a vertical hook.
9. **Checklist de publicación** — subtitles ES/EN uploaded, end screen, cards, playlist,
   translated title/description tracks, category, made-for-kids setting.

## Output for `optimize`

Compare current metadata to the checklist above, show before → after for title,
description and thumbnail brief in both languages, and explain the expected effect
(CTR, search, retention). Never promise specific numbers.

## Brand check

Before delivering, run the text through the voice and "claims requiring proof" rules in
COMPANY.md (as `/brand-review` would) and flag anything that needs verification.

Ask: "¿Quieres que ajuste algo, genere la miniatura con ~~design o prepare los Shorts?"
