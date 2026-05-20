"""
news/zaragoza_fetcher.py

Scrapea las agendas REALES de las salas de conciertos de Zaragoza.
NO busca por artista — lee la agenda de cada sala y devuelve
los eventos tal como aparecen. La IA decide después qué es relevante.

Salas incluidas:
  - La Lata de Bombillas (union25.org)
  - Rock & Blues Café (SweetCaroline + Union25)
  - Sala Z (conciertos.club)
  - La Casa del Loco (conciertos.club)
  - Sala López
  - Aragón Musical (agenda general)
"""

from __future__ import annotations

import re
import time
from html import unescape
from urllib.parse import urljoin


import requests
from bs4 import BeautifulSoup, Tag, SoupStrainer

REQUEST_DELAY  = 0.4
TIMEOUT        = 10
MAX_PAGES      = 4   # máximo de páginas a seguir por sala Union25

# ─── Salas y sus URLs de agenda ───────────────────────────────────────────────

VENUE_SOURCES = [
    {
        "venue":  "La Lata de Bombillas",
        "url":    "https://union25.org/sala/la-lata-de-bombillas/",
        "source": "Union25",
    },
    {
        "venue":  "Rock & Blues Café",
        "url":    "https://www.sweetcaroline.app/programacion8.php",
        "source": "SweetCaroline",
    },
    {
        "venue":  "Rock & Blues Café",
        "url":    "https://union25.org/sala/rock-and-blues-cafe/",
        "source": "Union25",
    },
    {
        "venue":  "La Casa del Loco",
        "url":    "https://conciertos.club/zaragoza/locales/la-casa-del-loco",
        "source": "Conciertos.club",
    },
    {
        "venue":  "Sala Z",
        "url":    "https://conciertos.club/zaragoza/locales/sala-z",
        "source": "Conciertos.club",
    },
    {
        "venue":  "",
        "url":    "https://www.aragonmusical.com/agenda/",
        "source": "Aragón Musical",
    },
    {
        "venue":  "",
        "url":    "https://conciertos.club/zaragoza",
        "source": "Conciertos.club Zaragoza",
    },
]


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def _get(url: str) -> BeautifulSoup | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; CarrotBot/1.0; "
            "+https://github.com/)"
        )
    }

    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        if r.status_code >= 400:
            print(f"  ⚠️  Zaragoza HTTP {r.status_code}: {url}")
            return None

        # Union25 a veces se interpreta como ISO-8859-1 aunque el HTML sea UTF-8.
        if not r.encoding or r.encoding.lower() in {"iso-8859-1", "windows-1252"}:
            r.encoding = r.apparent_encoding or "utf-8"

        return BeautifulSoup(r.text, "html.parser")

    except Exception as e:
        print(f"  ⚠️  Zaragoza fetch error ({url}): {e}")
        return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def _bad_title(text: str) -> bool:
    text = _clean(text).lower()

    if not text:
        return True

    rejected_exact = {
        "skip to content",
        "pasiones",
        "música / music",
        "musica / music",
        "películas / films",
        "peliculas / films",
        "libros / books",
        "deporte / sport",
        "viajes / trips",
        "modelos",
        "fotos modelos",
        "videos modelos",
        "quiénes somos",
        "quienes somos",
        "fundación",
        "fundacion",
        "contacto",
        "más info",
        "mas info",
        "ver más",
        "ver mas",
        "leer más",
        "leer mas",
        "comprar entradas",
        "entradas",
    }

    if text in rejected_exact:
        return True

    rejected_fragments = [
        "facebook",
        "instagram",
        "youtube",
        "tiktok",
        "linkedin",
        "cookie",
        "privacidad",
        "aviso legal",
    ]

    return any(fragment in text for fragment in rejected_fragments)


def _extract_union25_event_title_from_url(url: str) -> str:
    """
    Fallback para enlaces tipo:
    /concierto/candelabro-zaragoza-24-mayo-2026/
    """
    m = re.search(r"/concierto/([^/]+)/?", url)
    if not m:
        return ""

    slug = m.group(1)

    # Quitar sufijo de ciudad + fecha.
    slug = re.sub(
        r"-zaragoza-\d{1,2}-(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|setiembre|octubre|noviembre|diciembre)-\d{4}$",
        "",
        slug,
        flags=re.I,
    )

    return _clean(slug.replace("-", " ").title())


def _union25_date_from_url(url: str) -> str:
    """
    Extrae fecha aproximada desde slug si el bloque no trae fecha limpia.
    """
    m = re.search(
        r"-zaragoza-(\d{1,2})-"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|setiembre|octubre|noviembre|diciembre)-(\d{4})",
        url,
        re.I,
    )

    if not m:
        return ""

    return f"{m.group(1)} {m.group(2).title()} {m.group(3)}"


