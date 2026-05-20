"""
main.py — CarrotBot

Orquestador principal. Ejecuta el pipeline completo:
  1. Carga artistas y géneros desde config/
  2. Agrega datos (RSS + Last.fm + Spotify) y procesa con IA
  3. Construye el email HTML
  4. Envía el email
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Carga variables de entorno
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from config.loader        import load_artists, load_genres
from news.aggregator      import aggregate
from email_builder.builder import build_email_html
from email_builder.sender  import send_email

BOT_NAME      = "CarrotBot"
EMAIL_SUBJECT = "🎵 CarrotBot — Tu resumen musical semanal"


def main() -> None:
    print("🥕 CarrotBot arrancando...\n")

    # ── 1. Cargar perfil musical ──────────────────────────────────────────────
    artists = load_artists()
    genres  = load_genres()

    # Excluir compositores de OST (excepto los que están en ost_keep.txt)
    exclude_path = Path(__file__).parent / "config" / "ost_exclude.txt"
    keep_path    = Path(__file__).parent / "config" / "ost_keep.txt"

    excluded = set()
    kept     = set()

    if exclude_path.exists():
        excluded = {
            line.strip().lower()
            for line in exclude_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }

    if keep_path.exists():
        kept = {
            line.strip().lower()
            for line in keep_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }

    artists = [a for a in artists if a.lower() not in excluded or a.lower() in kept]
    print(f"🎵 Artistas activos: {len(artists)}")
    print(f"🎸 Géneros activos:  {len(genres)}")

    # ── 2. Agregar datos y procesar con IA ───────────────────────────────────
    data = aggregate(artists, genres)

    # ── 3. Construir email ────────────────────────────────────────────────────
    print("\n📧 Construyendo email...")
    html_body = build_email_html(data, artists, genres)

    # ── 4. Enviar email ───────────────────────────────────────────────────────
    print("📤 Enviando email...")
    send_email(
        html_body=html_body,
        subject=EMAIL_SUBJECT,
        bot_name=BOT_NAME,
    )

    print("\n✅ CarrotBot finalizado correctamente.")


if __name__ == "__main__":
    main()