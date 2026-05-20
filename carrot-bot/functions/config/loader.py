def load_lines(filepath: str) -> list[str]:
    with open(filepath, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def load_artists() -> list[str]:
    return load_lines("config/artists.txt")

def load_genres() -> list[str]:
    return load_lines("config/genres.txt")