def _looks_like_date(text: str) -> bool:
    text = _clean(text).lower()

    return bool(
        re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", text)
        or re.search(
            r"\b\d{1,2}\s+"
            r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
            r"septiembre|setiembre|octubre|noviembre|diciembre)\b",
            text,
        )
    )


def _looks_like_time(text: str) -> bool:
    text = _clean(text).lower()
    return bool(re.search(r"\b\d{1,2}:\d{2}\s*(am|pm)?\b", text))


def _normalize_union25_venue(text: str, fallback: str) -> str:
    text_low = _clean(text).lower()

    if "la lata de bombillas" in text_low:
        return "La Lata de Bombillas"
    if "rock and blues" in text_low or "rock & blues" in text_low:
        return "Rock & Blues Café"

    return fallback


def _is_probable_event_link(a: Tag, venue: str) -> bool:
    text = _clean(a.get_text(" "))

    if len(text) < 3 or len(text) > 120:
        return False

    lowered = text.lower()

    rejected = {
        "inicio",
        "facebook",
        "instagram",
        "youtube",
        "tiktok",
        "linkedin",
        "ver mapa",
        "más info",
        "mas info",
        "volver a conciertos",
        "aviso de privacidad",
        "trabaja con nosotros",
    }

    if lowered in rejected:
        return False

    if lowered.startswith("http"):
        return False

    href = a.get("href", "")

    if "google.com" in href:
        return False

    # En Union25 los artistas aparecen como enlaces cercanos al bloque de próximos conciertos.
    # Evitamos enlaces del menú superior y de redes.
    parent_text = _clean(a.find_parent().get_text(" ") if a.find_parent() else "")
    context = _clean(
        " ".join(
            p.get_text(" ")
            for p in list(a.parents)[:4]
            if isinstance(p, Tag)
        )
    ).lower()

    if venue and venue.lower() in context:
        return True

    if _looks_like_date(context):
        return True

    if "/evento/" in href or "/concierto/" in href:
        return True

    # Caso real Union25: enlaces de artista con texto simple, seguidos de género/sala/fecha.
    if parent_text == text and len(text.split()) <= 8:
        return True

    return False


# ─── Parsers por fuente ───────────────────────────────────────────────────────

def _parse_union25(soup: BeautifulSoup, venue: str, source_url: str) -> list[dict]:
    """
    Union25 lista eventos en enlaces /concierto/... dentro de la página de sala.
    La plantilla incluye muchos enlaces de menú y botones 'Más Info', así que
    este parser se limita a URLs de concierto y recupera título/fecha desde
    el texto cercano o desde el slug.
    """
    events: list[dict] = []
    seen_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        url = urljoin(source_url, a["href"])

        if "/concierto/" not in url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        raw_title = _clean(a.get_text(" "))

        if _bad_title(raw_title):
            title = _extract_union25_event_title_from_url(url)
        else:
            title = raw_title

        if _bad_title(title) or len(title) < 3:
            title = _extract_union25_event_title_from_url(url)

        if not title or _bad_title(title):
            continue

        context_parts = []
        for parent in list(a.parents)[:5]:
            if isinstance(parent, Tag):
                text = _clean(parent.get_text(" "))
                if text and text not in context_parts:
                    context_parts.append(text)

        context = " ".join(context_parts)

        m_date = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", context)
        m_time = re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", context, re.I)

        date = ""
        if m_date:
            date = m_date.group(0)
            if m_time:
                date = f"{date} {m_time.group(0)}"

        if not date:
            date = _union25_date_from_url(url)

        parsed_venue = _normalize_union25_venue(context, venue)

        events.append({
            "artist": title,
            "event":  title,
            "date":   date,
            "venue":  parsed_venue,
            "url":    url,
            "source": "Union25",
        })

    return events

