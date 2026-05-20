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
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from news.rss_fetcher           import fetch_rss_articles
from news.lastfm_fetcher        import fetch_recent_releases, fetch_similar_artists
from news.spotify_fetcher       import fetch_new_releases, fetch_related_artists
from news.zaragoza_fetcher      import fetch_zaragoza_venue_agenda, enrich_with_genres
from news.ticketmaster_fetcher  import fetch_ticketmaster_concerts


# ─── Historial de descubrimientos ────────────────────────────────────────────

DISCOVERIES_HISTORY_PATH = Path(__file__).parent.parent / "spotify" / "data" / "discoveries_history.json"
DISCOVERIES_EXCLUDE_WEEKS = 8   # no repetir un descubrimiento durante N semanas


def _load_discoveries_history() -> dict[str, str]:
    """Carga {nombre_artista: fecha_recomendado} del historial."""
    if not DISCOVERIES_HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(DISCOVERIES_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_discoveries_history(history: dict[str, str]) -> None:
    """Guarda el historial actualizado, purgando entradas antiguas."""
    cutoff = datetime.now() - timedelta(weeks=DISCOVERIES_EXCLUDE_WEEKS)
    pruned = {
        name: date_str
        for name, date_str in history.items()
        if datetime.fromisoformat(date_str) >= cutoff
    }
    DISCOVERIES_HISTORY_PATH.write_text(
        json.dumps(pruned, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _recently_recommended(history: dict[str, str]) -> set[str]:
    """Devuelve nombres en minúsculas recomendados dentro de la ventana de exclusión."""
    cutoff = datetime.now() - timedelta(weeks=DISCOVERIES_EXCLUDE_WEEKS)
    return {
        name.lower()
        for name, date_str in history.items()
        if datetime.fromisoformat(date_str) >= cutoff
    }


def _record_discoveries(result: dict, history: dict[str, str]) -> None:
    """Añade los descubrimientos de esta ejecución al historial."""
    today = datetime.now().date().isoformat()
    for d in result.get("discoveries", []):
        name = d.get("name", "").strip()
        if name:
            history[name] = today


# ─── Historial de conciertos mostrados ───────────────────────────────────────

CONCERTS_HISTORY_PATH = Path(__file__).parent.parent / "spotify" / "data" / "concerts_history.json"


def _load_concerts_history() -> dict[str, dict]:
    """
    Carga {url: {first_shown, event_date, artist}} del historial.
    Purga automáticamente conciertos cuya fecha ya pasó.
    """
    if not CONCERTS_HISTORY_PATH.exists():
        return {}
    try:
        raw    = json.loads(CONCERTS_HISTORY_PATH.read_text(encoding="utf-8"))
        today  = datetime.now().date().isoformat()
        return {
            url: meta for url, meta in raw.items()
            if meta.get("event_date", "9999") >= today  # purga pasados
        }
    except Exception:
        return {}


def _save_concerts_history(history: dict[str, dict]) -> None:
    CONCERTS_HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _annotate_concerts(
    concerts: list[dict],
    history:  dict[str, dict],
) -> list[dict]:
    """
    Añade is_new=True/False a cada concierto según si ya aparece en el historial.
    """
    annotated = []
    for c in concerts:
        url    = c.get("url", "")
        is_new = url not in history
        annotated.append({**c, "is_new": is_new})
    return annotated


def _record_concerts(result: dict, history: dict[str, dict]) -> None:
    """Registra los conciertos mostrados en esta ejecución."""
    today = datetime.now().date().isoformat()
    for c in result.get("concerts", []):
        url = c.get("url", "")
        if url and url not in history:
            history[url] = {
                "first_shown": today,
                "event_date":  (c.get("dates", "") or "")[:10],  # YYYY-MM-DD
                "artist":      c.get("artist", ""),
            }


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


def _artist_is_known(artist_field: str, known_set: set[str]) -> bool:
    """
    Comprueba si alguno de los artistas en un campo de artista pertenece
    al conjunto de conocidos. Divide por separadores habituales de cartelería
    ('+', '&', 'feat.', 'vs') para manejar casos como
    'Pink Breath of Heaven + Nuevos Mundos'.
    """
    name = artist_field.lower().strip()
    if name in known_set:
        return True
    parts = re.split(r"\s*[+&]\s*|\s+feat\.?\s+|\s+vs\.?\s+", name)
    return any(p.strip() in known_set for p in parts if p.strip())


def _sort_local_candidates(candidates: list[dict], followed: set[str]) -> list[dict]:
    """
    Reordena local_candidates en código (no dependemos de la IA para esto):
      1. Artistas que el usuario sigue/conoce → primero, marcados con is_known=True
      2. Artistas desconocidos → después
    Dentro de cada grupo mantiene el orden de fecha que dio la IA.
    """
    known   = [{**c, "is_known": True}  for c in candidates if     _artist_is_known(c.get("artist",""), followed)]
    unknown = [{**c, "is_known": False} for c in candidates if not _artist_is_known(c.get("artist",""), followed)]
    return known + unknown


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
    artists:              list[str],
    genres:               list[str],
    followed_artists:     set[str],
    recently_recommended: set[str],
    ticketmaster:         list[dict],
    rss_articles:         list[dict],
    zaragoza_agenda:      list[dict],
    lastfm_releases:      list[dict],
    spotify_releases:     list[dict],
    similar_artists:      list[dict],
    related_artists:      list[dict],
    concerts_history:     dict[str, dict] | None = None,
) -> str:

    today_str  = datetime.now().strftime("%Y-%m-%d")
    cutoff_str = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    all_known  = sorted(followed_artists | recently_recommended)

    rss_text = "\n".join(
        f"  [{i+1}] {a.get('source','')} — {a.get('title','')}\n"
        f"      {a.get('summary','')[:200]}\n"
        f"      URL: {a.get('url','')}"
        for i, a in enumerate(rss_articles[:30])
    ) or "  (sin datos)"

    # Separar conciertos Ticketmaster en nuevos (no vistos) y ya reportados
    history  = concerts_history or {}
    tm_new   = [c for c in ticketmaster if c.get("url", "") not in history]
    tm_prev  = [c for c in ticketmaster if c.get("url", "") in history]

    # Separar agenda Zaragoza en conocidos vs desconocidos antes de enviarlo a la IA
    excluded = followed_artists | recently_recommended
    zaragoza_known   = [
        e for e in zaragoza_agenda
        if     _artist_is_known(e.get("artist", ""), excluded)
    ]
    zaragoza_unknown = enrich_with_genres([
        e for e in zaragoza_agenda
        if not _artist_is_known(e.get("artist", ""), excluded)
    ])

    return f"""
Fecha de hoy: {today_str}

Perfil del usuario:
  Artistas favoritos: {", ".join(artists)}
  Géneros favoritos:  {", ".join(genres)}
  Ciudad: Zaragoza, España

Lista COMPLETA de artistas excluidos de discoveries (conocidos/seguidos + recomendados en las últimas {DISCOVERIES_EXCLUDE_WEEKS} semanas):
  {", ".join(all_known[:200])}

{PROXIMITY_CONTEXT}

━━━ DATOS DISPONIBLES ━━━

[A-NEW] CONCIERTOS NUEVOS esta semana (Ticketmaster — no reportados antes):
{_fmt(tm_new, ["artist", "event", "dates", "locations", "venue", "proximity", "price", "url"], 60) or "  (ninguno nuevo esta semana)"}

[A-PREV] CONCIERTOS YA REPORTADOS en semanas anteriores (Ticketmaster — aún vigentes):
{_fmt(tm_prev, ["artist", "event", "dates", "locations", "venue", "proximity", "price", "url"], 60) or "  (ninguno)"}

[B] NOTICIAS RSS (pueden mencionar giras, tours o lanzamientos próximos):
{rss_text}

[C1] AGENDA ZARAGOZA — ARTISTAS QUE EL USUARIO YA SIGUE (incluir TODOS en local_candidates):
{_fmt(zaragoza_known, ["artist", "event", "date", "venue", "url", "source"], 20) if zaragoza_known else "  (ninguno esta semana)"}

[C2] AGENDA ZARAGOZA — ARTISTAS DESCONOCIDOS (seleccionar los más relevantes por género):
{_fmt(zaragoza_unknown, ["artist", "event", "date", "venue", "genre", "url", "source"], 30)}

[D] LANZAMIENTOS RECIENTES (Last.fm — ya filtrados a últimos 12 meses):
{_fmt(lastfm_releases, ["artist", "album", "release_date", "url"], 60)}

[E] LANZAMIENTOS RECIENTES (Spotify — ya filtrados a últimos 6 meses o futuros):
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
      "url":       "enlace real",
      "source":    "Ticketmaster|sala"
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

- concerts: máximo 10. USA SOLO datos de [A-NEW] y [A-PREV]. Copia exactamente
  artist, event, dates, locations, venue, proximity, price y url — no inventes nada.
  PRIORIDAD OBLIGATORIA:
    1. Incluye PRIMERO todos los de [A-NEW] (conciertos nuevos esta semana), ordenados
       por proximity (0 primero). Son prioridad absoluta aunque sean de nivel 4.
    2. Completa hasta 10 con los de [A-PREV] más relevantes (los más próximos
       geográficamente y con fecha más cercana), para mantener la agenda completa.
  Para cada artista favorito con datos en [A-NEW] o [A-PREV], intenta incluir
  al menos su concierto más próximo aunque sea nivel 3 o 4.

- releases: máximo 6. USA SOLO datos de [D], [E] o [B] con release_date posterior a
  {cutoff_str} o futura (upcoming). Si un lanzamiento no tiene fecha confirmada o
  su fecha es anterior a {cutoff_str}, NO lo incluyas. Prioriza artistas favoritos.
  También incluye lanzamientos próximos anunciados en [B] aunque aún no hayan salido.
  No inventes fechas ni URLs.

- discoveries: exactamente 4 si hay datos. Compara el nombre de cada candidato de [F]
  y [G] con la lista de excluidos de forma LITERAL e ignorando mayúsculas. Si el nombre
  coincide exactamente con cualquier entrada de la lista, DESCÁRTALO. No uses criterio
  de "es muy conocido" — usa solo la lista proporcionada.

- local_candidates: máximo 6.
    1. Incluye TODOS los eventos de [C1] sin excepción (son artistas que el usuario
       sigue — tienen prioridad absoluta independientemente del género).
    2. Completa hasta 6 con eventos de [C2] que encajen con los géneros del usuario.
  El orden final lo gestiona el sistema externamente, no es necesario que los ordenes.

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
        max_tokens=5000,
    )

    choice        = response.choices[0]
    finish_reason = choice.finish_reason
    raw           = choice.message.content or ""

    if finish_reason == "length":
        used = response.usage.completion_tokens if response.usage else "?"
        print(f"  ⚠️  Respuesta cortada por max_tokens (completion_tokens={used}). "
              f"Aumenta max_tokens en call_ai().")

    result = _safe_json(raw)
    return _normalize(result)


# ─── Función principal ────────────────────────────────────────────────────────

def aggregate(artists: list[str], genres: list[str]) -> dict:
    print("\n📡 Buscando datos...\n")

    print("[1/6] Cargando artistas seguidos y historiales...")
    followed = _load_followed_artists()
    for a in artists:
        followed.add(a.lower())
    disc_history       = _load_discoveries_history()
    recent_recommended = _recently_recommended(disc_history)
    conc_history       = _load_concerts_history()
    print(f"  → {len(followed)} artistas conocidos, "
          f"{len(recent_recommended)} descubrimientos recientes excluidos, "
          f"{len(conc_history)} conciertos en historial")

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
        artists              = artists,
        genres               = genres,
        followed_artists     = followed,
        recently_recommended = recent_recommended,
        ticketmaster         = ticketmaster,
        rss_articles         = rss_articles,
        zaragoza_agenda      = zaragoza_agenda,
        lastfm_releases      = lastfm_releases,
        spotify_releases     = spotify_releases,
        similar_artists      = similar,
        related_artists      = related,
        concerts_history     = conc_history,
    )

    result = call_ai(prompt)

    # Reordenar local_candidates en código: conocidos primero, desconocidos después
    result["local_candidates"] = _sort_local_candidates(
        result.get("local_candidates", []), followed
    )

    # Guardar historiales
    _record_discoveries(result, disc_history)
    _save_discoveries_history(disc_history)
    _record_concerts(result, conc_history)
    _save_concerts_history(conc_history)

    print(f"\n  ✅ Conciertos:          {len(result.get('concerts', []))}")
    print(f"  ✅ Lanzamientos:        {len(result.get('releases', []))}")
    print(f"  ✅ Descubrimientos:     {len(result.get('discoveries', []))}")
    print(f"  ✅ Candidatos Zaragoza: {len(result.get('local_candidates', []))}")

    return result