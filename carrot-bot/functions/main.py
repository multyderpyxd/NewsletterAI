"""
main.py — CarrotBot

Orquestador principal. Ejecuta el pipeline completo:
  1. Carga artistas y géneros desde config/
  2. Agrega datos (RSS + Last.fm + Spotify) y procesa con IA
  3. Construye el email HTML
  4. Envía el email

── Ejecución local ──────────────────────────────────────────────────────────
  python main.py               → pipeline estándar (sin refresh Spotify)
  python main.py --full        → pipeline completo (refresh Spotify + parse)

── Ejecución en Firebase Cloud Functions ────────────────────────────────────
  La función 'weekly_newsletter' se dispara automáticamente según SCHEDULE.

── Cambiar el día u hora de envío ───────────────────────────────────────────
  Edita SCHEDULE y TIMEZONE y vuelve a desplegar:
    firebase deploy --only functions
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from config.loader         import load_artists, load_genres
from news.aggregator       import aggregate
from email_builder.builder import build_email_html
from email_builder.sender  import send_email

BOT_NAME      = "CarrotBot"
EMAIL_SUBJECT = "🎵 CarrotBot — Tu resumen musical semanal"

# ── Configuración del schedule ────────────────────────────────────────────────
# Formato cron unix:  minuto hora día-mes mes día-semana
# Días de semana:     0=domingo, 1=lunes, 2=martes, ..., 6=sábado
SCHEDULE = "0 8 * * 1"    # lunes a las 08:00
TIMEZONE  = "Europe/Madrid"


# ── Pipeline principal ────────────────────────────────────────────────────────

def main() -> None:
    print("🥕 CarrotBot arrancando...\n")

    artists = load_artists()
    genres  = load_genres()

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

    data = aggregate(artists, genres)

    print("\n📧 Construyendo email...")
    html_body = build_email_html(data, artists, genres)

    print("📤 Enviando email...")
    send_email(html_body=html_body, subject=EMAIL_SUBJECT, bot_name=BOT_NAME)

    print("\n✅ CarrotBot finalizado correctamente.")


# ── Pipeline completo (Cloud Functions + uso local con --full) ────────────────

def run_full_pipeline() -> None:
    """
    Pipeline completo con refresh de Spotify y persistencia de historiales:
      1. Descarga historiales desde GCS
      2. Refresca datos de Spotify (requiere SPOTIFY_REFRESH_TOKEN)
      3. Recalcula artists.txt y genres.txt
      4. Ejecuta el pipeline principal
      5. Sube historiales actualizados a GCS
    """
    from storage                   import pull_histories, push_histories
    from spotify.refresh_spotify   import refresh_spotify_data
    from spotify.parse_spotify     import main as parse_spotify

    print("\n[1/5] Descargando historiales desde GCS...")
    pull_histories()

    print("\n[2/5] Refrescando datos de Spotify...")
    refresh_spotify_data()

    print("\n[3/5] Actualizando perfil musical (artists.txt / genres.txt)...")
    parse_spotify()

    print("\n[4/5] Pipeline principal...")
    main()

    print("\n[5/5] Guardando historiales en GCS...")
    push_histories()


# ── Firebase Cloud Function ───────────────────────────────────────────────────

try:
    import firebase_admin
    from firebase_functions import options, scheduler_fn

    options.set_global_options(
        region="europe-southwest1",
        memory=options.MemoryOption.GB_1,
        timeout_sec=540,
    )

    if not firebase_admin._apps:
        firebase_admin.initialize_app()

    @scheduler_fn.on_schedule(
        schedule=SCHEDULE,
        timezone=scheduler_fn.Timezone(TIMEZONE),
    )
    def weekly_newsletter(event: scheduler_fn.ScheduledEvent) -> None:
        """Se ejecuta cada lunes a las 08:00 hora de Madrid."""
        run_full_pipeline()

except ImportError:
    pass  # entorno local sin firebase_functions instalado


# ── Punto de entrada local ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CarrotBot — newsletter musical semanal")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Pipeline completo: refresh Spotify + recalcular config + enviar email",
    )
    args = parser.parse_args()

    if args.full:
        run_full_pipeline()
    else:
        main()
