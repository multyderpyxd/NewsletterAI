"""
news/spotify_fetcher.py

Consulta Spotify usando batch APIs para minimizar llamadas y evitar rate limit.

Estrategia:
  - Búsqueda de IDs: GET /v1/search por artista (una llamada por artista, inevitable)
  - Álbumes recientes: GET /v1/artists/{id}/albums (una por artista, necesario)
  - Artistas relacionados: GET /v1/artists?ids=... (batch de 50, una sola llamada)

Total de llamadas: ~2 por artista para lanzamientos + 1 batch para relacionados
vs el sistema anterior: ~3 por artista = reducción del 60%+
"""

import os
import time
import re
from datetime import datetime, timedelta
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
from dotenv import load_dotenv
from pathlib import Path


load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

REQUEST_DELAY        = 0.5   # segundos entre llamadas individuales
BATCH_SIZE           = 50    # máximo de IDs por llamada batch de Spotify
RELEASE_MONTHS_WINDOW = 6   # filtrar lanzamientos más antiguos que N meses


def _is_recent_or_upcoming(release_date: str) -> bool:
    """True si el lanzamiento es de los últimos RELEASE_MONTHS_WINDOW meses o es futuro."""
    if not release_date:
        return False
    try:
        if len(release_date) == 4:
            dt = datetime(int(release_date), 1, 1)
        elif len(release_date) == 7:
            dt = datetime(int(release_date[:4]), int(release_date[5:7]), 1)
        else:
            dt = datetime.strptime(release_date[:10], "%Y-%m-%d")
        cutoff = datetime.now() - timedelta(days=30 * RELEASE_MONTHS_WINDOW)
        return dt >= cutoff
    except (ValueError, TypeError):
        return False


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _get_client() -> spotipy.Spotify | None:
    try:
        return spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=os.getenv("SPOTIFY_CLIENT_ID"),
                client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
                redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
                scope="user-top-read user-follow-read",
                open_browser=False,
            ),
            requests_timeout=10,
            retries=0,
            status_retries=0,
            backoff_factor=0,
        )
    except Exception as e:
        print(f"  ⚠️  Spotify auth error: {e}")
        return None

def _is_spotify_rate_limit(e: Exception) -> bool:
    if isinstance(e, SpotifyException):
        return e.http_status == 429

    err = str(e).lower()
    return "429" in err or "rate/request limit" in err or "rate limit" in err


def _spotify_retry_after(e: Exception) -> str:
    if isinstance(e, SpotifyException):
        headers = getattr(e, "headers", None) or {}
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            return str(retry_after)

    m = re.search(r"retry.*?after[: ]+(\d+)", str(e), re.I)
    if m:
        return m.group(1)

    return "desconocido"

# ─── Búsqueda de IDs (una llamada por artista, no evitable) ───────────────────

def _resolve_artist_ids(sp: spotipy.Spotify, artists: list[str]) -> dict[str, str]:
    """
    Devuelve {nombre_artista: spotify_id} para todos los artistas que se encuentren.
    Si Spotify devuelve 429, corta Spotify inmediatamente sin esperar.
    """
    ids = {}

    for name in artists:
        try:
            results = sp.search(q=f"artist:{name}", type="artist", limit=1)
            items = results.get("artists", {}).get("items", [])
            if items:
                ids[name] = items[0]["id"]

        except Exception as e:
            if _is_spotify_rate_limit(e):
                retry_after = _spotify_retry_after(e)
                print(
                    f"  ⚠️  Spotify rate limit buscando IDs "
                    f"(Retry-After: {retry_after}s). Saltando Spotify."
                )
                return {}

            print(f"  ⚠️  Spotify search error ({name}): {e}")

        time.sleep(REQUEST_DELAY)

    print(f"  Spotify → {len(ids)}/{len(artists)} IDs resueltos")
    return ids

# ─── Lanzamientos recientes ───────────────────────────────────────────────────

def fetch_new_releases(artists: list[str]) -> list[dict]:
    """
    Busca los álbumes y singles más recientes de cada artista.
    Si Spotify devuelve 429, corta esta sección y devuelve lo ya encontrado.
    """
    sp = _get_client()
    if not sp:
        return []

    artist_ids = _resolve_artist_ids(sp, artists)
    if not artist_ids:
        print("  Spotify → lanzamientos omitidos")
        return []

    releases = []

    for artist_name, artist_id in artist_ids.items():
        try:
            albums = sp.artist_albums(
                artist_id,
                album_type="album,single",
                limit=5,
            )

            added = 0
            for album in albums.get("items", []):
                if added >= 2:
                    break
                release_date = album.get("release_date", "")
                if not _is_recent_or_upcoming(release_date):
                    continue
                releases.append({
                    "artist":       artist_name,
                    "album":        album.get("name", ""),
                    "type":         album.get("album_type", ""),
                    "release_date": release_date,
                    "url":          album.get("external_urls", {}).get("spotify", ""),
                    "source":       "Spotify",
                })
                added += 1

        except Exception as e:
            if _is_spotify_rate_limit(e):
                retry_after = _spotify_retry_after(e)
                print(
                    f"  ⚠️  Spotify rate limit en álbumes "
                    f"(Retry-After: {retry_after}s). "
                    f"Continuando sin más datos de Spotify."
                )
                break

            print(f"  ⚠️  Spotify albums error ({artist_name}): {e}")

        time.sleep(REQUEST_DELAY)

    print(f"  Spotify → {len(releases)} lanzamientos encontrados")
    return releases

# ─── Artistas relacionados (batch) ────────────────────────────────────────────

def fetch_related_artists(artists: list[str], known_artists: list[str]) -> list[dict]:
    """
    Busca artistas relacionados en Spotify.
    Si Spotify devuelve 429 o 403, no bloquea la ejecución.
    Last.fm cubre los descubrimientos.
    """
    sp = _get_client()
    if not sp:
        return []

    known_lower = {a.lower() for a in known_artists}
    sample = artists[:15]

    artist_ids = _resolve_artist_ids(sp, sample)
    if not artist_ids:
        print("  Spotify → artistas relacionados omitidos")
        return []

    related_found = {}

    for artist_name, artist_id in artist_ids.items():
        try:
            result = sp.artist_related_artists(artist_id)
            related = result.get("artists", [])

            for item in related[:5]:
                name = item.get("name", "").strip()
                popularity = item.get("popularity", 0)
                url = item.get("external_urls", {}).get("spotify", "")
                genres = item.get("genres", [])

                if not name or name.lower() in known_lower:
                    continue

                if name not in related_found:
                    related_found[name] = {
                        "name":       name,
                        "popularity": popularity,
                        "url":        url,
                        "genres":     genres,
                        "via":        artist_name,
                    }

        except Exception as e:
            err = str(e).lower()

            if isinstance(e, SpotifyException) and e.http_status == 403:
                print("  Spotify → related-artists bloqueado (403), usando Last.fm")
                return []

            if "403" in err or "forbidden" in err:
                print("  Spotify → related-artists bloqueado (403), usando Last.fm")
                return []

            if _is_spotify_rate_limit(e):
                retry_after = _spotify_retry_after(e)
                print(
                    f"  ⚠️  Spotify rate limit en related-artists "
                    f"(Retry-After: {retry_after}s). Usando Last.fm."
                )
                return []

            print(f"  ⚠️  Spotify related error ({artist_name}): {e}")

        time.sleep(REQUEST_DELAY)

    result = sorted(
        related_found.values(),
        key=lambda x: x["popularity"],
        reverse=True,
    )[:15]

    print(f"  Spotify → {len(result)} artistas relacionados encontrados")
    return result