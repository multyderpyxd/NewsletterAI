import json
import os
from pathlib import Path

from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth
import spotipy

# Carga el .env desde functions/
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

# ─── Auth manual (compatible con Codespaces sin navegador local) ───────────────

auth_manager = SpotifyOAuth(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
    scope="user-top-read user-follow-read",
    open_browser=False,   # No intenta abrir navegador
)

# 1. Muestra la URL de autorización
auth_url = auth_manager.get_authorize_url()
print("\n🎵 Abre esta URL en tu navegador:\n")
print(auth_url)
print()

# 2. El usuario pega la URL de redirección completa
print("Después de autorizar, Spotify te redirigirá a una URL que empieza por:")
print(f"  {os.getenv('SPOTIFY_REDIRECT_URI')}?code=...")
print()
redirected_url = input("Pega aquí la URL completa a la que fuiste redirigido: ").strip()

# 3. Extrae el código y obtiene el token
code = auth_manager.parse_response_code(redirected_url)
token_info = auth_manager.get_access_token(code)

sp = spotipy.Spotify(auth_manager=auth_manager)

# ─── Descarga de datos ─────────────────────────────────────────────────────────

for term in ["short_term", "medium_term", "long_term"]:
    print(f"Descargando top artistas ({term})...")
    result = sp.current_user_top_artists(limit=50, time_range=term)
    output_path = OUTPUT_DIR / f"top_artists_{term}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"  → Guardado en {output_path}")

# Artistas seguidos — paginación completa (sin límite de 50)
print("Descargando artistas seguidos...")
all_followed = []
after = None

while True:
    batch = sp.current_user_followed_artists(limit=50, after=after)
    items = batch["artists"]["items"]
    all_followed.extend(items)
    print(f"  → {len(all_followed)} artistas descargados hasta ahora...")

    after = batch["artists"]["cursors"].get("after")
    if not after:
        break

output_path = OUTPUT_DIR / "followed_artists.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump({"artists": all_followed}, f, indent=2, ensure_ascii=False)
print(f"  → Total: {len(all_followed)} artistas guardados en {output_path}")

print("\n✅ Datos de Spotify guardados correctamente.")