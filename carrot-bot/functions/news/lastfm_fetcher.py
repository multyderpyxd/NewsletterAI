"""
news/lastfm_fetcher.py

Consulta Last.fm para:
  - Novedades recientes de los artistas del usuario
  - Artistas similares para el bloque de descubrimientos
"""

import os
import re
import time
import requests
from datetime import datetime, timedelta

LASTFM_API_URL    = "https://ws.audioscrobbler.com/2.0/"
REQUEST_DELAY     = 0.25   # segundos entre llamadas (rate limit)
SIMILAR_LIMIT     = 3      # artistas similares por artista
SIMILAR_MIN_MATCH = 0.4    # similitud mínima (0-1)
RECENT_MONTHS     = 12     # solo álbumes publicados en los últimos N meses


def _get(params: dict) -> dict:
    """Llamada base a la API de Last.fm."""
    api_key = os.getenv("LASTFM_API_KEY")
    if not api_key:
        return {}
    try:
        response = requests.get(LASTFM_API_URL, params={
            **params,
            "api_key": api_key,
            "format":  "json",
        }, timeout=5)
        return response.json()
    except Exception as e:
        print(f"  ⚠️  Last.fm error ({params.get('method')}): {e}")
        return {}


# ─── Fecha de lanzamiento de álbum ───────────────────────────────────────────

def _parse_lastfm_date(datestr: str) -> datetime | None:
    """Parsea el campo 'releasedate' de Last.fm: ' 23 Nov 2024, 00:00 '"""
    if not datestr:
        return None
    datestr = datestr.strip()
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", datestr)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y")
        except ValueError:
            pass
    m = re.match(r"^(\d{4})", datestr)
    if m:
        try:
            return datetime(int(m.group(1)), 1, 1)
        except ValueError:
            pass
    return None


def _get_album_releasedate(artist: str, album: str) -> datetime | None:
    """Consulta album.getInfo para obtener la fecha de lanzamiento."""
    data = _get({"method": "album.getInfo", "artist": artist, "album": album, "autocorrect": 1})
    datestr = data.get("album", {}).get("releasedate", "")
    return _parse_lastfm_date(datestr)


# ─── Lanzamientos recientes ───────────────────────────────────────────────────

def fetch_recent_releases(artists: list[str]) -> list[dict]:
    """
    Busca álbumes de los artistas que tengan menos de RECENT_MONTHS meses de antigüedad.
    Usa artist.getTopAlbums para obtener candidatos y album.getInfo para verificar la fecha.
    """
    releases = []
    cutoff   = datetime.now() - timedelta(days=30 * RECENT_MONTHS)

    # Limitamos a los primeros 25 artistas para no disparar el rate limit
    for artist in artists[:25]:
        data   = _get({"method": "artist.getTopAlbums", "artist": artist, "limit": 5})
        albums = data.get("topalbums", {}).get("album", [])
        time.sleep(REQUEST_DELAY)

        added = 0
        for album in albums[:5]:
            if added >= 2:
                break

            name = album.get("name", "").strip()
            url  = album.get("url",  "").strip()

            if not name or name.lower() in {"(null)", ""}:
                continue

            release_dt = _get_album_releasedate(artist, name)
            time.sleep(REQUEST_DELAY)

            # Incluir solo álbumes recientes (o futuros: pre-anuncios)
            if release_dt is None or release_dt < cutoff:
                continue

            releases.append({
                "artist":       artist,
                "album":        name,
                "url":          url,
                "source":       "Last.fm",
                "release_date": release_dt.strftime("%Y-%m-%d"),
            })
            added += 1

    print(f"  Last.fm → {len(releases)} lanzamientos recientes encontrados")
    return releases


# ─── Artistas similares ───────────────────────────────────────────────────────

def fetch_similar_artists(artists: list[str], known_artists: list[str]) -> list[dict]:
    """
    Busca artistas similares a los del usuario que éste NO conoce ya.
    Se usa para el bloque de descubrimientos.
    """
    known_lower    = {a.lower() for a in known_artists}
    similar_found  = {}  # nombre → {match, url, via}

    # Solo consultamos los primeros 20 artistas para no disparar el rate limit
    for artist in artists[:20]:
        data  = _get({"method": "artist.getSimilar", "artist": artist, "limit": 10})
        items = data.get("similarartists", {}).get("artist", [])

        for item in items:
            name  = item.get("name",  "").strip()
            match = float(item.get("match", 0))
            url   = item.get("url",   "").strip()

            if not name or match < SIMILAR_MIN_MATCH:
                continue
            if name.lower() in known_lower:
                continue
            if name not in similar_found or match > similar_found[name]["match"]:
                similar_found[name] = {"match": match, "url": url, "via": artist}

        time.sleep(REQUEST_DELAY)

    # Ordena por similitud descendente
    sorted_similar = sorted(similar_found.items(), key=lambda x: x[1]["match"], reverse=True)

    result = [
        {"name": name, "match": round(data["match"], 2), "url": data["url"], "via": data["via"]}
        for name, data in sorted_similar[:15]
    ]

    print(f"  Last.fm → {len(result)} artistas similares encontrados")
    return result