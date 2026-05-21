"""
news/ticketmaster_fetcher.py

Busca conciertos de los artistas favoritos del usuario
usando la API oficial de Ticketmaster Discovery v2.

Filtra por proximidad a España:
  0 → Zaragoza (se detecta por nombre de ciudad)
  1 → España
  2 → Portugal, Francia, Andorra
  3 → Alemania, Italia, Países Bajos, Bélgica, Suiza, Austria
  4 → Resto de Europa
  ignorar → fuera de Europa
"""

import os
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path

TICKETMASTER_API         = "https://app.ticketmaster.com/discovery/v2/events.json"
TICKETMASTER_ATTRACTIONS = "https://app.ticketmaster.com/discovery/v2/attractions.json"
REQUEST_DELAY            = 0.3   # segundos entre llamadas (rate limit: 5 req/s)
MONTHS_AHEAD             = 12    # buscar conciertos hasta X meses en el futuro

# ─── Mapas de proximidad ──────────────────────────────────────────────────────

COUNTRY_PROXIMITY = {
    # Nivel 1 — España
    "spain": 1, "es": 1,
    # Nivel 2 — Muy cerca
    "portugal": 2, "pt": 2,
    "france": 2, "fr": 2,
    "andorra": 2, "ad": 2,
    # Nivel 3 — Europa central accesible
    "germany": 3, "de": 3,
    "italy": 3, "it": 3,
    "netherlands": 3, "nl": 3,
    "belgium": 3, "be": 3,
    "switzerland": 3, "ch": 3,
    "austria": 3, "at": 3,
    "luxembourg": 3, "lu": 3,
    # Nivel 4 — Resto UE/Europa
    "great britain": 4, "gb": 4, "united kingdom": 4, "uk": 4,
    "ireland": 4, "ie": 4,
    "sweden": 4, "se": 4,
    "norway": 4, "no": 4,
    "denmark": 4, "dk": 4,
    "finland": 4, "fi": 4,
    "poland": 4, "pl": 4,
    "czech republic": 4, "cz": 4,
    "hungary": 4, "hu": 4,
    "romania": 4, "ro": 4,
    "greece": 4, "gr": 4,
    "croatia": 4, "hr": 4,
}

ZARAGOZA_NAMES = {"zaragoza", "saragossa"}

EU_COUNTRY_CODES = set(COUNTRY_PROXIMITY.keys())


# ─── Utilidades ───────────────────────────────────────────────────────────────

def _proximity(country_name: str, country_code: str, city_name: str) -> int | None:
    """
    Devuelve el nivel de proximidad a España (0-4) o None si está fuera de Europa.
    """
    city_l    = (city_name    or "").lower().strip()
    country_l = (country_name or "").lower().strip()
    code_l    = (country_code or "").lower().strip()

    # Zaragoza → nivel 0
    if city_l in ZARAGOZA_NAMES:
        return 0

    # Busca por nombre de país o código ISO
    if country_l in COUNTRY_PROXIMITY:
        return COUNTRY_PROXIMITY[country_l]
    if code_l in COUNTRY_PROXIMITY:
        return COUNTRY_PROXIMITY[code_l]

    return None  # Fuera de Europa → ignorar


def _date_range() -> tuple[str, str]:
    """Rango de fechas: hoy → X meses adelante."""
    start = datetime.now()
    end   = start + timedelta(days=30 * MONTHS_AHEAD)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_event(event: dict, artist_name: str) -> dict | None:
    """
    Convierte un evento de Ticketmaster en el formato estándar del bot.
    Devuelve None si está fuera de Europa.
    """
    venues = event.get("_embedded", {}).get("venues", [{}])
    venue  = venues[0] if venues else {}

    city         = venue.get("city",    {}).get("name", "")
    country_name = venue.get("country", {}).get("name", "")
    country_code = venue.get("country", {}).get("countryCode", "")
    venue_name   = venue.get("name", "")
    state        = venue.get("state",   {}).get("name", "")

    prox = _proximity(country_name, country_code, city)
    if prox is None:
        return None  # Fuera de Europa

    date_info = event.get("dates", {}).get("start", {})
    date      = date_info.get("localDate", "")
    time_str  = date_info.get("localTime", "")

    # Nombre del evento (puede incluir artistas support)
    event_name = event.get("name", artist_name)

    # URL de la entrada
    url = event.get("url", "")

    # Precio si está disponible
    price_ranges = event.get("priceRanges", [])
    price_str    = ""
    if price_ranges:
        pr       = price_ranges[0]
        currency = pr.get("currency", "")
        min_p    = pr.get("min", "")
        max_p    = pr.get("max", "")
        if min_p and max_p:
            price_str = f"{min_p}–{max_p} {currency}"
        elif min_p:
            price_str = f"desde {min_p} {currency}"

    # Ubicación legible
    location_parts = [p for p in [city, state, country_name] if p]
    location       = ", ".join(location_parts)

    return {
        "artist":    artist_name,
        "event":     event_name,
        "dates":     f"{date} {time_str}".strip(),
        "locations": location,
        "venue":     venue_name,
        "proximity": prox,
        "price":     price_str,
        "url":       url,
        "source":    "Ticketmaster",
    }


