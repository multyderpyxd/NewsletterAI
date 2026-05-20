"""
news/lastfm_fetcher.py

Consulta Last.fm para:
  - Novedades recientes de los artistas del usuario
  - Artistas similares para el bloque de descubrimientos
"""

import os
import time
import requests

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
REQUEST_DELAY  = 0.25   # segundos entre llamadas (rate limit)
SIMILAR_LIMIT  = 3      # artistas similares por artista
SIMILAR_MIN_MATCH = 0.4  # similitud mínima (0-1)


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


# ─── Lanzamientos recientes ───────────────────────────────────────────────────

def fetch_recent_releases(artists: list[str]) -> list[dict]:
    """
    Busca los álbumes más recientes de cada artista en Last.fm.
    Útil para detectar lanzamientos de bandas pequeñas que no salen en RSS.
    """
    releases = []

    for artist in artists:
        data  = _get({"method": "artist.getTopAlbums", "artist": artist, "limit": 3})
        albums = data.get("topalbums", {}).get("album", [])

        for album in albums[:2]:
            name = album.get("name", "").strip()
            url  = album.get("url",  "").strip()

            if name and name.lower() not in {"(null)", ""}:
                releases.append({
                    "artist": artist,
                    "album":  name,
                    "url":    url,
                    "source": "Last.fm",
                })

        time.sleep(REQUEST_DELAY)

    print(f"  Last.fm → {len(releases)} álbumes encontrados")
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