def _parse_sweetcaroline(soup: BeautifulSoup, source_url: str) -> list[dict]:
    """
    SweetCaroline carga la programación del Rock & Blues Café desde:
    https://www.sweetcaroline.app/programacion8.php

    La página contiene enlaces con textos tipo:
      Con Entrada PETIT COMITE 10 AÑOS SWEET CAROLINE REDD KROSS 21 MAYO
      Acceso Libre SONNY VINCENT 23 MAYO
    """
    events: list[dict] = []

    month = ""

    for node in soup.find_all(["h1", "h2", "h3", "h4", "a"]):
        text = _clean(node.get_text(" "))
        if not text:
            continue

        heading = text.strip("# ").upper()
        if heading in {
            "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
            "JULIO", "AGOSTO", "SEPTIEMBRE", "SETIEMBRE", "OCTUBRE",
            "NOVIEMBRE", "DICIEMBRE",
        }:
            month = heading.title()
            continue

        if node.name != "a":
            continue

        # Evitar controles de UI.
        if text.lower() in {"buscar"} or len(text) < 5:
            continue

        m = re.search(
            r"\b(\d{1,2})\s+"
            r"(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|"
            r"SEPTIEMBRE|SETIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)\b",
            text,
            re.I,
        )

        date = ""
        if m:
            date = f"{m.group(1)} {m.group(2).title()}"
        elif month:
            # Fallback por si la fecha aparece sin mes.
            m_day = re.search(r"\b(\d{1,2})\b", text)
            if m_day:
                date = f"{m_day.group(1)} {month}"

        title = text

        # Limpieza de prefijos habituales.
        title = re.sub(r"^(Acceso Libre|Con Entrada)\s+", "", title, flags=re.I)

        # Quitar fecha final del título.
        title = re.sub(
            r"\s+\d{1,2}\s+"
            r"(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|"
            r"SEPTIEMBRE|SETIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)\s*$",
            "",
            title,
            flags=re.I,
        )

        title = _clean(title)

        if not title or len(title) < 3:
            continue

        href = node.get("href", "")
        url = urljoin(source_url, href) if href else source_url

        events.append({
            "artist": title,
            "event":  title,
            "date":   date,
            "venue":  "Rock & Blues Café",
            "url":    url,
            "source": "SweetCaroline",
        })

    return events


