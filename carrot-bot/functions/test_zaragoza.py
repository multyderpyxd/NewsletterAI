"""
test_zaragoza.py — Diagnóstico del scraper de salas de Zaragoza.

Uso desde el Codespace:
    cd carrot-bot/functions
    python test_zaragoza.py
"""

import re
import time
from html import unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

# ── Copias mínimas de las funciones necesarias ────────────────────────────────

REQUEST_DELAY = 0.4
TIMEOUT       = 10
MAX_PAGES     = 4


def _get(url: str) -> BeautifulSoup | None:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; CarrotBot-test/1.0)"}
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        if r.status_code >= 400:
            print(f"  HTTP {r.status_code}: {url}")
            return None
        if not r.encoding or r.encoding.lower() in {"iso-8859-1", "windows-1252"}:
            r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  Error al cargar {url}: {e}")
        return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def _extract_title_from_url(url: str) -> str:
    m = re.search(r"/concierto/([^/]+)/?", url)
    if not m:
        return ""
    slug = m.group(1)
    slug = re.sub(
        r"-zaragoza-\d{1,2}-(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|setiembre|octubre|noviembre|diciembre)-\d{4}$",
        "", slug, flags=re.I,
    )
    return _clean(slug.replace("-", " ").title())


def _parse_union25_page(soup: BeautifulSoup, source_url: str) -> list[dict]:
    events = []
    seen   = set()
    for a in soup.find_all("a", href=True):
        url = urljoin(source_url, a["href"])
        if "/concierto/" not in url or url in seen:
            continue
        seen.add(url)
        title = _clean(a.get_text(" ")) or _extract_title_from_url(url)
        if not title or len(title) < 3:
            title = _extract_title_from_url(url)
        if not title or len(title) < 3:
            continue
        # fecha desde contexto
        context = " ".join(
            _clean(p.get_text(" "))
            for p in list(a.parents)[:5]
            if isinstance(p, Tag)
        )
        m_date = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", context)
        m_time = re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", context, re.I)
        date = ""
        if m_date:
            date = m_date.group(0)
            if m_time:
                date += f" {m_time.group(0)}"
        if not date:
            m = re.search(
                r"-zaragoza-(\d{1,2})-"
                r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
                r"septiembre|setiembre|octubre|noviembre|diciembre)-(\d{4})",
                url, re.I,
            )
            if m:
                date = f"{m.group(1)} {m.group(2).title()} {m.group(3)}"
        events.append({"title": title, "date": date, "url": url})
    return events


# ── Test principal ────────────────────────────────────────────────────────────

def test_union25_pagination(base_url: str, venue_name: str) -> None:
    print(f"\n{'='*60}")
    print(f"SALA: {venue_name}")
    print(f"URL base: {base_url}")
    print(f"{'='*60}")

    all_events      = []
    seen_event_urls = set()
    base            = base_url.rstrip("/")

    for page in range(1, MAX_PAGES + 1):
        url  = base_url if page == 1 else f"{base}/{page}/"
        print(f"\n  >> Cargando página {page}: {url}")

        soup = _get(url)
        if not soup:
            print(f"     ✗ No se pudo cargar")
            break

        events   = _parse_union25_page(soup, url)
        new_ones = [e for e in events if e["url"] not in seen_event_urls]

        print(f"     Eventos totales en la página : {len(events)}")
        print(f"     Eventos NUEVOS (no vistos)   : {len(new_ones)}")

        if not new_ones and page > 1:
            print(f"     → Sin eventos nuevos, fin de paginación.")
            break

        for e in events:
            seen_event_urls.add(e["url"])

        for e in new_ones:
            marker = " ⭐ ARTISTA SEGUIDO" if "pink breath of heaven" in e["title"].lower() else ""
            print(f"       - [{e['date'] or 'sin fecha'}] {e['title']}{marker}")
            all_events.append({**e, "page": page})

        time.sleep(REQUEST_DELAY)

    print(f"\n  TOTAL eventos recogidos de '{venue_name}': {len(all_events)}")

    # Búsqueda explícita de Pink Breath of Heaven
    pboh = [e for e in all_events if "pink breath of heaven" in e["title"].lower()]
    if pboh:
        print(f"\n  ✅ Pink Breath of Heaven ENCONTRADO (página {pboh[0]['page']}):")
        for e in pboh:
            print(f"     Fecha: {e['date']} | URL: {e['url']}")
    else:
        print(f"\n  ✗ Pink Breath of Heaven NO encontrado en ninguna página.")


if __name__ == "__main__":
    venues = [
        ("https://union25.org/sala/la-lata-de-bombillas/", "La Lata de Bombillas"),
        ("https://union25.org/sala/rock-and-blues-cafe/",  "Rock & Blues Café"),
    ]
    for url, name in venues:
        test_union25_pagination(url, name)

    print("\n" + "="*60)
    print("Diagnóstico completado.")
