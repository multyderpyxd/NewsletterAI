# NewsletterAI — CarrotBot 🥕

CarrotBot es un bot de newsletter musical personalizado. Cada semana agrega datos de múltiples fuentes (Ticketmaster, Last.fm, Spotify, RSS y scrapers de salas locales), los procesa con un modelo de lenguaje (GPT-4.1) y envía un email HTML con cuatro bloques: conciertos, lanzamientos, descubrimientos y agenda local en Zaragoza.

---

## Índice

1. [Arquitectura general](#arquitectura-general)
2. [Estructura del proyecto](#estructura-del-proyecto)
3. [Pipeline de ejecución](#pipeline-de-ejecución)
4. [Módulos](#módulos)
5. [Fuentes de datos](#fuentes-de-datos)
6. [Persistencia e historiales](#persistencia-e-historiales)
7. [Configuración del perfil musical](#configuración-del-perfil-musical)
8. [Variables de entorno](#variables-de-entorno)
9. [Instalación y ejecución](#instalación-y-ejecución)
10. [Email generado](#email-generado)

---

## Arquitectura general

```
main.py
  │
  ├── config/loader.py          → carga artistas y géneros
  │
  ├── news/aggregator.py        → orquesta todos los fetchers + llama a la IA
  │     ├── ticketmaster_fetcher.py
  │     ├── lastfm_fetcher.py
  │     ├── spotify_fetcher.py
  │     ├── rss_fetcher.py
  │     └── zaragoza_fetcher.py
  │
  ├── email_builder/builder.py  → construye el HTML del email
  └── email_builder/sender.py   → envía por SMTP (Gmail)
```

El flujo es lineal y sin estado en memoria entre ejecuciones: los historiales se persisten en JSON dentro de `spotify/data/`.

---

## Estructura del proyecto

```
NewsletterAI/
└── carrot-bot/
    └── functions/
        ├── main.py                          # punto de entrada
        ├── requirements.txt
        ├── config/
        │   ├── loader.py                    # lee artists.txt y genres.txt
        │   ├── artists.txt                  # lista de artistas favoritos
        │   ├── genres.txt                   # lista de géneros favoritos
        │   ├── ost_exclude.txt              # compositores de OST a ignorar
        │   ├── ost_keep.txt                 # excepciones de ost_exclude
        │   └── ticketmaster_skip.txt        # artistas con falsos positivos en TM
        ├── news/
        │   ├── aggregator.py                # orquestador principal + llamada a IA
        │   ├── ticketmaster_fetcher.py      # conciertos en Europa
        │   ├── lastfm_fetcher.py            # lanzamientos y artistas similares
        │   ├── spotify_fetcher.py           # lanzamientos y artistas relacionados
        │   ├── rss_fetcher.py               # noticias musicales vía feeds RSS
        │   └── zaragoza_fetcher.py          # agenda de salas de Zaragoza (scraping)
        ├── email_builder/
        │   ├── builder.py                   # genera el HTML del email
        │   └── sender.py                    # envío por Gmail SMTP
        └── spotify/
            ├── export_spotify.py            # exporta datos de Spotify a JSON
            ├── parse_spotify.py             # parsea los JSON exportados
            └── data/
                ├── followed_artists.json
                ├── top_artists_short_term.json
                ├── top_artists_medium_term.json
                ├── top_artists_long_term.json
                ├── discoveries_history.json  # historial de descubrimientos enviados
                └── concerts_history.json     # historial de conciertos mostrados
```

---

## Pipeline de ejecución

### Paso 1 — Carga del perfil musical
Se leen `artists.txt` y `genres.txt`. Los artistas de `ost_exclude.txt` se filtran (salvo los que aparezcan en `ost_keep.txt`), lo que permite ignorar compositores de bandas sonoras sin relevancia para conciertos o lanzamientos.

### Paso 2 — Agregación de datos
El `aggregator.py` ejecuta en orden:

1. Carga de artistas seguidos desde los JSON de Spotify (`followed_artists`, `top_artists_*`) y los historiales de descubrimientos y conciertos ya mostrados.
2. **Ticketmaster** — conciertos en Europa para todos los artistas favoritos.
3. **RSS** — artículos de noticias musicales.
4. **Zaragoza** — scraping de salas locales.
5. **Last.fm + Spotify** — lanzamientos recientes y artistas similares/relacionados.

### Paso 3 — Procesamiento con IA
Se construye un prompt estructurado con todos los datos y se envía a GPT-4.1-mini. El modelo devuelve un JSON con cuatro bloques: `concerts`, `releases`, `discoveries` y `local_candidates`.

El sistema aplica reglas adicionales en código (no depende de la IA para):
- Separar conciertos de Ticketmaster en nuevos (`[A-NEW]`) y ya reportados (`[A-PREV]`).
- Reordenar `local_candidates`: artistas seguidos aparecen primero, marcados con `is_known: true`.
- Guardar los nuevos descubrimientos y conciertos en los historiales JSON.

### Paso 4 — Construcción y envío del email
`builder.py` genera un email HTML oscuro y editorial con cuatro secciones coloreadas. `sender.py` lo envía vía Gmail SMTP.

---

## Módulos

### `news/aggregator.py`
Núcleo del sistema. Gestiona:
- **Historial de descubrimientos**: evita recomendar el mismo artista durante 8 semanas (`DISCOVERIES_EXCLUDE_WEEKS`).
- **Historial de conciertos**: etiqueta cada concierto como nuevo o ya reportado; purga automáticamente los que ya han pasado.
- **Lista de exclusión para discoveries**: combina artistas seguidos en Spotify + top artists + recomendaciones recientes. La comparación es literal e insensible a mayúsculas.
- **Priorización de conciertos locales**: divide la agenda de Zaragoza en conocidos vs desconocidos antes de enviarlo a la IA, usando separadores de cartelería (`+`, `&`, `feat.`, `vs`) para detectar colaboraciones.

### `news/ticketmaster_fetcher.py`
Busca conciertos en la Discovery API v2 de Ticketmaster. Estrategia:
- Primero resuelve el `attractionId` exacto por nombre para evitar falsos positivos. Si no hay match exacto, descarta el artista.
- Filtra por Europa y asigna un nivel de proximidad geográfica (0=Zaragoza, 1=España, 2=Portugal/Francia/Andorra, 3=Europa central, 4=resto de Europa; fuera de Europa se ignora).
- Los artistas en `ticketmaster_skip.txt` se omiten (útil para nombres ambiguos como "Mili").

### `news/lastfm_fetcher.py`
Dos funciones principales:
- `fetch_recent_releases`: obtiene top álbumes por artista y verifica la fecha de cada uno con `album.getInfo`. Solo devuelve álbumes publicados en los últimos 12 meses.
- `fetch_similar_artists`: recupera artistas similares con similitud mínima 0.4, excluyendo los ya conocidos.

### `news/spotify_fetcher.py`
Minimiza el número de llamadas a la API:
- Resolución de IDs: 1 llamada por artista.
- Álbumes recientes: 1 llamada por artista, filtrando por ventana de 6 meses.
- Artistas relacionados: batch de hasta 50 IDs en una sola llamada.
- Gestiona rate limits (429) y bloqueos (403) sin interrumpir el pipeline; si falla, Last.fm cubre los descubrimientos.

### `news/zaragoza_fetcher.py`
Scrapea las agendas reales de las siguientes salas sin filtrar por artista — la IA decide qué es relevante:

| Sala | Fuente |
|---|---|
| La Lata de Bombillas | Union25 |
| Rock & Blues Café | Union25 + SweetCaroline |
| La Casa del Loco | Conciertos.club |
| Sala Z | Conciertos.club |
| Zaragoza general | Conciertos.club |
| Zaragoza general | Aragón Musical |

Incluye paginación para Union25 (hasta 4 páginas) y enriquecimiento de género visitando cada página individual de evento.

### `email_builder/builder.py`
Genera HTML inline con estilo oscuro y editorial. Cuatro secciones con acento de color distinto:
- 🎫 **Conciertos** — naranja/ámbar
- 📍 **Candidatos locales Zaragoza** — rojo coral
- 🎵 **Lanzamientos** — verde menta
- 🔭 **Descubrimientos** — violeta/lila

Los conciertos locales de artistas que el usuario sigue se destacan con fondo tenue y etiqueta "✓ Artista que sigues".

---

## Fuentes de datos

| Fuente | Qué aporta | API / Método |
|---|---|---|
| **Ticketmaster** | Conciertos en Europa | Discovery API v2 |
| **Last.fm** | Lanzamientos recientes + artistas similares | REST API pública |
| **Spotify** | Lanzamientos recientes + artistas relacionados + perfil del usuario | Spotipy / OAuth |
| **RSS** | Noticias de música (giras, lanzamientos anunciados) | feedparser |
| **Salas Zaragoza** | Agenda local real | scraping con BeautifulSoup |

---

## Persistencia e historiales

Todos los ficheros de datos viven en `carrot-bot/functions/spotify/data/`.

### `discoveries_history.json`
Formato: `{ "Nombre Artista": "YYYY-MM-DD" }`. Un artista recomendado no vuelve a aparecer durante **8 semanas**. Al guardar, se purgan automáticamente las entradas antiguas.

### `concerts_history.json`
Formato: `{ "url_evento": { "first_shown": "...", "event_date": "...", "artist": "..." } }`. Permite diferenciar conciertos nuevos esta semana de los ya reportados. Los conciertos pasados se purgan en la siguiente ejecución.

### `followed_artists.json` / `top_artists_*.json`
Generados por `spotify/export_spotify.py`. Se usan para construir la lista completa de artistas conocidos y excluirlos de los descubrimientos.

---

## Configuración del perfil musical

### `config/artists.txt`
Un artista por línea. Soporta nombres con caracteres japoneses, tildes y caracteres especiales. Ejemplo:
```
Thornhill
Mili
Alice In Chains
tricot
Paramore
Extremoduro
```

### `config/genres.txt`
Un género por línea. Se usa para que la IA evalúe la relevancia de conciertos locales desconocidos y descubrimientos. Ejemplo:
```
rock
shoegaze
dream pop
progressive metal
math rock
post-rock
```

### `config/ost_exclude.txt` / `config/ost_keep.txt`
Permiten excluir compositores de bandas sonoras (que aparecen en Spotify pero no tienen conciertos ni lanzamientos relevantes) manteniendo excepciones concretas.

### `config/ticketmaster_skip.txt`
Lista de artistas cuyo nombre genera falsos positivos en Ticketmaster (p. ej. "Mili" matchea con "Mili Morena").

---

## Variables de entorno

El proyecto carga un fichero `.env` desde `carrot-bot/functions/.env`.

| Variable | Descripción |
|---|---|
| `OPENAI_API_KEY` | Clave de OpenAI para el procesamiento con IA |
| `OPENAI_MODEL` | Modelo a usar (por defecto: `gpt-4.1`) |
| `LASTFM_API_KEY` | Clave de la API de Last.fm |
| `SPOTIFY_CLIENT_ID` | Client ID de la app de Spotify |
| `SPOTIFY_CLIENT_SECRET` | Client Secret de la app de Spotify |
| `SPOTIFY_REDIRECT_URI` | URI de redirección OAuth de Spotify |
| `TICKETMASTER_API_KEY` | Clave de la Discovery API de Ticketmaster |
| `GMAIL_USER` | Dirección Gmail desde la que se envía |
| `GMAIL_APP_PASSWORD` | Contraseña de aplicación de Gmail (no la contraseña normal) |
| `EMAIL_TO` | Dirección de destino del newsletter |

---

## Instalación y ejecución

### Requisitos
- Python 3.11+
- Una cuenta de Gmail con contraseña de aplicación habilitada
- Claves de API para OpenAI, Last.fm, Spotify y Ticketmaster

### Instalación
```bash
cd carrot-bot/functions
pip install -r requirements.txt
```

### Exportar datos de Spotify (primera vez y periódicamente)
```bash
python spotify/export_spotify.py
```
Genera los JSON de artistas seguidos y top artists que el sistema usa para construir la lista de exclusión.

### Ejecutar el bot
```bash
cd carrot-bot/functions
python main.py
```

El bot ejecuta el pipeline completo y envía el email. La salida por consola muestra el progreso de cada paso:
```
🥕 CarrotBot arrancando...

🎵 Artistas activos: 42
🎸 Géneros activos:  67

📡 Buscando datos...

[1/6] Cargando artistas seguidos y historiales...
[2/6] Ticketmaster — conciertos en Europa...
[3/6] RSS...
[4/6] Agenda de salas de Zaragoza...
[5/6] Last.fm y Spotify — lanzamientos y similares...
[6/6] Procesando con IA...

  ✅ Conciertos:          8
  ✅ Lanzamientos:        5
  ✅ Descubrimientos:     4
  ✅ Candidatos Zaragoza: 6

📧 Construyendo email...
📤 Enviando email...

✅ CarrotBot finalizado correctamente.
```

### Automatización
El bot está diseñado para ejecutarse como una **Cloud Function de Firebase** (ver `carrot-bot/functions/.cache`). También puede ejecutarse manualmente o programarse con cualquier scheduler (cron, GitHub Actions, etc.).

---

## Email generado

El email tiene un diseño oscuro con fondo `#0f0f0f` y un patrón sutil de zanahorias en SVG. Está optimizado para clientes de email que soporten HTML inline (Gmail, Apple Mail, Outlook).

Cada sección muestra:
- **Conciertos**: artista, evento, fecha, ciudad, sala, rango de precio, nivel de proximidad geográfica y enlace a Ticketmaster.
- **Candidatos locales**: sala de Zaragoza, fecha, razón de relevancia por género y distinción visual para artistas seguidos.
- **Lanzamientos**: título, artista, tipo (album/single/EP), fecha de lanzamiento y enlace a Spotify o Last.fm.
- **Descubrimientos**: nombre del artista, artista de referencia al que se parece, razón en español y enlace para escuchar.
