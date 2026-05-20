import json
import os
import time
import requests
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ─── Rutas ────────────────────────────────────────────────────────────────────

DATA_DIR   = Path(__file__).parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"

TOP_ARTISTS_LIMIT = 50  # Cuántos artistas guardar en artists.txt

# ─── Pesos por período ────────────────────────────────────────────────────────
#
# Puntos por posición (pos 0 = más escuchado):
#   short_term:  150 (pos 0) → 101 (pos 49)
#   medium_term:  75 (pos 0) →  26 (pos 49)
#   long_term:    25 (pos 0) →   1 (pos 49)
#   followed:      5 pts fijos
#
# Bonus combinación short + medium: +100 pts
# (artistas que llevas meses escuchando Y sigues escuchando ahora)

WEIGHTS = {
    "short_term":  {"base": 150, "min": 101},
    "medium_term": {"base":  75, "min":  26},
    "long_term":   {"base":  25, "min":   1},
}

FOLLOWED_BONUS     = 5
SHORT_MEDIUM_BONUS = 100

LASTFM_API_KEY     = os.getenv("LASTFM_API_KEY")
LASTFM_API_URL     = "https://ws.audioscrobbler.com/2.0/"
LASTFM_TOP_TAGS    = 5   # Cuántos tags coger por artista
LASTFM_MIN_COUNT   = 10  # Ignorar tags con menos de N votos (evita tags raros)

# Tags que no son géneros musicales útiles y se descartan
LASTFM_TAG_BLACKLIST = {
    # Nacionalidades y regiones
    "australian", "canadian", "japanese", "spanish", "greek", "latvian",
    "english", "england", "british", "american", "french", "german",
    "chinese", "japan", "latvia",
    # Décadas
    "60s", "70s", "80s", "90s", "00s",
    # Descriptores no musicales
    "seen live", "favorites", "favourite", "male vocalists", "female vocalists",
    "composer", "pianist", "singer-songwriter",
    # Categorías de medios
    "video game music", "video game", "game", "game soundtracks", "soundtrack",
    "anime", "doujin ongaku", "final fantasy",
    # Demasiado genéricos
    "music", "oldies", "misc",
}


# ─── Carga de datos ───────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if not path.exists():
        print(f"  ⚠️  No encontrado: {path}")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── Puntuación ───────────────────────────────────────────────────────────────

def score_artists() -> dict[str, dict]:
    scores = defaultdict(lambda: {"score": 0, "genres": set(), "terms": set()})

    # Top artistas por período
    for term, w in WEIGHTS.items():
        data  = load_json(DATA_DIR / f"top_artists_{term}.json")
        items = data.get("items", [])
        total = len(items)

        for pos, artist in enumerate(items):
            name = artist["name"]
            pts  = round(w["base"] - (w["base"] - w["min"]) * pos / max(total - 1, 1))

            scores[name]["score"] += pts
            scores[name]["terms"].add(term)

            for genre in artist.get("genres", []):
                scores[name]["genres"].add(genre)

    # Bonus combinación short + medium
    for name, data in scores.items():
        if {"short_term", "medium_term"}.issubset(data["terms"]):
            data["score"] += SHORT_MEDIUM_BONUS

    # Artistas seguidos (bonus fijo)
    followed_data  = load_json(DATA_DIR / "followed_artists.json")
    followed_items = followed_data.get("artists", [])

    for artist in followed_items:
        name = artist["name"]
        scores[name]["score"] += FOLLOWED_BONUS
        for genre in artist.get("genres", []):
            scores[name]["genres"].add(genre)

    return scores


# ─── Last.fm: géneros por artista ─────────────────────────────────────────────

def fetch_lastfm_genres(artist_name: str) -> list[str]:
    """Consulta Last.fm y devuelve los top tags del artista filtrados por popularidad."""
    if not LASTFM_API_KEY:
        return []

    try:
        response = requests.get(LASTFM_API_URL, params={
            "method":  "artist.getTopTags",
            "artist":  artist_name,
            "api_key": LASTFM_API_KEY,
            "format":  "json",
        }, timeout=5)

        data = response.json()
        tags = data.get("toptags", {}).get("tag", [])

        genres = []
        for tag in tags[:LASTFM_TOP_TAGS]:
            count = int(tag.get("count", 0))
            name  = tag.get("name", "").strip().lower()

            # Filtra tags genéricos, con pocos votos o en la blacklist
            if count >= LASTFM_MIN_COUNT and name not in {"seen live", "favorites", "favourite"} and name not in LASTFM_TAG_BLACKLIST:
                genres.append(name)

        return genres

    except Exception as e:
        print(f"    ⚠️  Error Last.fm para '{artist_name}': {e}")
        return []


def enrich_with_lastfm(scores: dict[str, dict], top_artists: list[tuple]) -> None:
    """Añade géneros de Last.fm a los artistas que no tienen géneros de Spotify."""
    print("\n🔍 Consultando Last.fm para géneros...")

    for i, (name, data) in enumerate(top_artists, 1):
        if data["genres"]:
            print(f"  {i:>2}. {name} → ya tiene géneros de Spotify, saltando")
            continue

        genres = fetch_lastfm_genres(name)

        if genres:
            data["genres"].update(genres)
            print(f"  {i:>2}. {name} → {', '.join(genres)}")
        else:
            print(f"  {i:>2}. {name} → sin géneros encontrados")

        time.sleep(0.25)  # Respetar rate limit de Last.fm


# ─── Generación de ficheros ───────────────────────────────────────────────────

def build_config(scores: dict[str, dict]) -> None:
    # Ordenar por puntuación descendente
    ranked = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    top    = ranked[:TOP_ARTISTS_LIMIT]

    # Enriquecer con Last.fm
    enrich_with_lastfm(scores, top)

    # artists.txt
    artists_path = CONFIG_DIR / "artists.txt"
    with open(artists_path, "w", encoding="utf-8") as f:
        for name, _ in top:
            f.write(name + "\n")

    print(f"\n🎵 Top {TOP_ARTISTS_LIMIT} artistas guardados en {artists_path}")
    print(f"{'Pos':>3}  {'Puntos':>6}  {'Términos':<30}  Artista")
    print("─" * 70)
    for i, (name, data) in enumerate(top, 1):
        terms = ", ".join(sorted(data["terms"])) or "followed"
        print(f"{i:>3}  {data['score']:>6}  {terms:<30}  {name}")

    # genres.txt — géneros de los top artistas, ordenados por frecuencia
    genre_count: dict[str, int] = defaultdict(int)
    for _, data in top:
        for genre in data["genres"]:
            genre_count[genre] += 1

    sorted_genres = sorted(genre_count.items(), key=lambda x: x[1], reverse=True)

    genres_path = CONFIG_DIR / "genres.txt"
    with open(genres_path, "w", encoding="utf-8") as f:
        for genre, _ in sorted_genres:
            f.write(genre + "\n")

    print(f"\n🎸 {len(sorted_genres)} géneros guardados en {genres_path}")
    print("   Top 10 géneros:", ", ".join(g for g, _ in sorted_genres[:10]))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Calculando puntuaciones...")
    scores = score_artists()
    print(f"Artistas únicos encontrados: {len(scores)}")
    build_config(scores)
    print("\n✅ config/artists.txt y config/genres.txt actualizados.")


if __name__ == "__main__":
    main()