# ─── Lookup de attraction ID ─────────────────────────────────────────────────

def _find_attraction_id(artist_name: str, api_key: str) -> str | None:
    """
    Busca el ID de attraction exacto para un artista en Ticketmaster.
    Hace matching exacto por nombre (insensible a mayúsculas).
    Devuelve None si no hay coincidencia exacta.
    """
    try:
        response = requests.get(
            TICKETMASTER_ATTRACTIONS,
            params={"apikey": api_key, "keyword": artist_name, "size": 5},
            timeout=8,
        )
        if response.status_code != 200:
            return None
        attractions = response.json().get("_embedded", {}).get("attractions", [])
        artist_lower = artist_name.lower()
        for att in attractions:
            if att.get("name", "").lower() == artist_lower:
                return att["id"]
    except Exception:
        pass
    return None


# ─── Fetcher principal ────────────────────────────────────────────────────────

def _load_skip_list() -> set[str]:
    skip_path = Path(__file__).parent.parent / "config" / "ticketmaster_skip.txt"
    if not skip_path.exists():
        return set()
    return {
        line.strip().lower()
        for line in skip_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def fetch_ticketmaster_concerts(artists: list[str]) -> list[dict]:
    """
    Busca conciertos en Europa para cada artista de la lista.
    Usa attractionId cuando es posible para evitar falsos positivos por keyword.
    Devuelve eventos ordenados por proximidad a España.
    """
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        print("  ⚠️  TICKETMASTER_API_KEY no configurada")
        return []

    skip = _load_skip_list()
    start_date, end_date = _date_range()
    all_events = []
    seen_ids   = set()

    for artist_name in artists:
        if artist_name.lower() in skip:
            continue
        try:
            # Paso 1: buscar el attraction ID exacto del artista
            attraction_id = _find_attraction_id(artist_name, api_key)
            time.sleep(REQUEST_DELAY)

            # Paso 2: buscar eventos solo si hay attractionId exacto.
            # Sin él preferimos cero resultados a falsos positivos.
            if not attraction_id:
                continue

            response = requests.get(TICKETMASTER_API, params={
                "apikey":        api_key,
                "attractionId":  attraction_id,
                "size":          10,
                "startDateTime": start_date,
                "endDateTime":   end_date,
                "sort":          "date,asc",
            }, timeout=8)

            if response.status_code == 429:
                print(f"  ⚠️  Ticketmaster rate limit, esperando...")
                time.sleep(2)
                continue

            if response.status_code != 200:
                print(f"  ⚠️  Ticketmaster error {response.status_code} para {artist_name}")
                time.sleep(REQUEST_DELAY)
                continue

            data   = response.json()
            events = data.get("_embedded", {}).get("events", [])

            for event in events:
                event_id = event.get("id", "")
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)

                parsed = _parse_event(event, artist_name)
                if parsed:
                    all_events.append(parsed)

        except Exception as e:
            print(f"  ⚠️  Ticketmaster error ({artist_name}): {e}")

        time.sleep(REQUEST_DELAY)

    # Ordena: primero por proximidad (0 mejor), luego por fecha
    all_events.sort(key=lambda e: (e["proximity"], e["dates"]))

    # Deduplica: Ticketmaster devuelve múltiples "productos" para el mismo
    # concierto (VIP, pases de camping, planes de pago, upgrades...).
    # Conservamos solo el primer evento por (artista, día, sala).
    seen_shows: set[tuple] = set()
    deduped: list[dict] = []
    for e in all_events:
        show_key = (
            e.get("artist", "").lower().strip(),
            (e.get("dates", "") or "")[:10],
            e.get("venue", "").lower().strip(),
        )
        if show_key in seen_shows:
            continue
        seen_shows.add(show_key)
        deduped.append(e)
    all_events = deduped

    # Resumen por nivel
    by_prox = {}
    for e in all_events:
        p = e["proximity"]
        by_prox[p] = by_prox.get(p, 0) + 1

    labels = {0: "Zaragoza", 1: "España", 2: "Cerca", 3: "Europa central", 4: "Europa"}
    summary = ", ".join(f"{labels.get(p,'?')}: {n}" for p, n in sorted(by_prox.items()))
    print(f"  Ticketmaster → {len(all_events)} conciertos en Europa [{summary}]")

    return all_events