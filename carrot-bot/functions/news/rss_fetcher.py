"""
news/rss_fetcher.py

Busca artículos en feeds RSS y filtra los relevantes
para los artistas y géneros del usuario.
"""

import feedparser

# ─── Feeds RSS ────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    # ── Rock / metal / alternativo (mainstream) ───────────────────────────────
    "https://pitchfork.com/rss/news/",
    "https://www.nme.com/news/music/feed",
    "https://www.stereogum.com/feed/",
    "https://www.rollingstone.com/music/music-news/feed/",
    "https://consequence.net/feed/",
    "https://loudwire.com/feed/",
    "https://www.kerrang.com/feed",
    "https://www.altpress.com/feed/",
    # ── Metalcore / post-hardcore (nicho) ────────────────────────────────────
    "https://www.heavyblogisheavy.com/feed/",  # prog, math metal, metalcore
    "https://www.theprp.com/feed/",            # post-hardcore, metalcore
    # ── Electrónica / experimental ────────────────────────────────────────────
    "https://www.factmag.com/feed/",           # electrónica, experimental, avant-garde
    # ── Música japonesa / anime / videojuegos ────────────────────────────────
    "https://www.animenewsnetwork.com/all/rss.xml?ann-edition=us",  # anime/OST
    "https://www.siliconera.com/feed/",        # videojuegos japoneses, OST
    "https://www.gematsu.com/feed",            # noticias videojuegos japoneses
]

MAX_ARTICLES_PER_FEED = 10


# ─── Fetcher ──────────────────────────────────────────────────────────────────

def fetch_rss_articles(artists: list[str], genres: list[str]) -> list[dict]:
    """
    Descarga artículos de todos los feeds RSS.
    Devuelve los que mencionan algún artista o género del usuario,
    más una selección general de los más recientes.
    """
    all_articles  = []
    relevant      = []
    general       = []

    artist_lower = [a.lower() for a in artists]
    genre_lower  = [g.lower() for g in genres]

    for feed_url in RSS_FEEDS:
        try:
            feed   = feedparser.parse(feed_url)
            source = feed.feed.get("title", "Fuente desconocida")

            for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
                title   = entry.get("title",   "").strip()
                summary = entry.get("summary", "").strip()
                link    = entry.get("link",    "").strip()

                if not title or not link:
                    continue

                article = {
                    "source":   source,
                    "title":    title,
                    "summary":  summary[:500],  # limita resumen largo
                    "url":      link,
                    "relevant": False,
                }

                # Comprueba si menciona algún artista o género
                text_lower = (title + " " + summary).lower()

                if any(a in text_lower for a in artist_lower):
                    article["relevant"] = True
                    relevant.append(article)
                elif any(g in text_lower for g in genre_lower):
                    article["relevant"] = True
                    relevant.append(article)
                else:
                    general.append(article)

        except Exception as e:
            print(f"  ⚠️  Error leyendo feed {feed_url}: {e}")

    # Devuelve primero los relevantes, luego generales como contexto
    print(f"  RSS → {len(relevant)} artículos relevantes, {len(general)} generales")
    return relevant + general[:20]