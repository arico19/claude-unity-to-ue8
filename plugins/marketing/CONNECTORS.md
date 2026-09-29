# Conectores

## Cómo funcionan las referencias a herramientas

Los ficheros del plugin usan `~~categoría` como marcador de la herramienta que conectes en
esa categoría. Por ejemplo, `~~video platform` significa YouTube, se consulte a través de
vidIQ, de Supermetrics o de cualquier otro servidor MCP con esos datos.

`.mcp.json` sólo preconfigura **Supermetrics**, que incluye YouTube Analytics entre sus
fuentes. No existe un conector MCP oficial de YouTube; para investigación de palabras
clave, tendencias y canales de la competencia, conecta **vidIQ** desde
claude.ai → Ajustes → Conectores.

Sin conectores, todas las skills funcionan igual: te piden los datos (CSV exportado de
YouTube Studio, capturas o cifras pegadas) en lugar de leerlos.

## Conectores de este plugin

| Categoría | Marcador | Preconfigurado | Otras opciones |
|---|---|---|---|
| Plataforma de vídeo | `~~video platform` | — | vidIQ (conector de claude.ai), exportaciones de YouTube Studio |
| Analítica de marketing | `~~marketing analytics` | Supermetrics (YouTube, Google Analytics, redes) | Google Analytics |
| SEO | `~~SEO` | — | vidIQ (SEO de YouTube), Ahrefs, Semrush |
| Analítica de producto | `~~product analytics` | — | Amplitude, Mixpanel, Google Analytics |
| Email marketing | `~~email marketing` | — | Mailchimp, Brevo, Klaviyo |
| Marketing automation | `~~marketing automation` | — | HubSpot |
| Chat | `~~chat` | — | Slack, Discord |
| Diseño | `~~design` | — | Canva, Figma (miniaturas) |
| Base de conocimiento | `~~knowledge base` | — | Notion, Confluence |

Para añadir un servidor, agrégalo a `.mcp.json` con su URL oficial; las skills ya lo
usarán a través de su categoría.
