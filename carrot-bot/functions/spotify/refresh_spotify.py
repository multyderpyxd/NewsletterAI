"""
spotify/refresh_spotify.py

Descarga no interactiva de datos de Spotify para Cloud Functions.
Usa SPOTIFY_REFRESH_TOKEN (variable de entorno) para obtener un token
sin intervención del usuario, y sobreescribe los JSON de spotify/data/.

Uso local (para probar sin pasar por el pipeline completo):
    python -m spotify.refresh_spotify
"""

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

# Mismo fichero de caché que usa spotify_fetcher.py
CACHE_PATH = str(Path(__file__).parent.parent / ".cache")


def _seed_cache() -> bool:
    """
    Escribe el fichero de caché de spotipy con el refresh token del entorno.
    Fuerza expires_at=0 para que spotipy lo renueve en la primera llamada.
    Devuelve False si SPOTIFY_REFRESH_TOKEN no está definido.
    """
    refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")
    if not refresh_token:
        print("  ⚠️  SPOTIFY_REFRESH_TOKEN no configurado — saltando refresh de Spotify")
        return False

    cache_data = {
        "access_token":  "",
        "token_type":    "Bearer",
        "expires_in":    3600,
        "scope":         "user-top-read user-follow-read",
        "expires_at":    0,
        "refresh_token": refresh_token,
    }
    Path(CACHE_PATH).write_text(json.dumps(cache_data), encoding="utf-8")
    return True


def refresh_spotify_data() -> None:
    """
    Descarga top artistas (3 períodos) y artistas seguidos desde Spotify.
    Guarda los resultados en spotify/data/ como JSON.
    """
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    if not _seed_cache():
        return

    auth_manager = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope="user-top-read user-follow-read",
        open_browser=False,
        cache_path=CACHE_PATH,
    )

    sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=10)

    for term in ["short_term", "medium_term", "long_term"]:
        print(f"  Spotify → top artistas ({term})...")
        result = sp.current_user_top_artists(limit=50, time_range=term)
        (OUTPUT_DIR / f"top_artists_{term}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        time.sleep(0.3)

    print("  Spotify → artistas seguidos...")
    all_followed: list[dict] = []
    after = None
    while True:
        batch = sp.current_user_followed_artists(limit=50, after=after)
        all_followed.extend(batch["artists"]["items"])
        after = batch["artists"]["cursors"].get("after")
        if not after:
            break
        time.sleep(0.3)

    (OUTPUT_DIR / "followed_artists.json").write_text(
        json.dumps({"artists": all_followed}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Spotify → {len(all_followed)} artistas seguidos descargados")


if __name__ == "__main__":
    refresh_spotify_data()
