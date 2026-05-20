"""
news/aggregator.py

Orquesta todos los fetchers y llama a la IA para que procese
los datos y devuelva un JSON estructurado con cuatro bloques:

  1. concerts          → conciertos reales (Ticketmaster) priorizando España
  2. releases          → nuevos lanzamientos (Last.fm + Spotify)
  3. discoveries       → artistas nuevos (nunca seguidos ni en favoritos)
  4. local_candidates  → conciertos en Zaragoza por sala (scraping)
"""

import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from news.rss_fetcher           import fetch_rss_articles
from news.lastfm_fetcher        import fetch_recent_releases, fetch_similar_artists
from news.spotify_fetcher       import fetch_new_releases, fetch_related_artists
from news.zaragoza_fetcher      import fetch_zaragoza_venue_agenda
from news.ticketmaster_fetcher  import fetch_ticketmaster_concerts


# ─── Carga de artistas seguidos ───────────────────────────────────────────────

def _load_followed_artists() -> set[str]:
    """
    Carga todos los artistas que el usuario ya sigue o tiene en favoritos
    para excluirlos de los descubrimientos.
    """
    followed = set()
    data_dir = Path(__file__).parent.parent / "spotify" / "data"

    files = [
        data_dir / "followed_artists.json",
        data_dir / "top_artists_short_term.json",
        data_dir / "top_artists_medium_term.json",
        data_dir / "top_artists_long_term.json",
    ]

    for filepath in files:
        if not filepath.exists():
            continue
        try:
            data  = json.loads(filepath.read_text(encoding="utf-8"))
            items = (
                data.get("artists", [])
                if isinstance(data.get("artists"), list)
                else data.get("items", [])
            )
            for artist in items:
                name = artist.get("name", "").strip()
                if name:
                    followed.add(name.lower())
        except Exception as e:
            print(f"  ⚠️  Error cargando {filepath.name}: {e}")

    return followed


# ─── Prompts ──────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
Eres el asistente musical personal de un usuario español que vive en Zaragoza.
Tu función es analizar datos musicales y devolver SOLO un objeto JSON válido.
Sin markdown, sin texto adicional, sin explicaciones. Solo el JSON.
"""

PROXIMITY_CONTEXT = """
Escala de proximidad geográfica para conciertos:
  - NIVEL 0 (prioridad absoluta): Zaragoza
  - NIVEL 1 (máxima prioridad): resto de España
  - NIVEL 2 (muy relevante): Portugal, Francia, Andorra
  - NIVEL 3 (relevante): Alemania, Italia, Países Bajos, Bélgica, Suiza, Austria
  - NIVEL 4 (informativo): resto de Europa (UK, Irlanda, Escandinavia, etc.)
  - IGNORAR: fuera de Europa
"""


# ─── Utilidades ───────────────────────────────────────────────────────────────

def _safe_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"No se pudo parsear JSON:\n{raw[:500]}")


def _normalize(result: dict) -> dict:
    if not isinstance(result, dict):
        result = {}
    for key in ("concerts", "releases", "discoveries", "local_candidates"):
        if not isinstance(result.get(key), list):
            result[key] = []
    return result


def _fmt(items: list[dict], keys: list[str], limit: int = 999) -> str:
    if not items:
        return "  (sin datos)"
    lines = []
    for item in items[:limit]:
        parts = []
        for k in keys:
            v = item.get(k, "")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            parts.append(f"{k}: {v}")
        lines.append("  - " + " | ".join(parts))
    return "\n".join(lines)


# ─── Prompt builder ───────────────────────────────────────────────────────────

def _build_prompt(
    artists:           list[str],
    genres:            list[str],
    followed_artists:  set[str],
    ticketmaster:      list[dict],
    rss_articles:      list[dict],
    zaragoza_agenda:   list[dict],
    lastfm_releases:   list[dict],
    spotify_releases:  list[dict],
    similar_artists:   list[dict],
    related_artists:   list[dict],
) -> str:

    all_known = sorted(followed_artists)

    rss_text = "\n".join(
        f"  [{i+1}] {a.get('source','')} — {a.get('title','')}\n"
        f"      {a.get('summary','')[:200]}\n"
        f"      URL: {a.get('url','')}"
        for i, a in enumerate(rss_articles[:30])
    ) or "  (sin datos)"

    return f"""
Perfil del usuario:
  Artistas favoritos: {", ".join(artists)}
  Géneros favoritos:  {", ".join(genres)}
  Ciudad: Zaragoza, España

Lista COMPLETA de artistas que el usuario ya conoce/sigue (NO incluir en discoveries):
  {", ".join(all_known[:200])}

{PROXIMITY_CONTEXT}

━━━ DATOS DISPONIBLES ━━━

[A] CONCIERTOS REALES EN EUROPA (Ticketmaster — datos 100% fiables):
{_fmt(ticketmaster, ["artist", "event", "dates", "locations", "venue", "proximity", "price", "url"], 60)}

[B] NOTICIAS RSS (pueden mencionar giras o lanzamientos):
{rss_text}

[C] AGENDA DE SALAS DE ZARAGOZA (scraping directo de webs de salas):
{_fmt(zaragoza_agenda, ["artist", "event", "date", "venue", "url", "source"], 30)}