def _parse_date_conciertos_club(text: str) -> str:
    """
    Parsea el formato de fecha de conciertos.club: 'V29/5/26 20:00'
    (letra día opcional + DD/M/YY + hora opcional).
    Devuelve 'DD/MM/YYYY HH:MM' o '' si no hay fecha.
    """
    m = re.search(r"[LMXJVSD]?(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if not m:
        return ""
    day, month, year = m.group(1), m.group(2), m.group(3)
    if len(year) == 2:
        year = "20" + year
    date = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
    m_time = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if m_time:
        date += f" {m_time.group(1)}"
    return date


def _parse_conciertos_club(soup: BeautifulSoup, venue: str, source_url: str) -> list[dict]:
    """
    Conciertos.club estructura cada evento como:
      <div>
        <div>V29/5/26<br>20:00</div>   ← fecha
        <a href="/zaragoza/conciertos/ID-slug"><img></a>
        <a href="/zaragoza/conciertos/ID-slug">Nombre artista</a>
        <span>Género</span>
        <a href="/zaragoza/locales/...">Sala. Zaragoza</a>
        <span>Precio</span>
      </div>
    Los enlaces de evento tienen '/zaragoza/conciertos/' en el href.
    """
    events  = []
    seen    = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/zaragoza/conciertos/" not in href:
            continue

        title = _clean(a.get_text(" "))
        if not title or len(title) < 3:
            continue  # saltar enlace de imagen (sin texto)

        url = urljoin(source_url, href)
        if url in seen:
            continue
        seen.add(url)

        # Buscar fecha en los hijos del contenedor padre
        date = ""
        parent = a.parent
        if isinstance(parent, Tag):
            for child in parent.children:
                if not isinstance(child, Tag):
                    continue
                child_text = _clean(child.get_text(" "))
                date = _parse_date_conciertos_club(child_text)
                if date:
                    break

        events.append({
            "artist": title,
            "event":  title,
            "date":   date,
            "venue":  venue,
            "url":    url,
            "source": "Conciertos.club",
        })

    return events


def _parse_aragon_musical(soup: BeautifulSoup, source_url: str) -> list[dict]:
    """
    Aragón Musical tiene una agenda con entradas de blog/eventos.
    """
    events = []

    for item in soup.select("article, .event, .agenda-item, .entry"):
        title_tag = item.find(["h1", "h2", "h3"])
        if not title_tag:
            continue
        title = _clean(title_tag.get_text(" "))
        if not title or len(title) < 3:
            continue

        date = ""
        date_tag = item.find("time")
        if date_tag:
            date = _clean(date_tag.get("datetime") or date_tag.get_text(" "))

        item_text = _clean(item.get_text(" ")).lower()
        venue = ""
        for known_venue in [
            "la lata de bombillas", "rock & blues", "rock and blues",
            "sala z", "la casa del loco", "sala lópez", "sala lopez",
            "las armas", "auditorio", "pabellón príncipe felipe",
        ]:
            if known_venue in item_text:
                venue = known_venue.title()
                venue = venue.replace("Rock & Blues", "Rock & Blues Café")
                venue = venue.replace("Rock And Blues", "Rock & Blues Café")
                venue = venue.replace("Sala Lopez", "Sala López")
                break

        link_tag = item.find("a", href=True)
        url = urljoin(source_url, link_tag["href"]) if link_tag else source_url

        events.append({
            "artist": title,
            "event":  title,
            "date":   date,
            "venue":  venue,
            "url":    url,
            "source": "Aragón Musical",
        })

    return events


# ─── Deduplicación ────────────────────────────────────────────────────────────

def _dedupe(events: list[dict]) -> list[dict]:
    seen = set()
    result = []

    for e in events:
        artist = e.get("artist", "").lower().strip()
        venue = e.get("venue", "").lower().strip()
        date = e.get("date", "").lower().strip()
        url = e.get("url", "").lower().strip()

        if not artist or _bad_title(artist):
            continue

        if url:
            key = ("url", url)
        else:
            key = ("event", artist, venue, date)

        if key in seen:
            continue

        seen.add(key)
        result.append(e)

    return result

# ─── Enriquecimiento de género (páginas individuales Union25) ────────────────

def _extract_union25_genre(soup: BeautifulSoup) -> str:
    """
    En Union25, el género específico del artista aparece en headings como:
      "Candelabro (Indie Rock / Art Rock / Post-Rock)"
    Extrae el contenido entre paréntesis si contiene al menos una "/".
    """
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = _clean(tag.get_text(" "))
        m = re.search(r"\(([^)]+/[^)]+)\)", text)
        if m:
            return m.group(1).strip()
    return ""


def enrich_with_genres(events: list[dict], max_requests: int = 20) -> list[dict]:
    """
    Para eventos de Union25, visita la página individual de cada evento
    y extrae el género específico del artista.
    Limita a max_requests peticiones para controlar la latencia.
    """
    enriched = []
    count    = 0

    for e in events:
        url = e.get("url", "")
        if count < max_requests and "union25.org/concierto/" in url:
            soup = _get(url)
            if soup:
                genre = _extract_union25_genre(soup)
                if genre:
                    e = {**e, "genre": genre}
            count += 1
            time.sleep(REQUEST_DELAY)
        enriched.append(e)

    if count:
        print(f"  Zaragoza → género enriquecido en {count} eventos Union25")
    return enriched


# ─── Paginación Union25 ───────────────────────────────────────────────────────

def _fetch_union25_all_pages(base_url: str, venue: str) -> list[dict]:
    """
    Scrapea todas las páginas de una sala Union25 hasta MAX_PAGES.
    Union25 usa paginación numerada: base_url, base_url/2/, base_url/3/, ...
    Para cuando la página devuelve eventos ya vistos o ninguno nuevo.
    """
    all_events: list[dict] = []
    seen_event_urls: set[str] = set()
    base = base_url.rstrip("/")

    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base}/{page}/"

        soup = _get(url)
        if not soup:
            break

        events   = _parse_union25(soup, venue, url)
        new_ones = [e for e in events if e.get("url") not in seen_event_urls]

        if not new_ones and page > 1:
            break  # sin eventos nuevos → no hay más páginas

        for e in events:
            seen_event_urls.add(e.get("url", ""))

        all_events.extend(events)
        time.sleep(REQUEST_DELAY)

    return all_events


# ─── Función principal ────────────────────────────────────────────────────────

def fetch_zaragoza_venue_agenda() -> list[dict]:
    """
    Scrapea las agendas reales de las salas de Zaragoza.
    Devuelve eventos tal como aparecen — sin filtrar por artista.
    La IA decide qué es relevante para el usuario.
    """
    all_events = []

    for source in VENUE_SOURCES:
        url = source["url"]
        venue = source["venue"]

        if "union25" in url:
            events = _fetch_union25_all_pages(url, venue)
        else:
            soup = _get(url)
            if not soup:
                time.sleep(REQUEST_DELAY)
                continue

            if "sweetcaroline.app" in url:
                events = _parse_sweetcaroline(soup, url)
            elif "conciertos.club" in url:
                events = _parse_conciertos_club(soup, venue, url)
            elif "aragonmusical" in url:
                events = _parse_aragon_musical(soup, url)
            else:
                events = []

        print(f"  Zaragoza [{source['source']} / {venue or 'general'}] → {len(events)} eventos")
        all_events.extend(events)
        time.sleep(REQUEST_DELAY)

    all_events = _dedupe(all_events)
    print(f"  Zaragoza total → {len(all_events)} eventos únicos en agenda")
    return all_events