[D] LANZAMIENTOS RECIENTES (Last.fm):
{_fmt(lastfm_releases, ["artist", "album", "url"], 60)}

[E] LANZAMIENTOS RECIENTES (Spotify):
{_fmt(spotify_releases, ["artist", "album", "type", "release_date", "url"], 60)}

[F] ARTISTAS SIMILARES (Last.fm):
{_fmt(similar_artists, ["name", "match", "url", "via"], 20)}

[G] ARTISTAS RELACIONADOS (Spotify):
{_fmt(related_artists, ["name", "popularity", "genres", "url", "via"], 20)}

━━━ INSTRUCCIONES ━━━

Devuelve este JSON exacto y nada más:

{{
  "concerts": [
    {{
      "artist":    "nombre del artista",
      "event":     "nombre del tour o evento",
      "dates":     "fecha y hora si se conocen",
      "locations": "ciudad, país",
      "venue":     "nombre de la sala o recinto",
      "proximity": 1,
      "price":     "rango de precios si se conoce",
      "summary":   "1-2 frases en español sobre el evento",
      "url":       "enlace real de Ticketmaster",
      "source":    "Ticketmaster"
    }}
  ],
  "releases": [
    {{
      "artist":       "nombre del artista",
      "title":        "nombre del álbum/single/EP",
      "type":         "album|single|ep|unknown",
      "release_date": "fecha si se conoce",
      "summary":      "descripción breve en español",
      "url":          "enlace",
      "source":       "Last.fm|Spotify|RSS"
    }}
  ],
  "discoveries": [
    {{
      "name":       "nombre del artista",
      "type":       "artist",
      "reason":     "por qué encaja con los gustos del usuario, en español",
      "similar_to": "artista del usuario al que se parece",
      "url":        "enlace a Spotify o Last.fm"
    }}
  ],
  "local_candidates": [
    {{
      "artist": "nombre del artista o evento",
      "event":  "nombre del concierto",
      "date":   "fecha si se conoce",
      "venue":  "sala en Zaragoza",
      "reason": "por qué puede interesar según géneros del usuario, en español",
      "url":    "enlace real de la sala",
      "source": "fuente"
    }}
  ]
}}

Reglas ESTRICTAS:
- Devuelve SOLO el JSON. Sin texto antes ni después.
- concerts: máximo 8. USA SOLO datos de [A]. Ordena por proximity (0 primero).
  No inventes fechas, venues ni URLs — cópialos exactamente de [A].
- releases: máximo 6. Usa [D] y [E]. Prioriza artistas favoritos. No inventes.
- discoveries: exactamente 4 si hay datos. NUNCA artistas de la lista "ya conoce/sigue".
  Usa solo artistas de [F] o [G] que no estén en esa lista.
- local_candidates: máximo 5. Usa solo eventos reales de [C] que encajen con
  géneros del usuario. NO repetir lo que ya esté en concerts.
- Todo el texto explicativo en español.
- Si no hay datos para un bloque, devuelve [].
"""


# ─── Llamada a la IA ──────────────────────────────────────────────────────────

def call_ai(prompt: str) -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model  = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.2,
        max_tokens=3000,
    )

    raw    = response.choices[0].message.content or ""
    result = _safe_json(raw)
    return _normalize(result)


# ─── Función principal ────────────────────────────────────────────────────────

def aggregate(artists: list[str], genres: list[str]) -> dict:
    print("\n📡 Buscando datos...\n")

    print("[1/6] Cargando artistas seguidos en Spotify...")
    followed = _load_followed_artists()
    for a in artists:
        followed.add(a.lower())
    print(f"  → {len(followed)} artistas conocidos (excluidos de descubrimientos)")

    print("\n[2/6] Ticketmaster — conciertos en Europa...")
    ticketmaster = fetch_ticketmaster_concerts(artists)

    print("\n[3/6] RSS...")
    rss_articles = fetch_rss_articles(artists, genres)

    print("\n[4/6] Agenda de salas de Zaragoza...")
    zaragoza_agenda = fetch_zaragoza_venue_agenda()

    print("\n[5/6] Last.fm y Spotify — lanzamientos y similares...")
    lastfm_releases  = fetch_recent_releases(artists)
    similar          = fetch_similar_artists(artists, artists)
    spotify_releases = fetch_new_releases(artists)
    related          = fetch_related_artists(artists, artists)

    print("\n[6/6] Procesando con IA...")
    prompt = _build_prompt(
        artists          = artists,
        genres           = genres,
        followed_artists = followed,
        ticketmaster     = ticketmaster,
        rss_articles     = rss_articles,
        zaragoza_agenda  = zaragoza_agenda,
        lastfm_releases  = lastfm_releases,
        spotify_releases = spotify_releases,
        similar_artists  = similar,
        related_artists  = related,
    )

    result = call_ai(prompt)

    print(f"\n  ✅ Conciertos:          {len(result.get('concerts', []))}")
    print(f"  ✅ Lanzamientos:        {len(result.get('releases', []))}")
    print(f"  ✅ Descubrimientos:     {len(result.get('discoveries', []))}")
    print(f"  ✅ Candidatos Zaragoza: {len(result.get('local_candidates', []))}")

    return result