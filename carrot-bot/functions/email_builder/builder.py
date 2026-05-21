"""
email_builder/builder.py

Construye el HTML del email a partir del JSON estructurado
devuelto por el aggregator. Estilo oscuro, editorial.

Bloques:
  🎫 Conciertos y giras          → acento naranja/ámbar
  🎵 Nuevos lanzamientos         → acento verde menta
  🔭 Descubrimientos             → acento violeta/lila
  📍 Candidatos locales Zaragoza → acento rojo coral
"""

from datetime import datetime
from html import escape


# ─── Paleta de colores ────────────────────────────────────────────────────────

COLORS = {
    "bg":                "#0f0f0f",
    "surface":           "#1a1a1a",
    "surface2":          "#222222",
    "border":            "#2e2e2e",
    "text":              "#e8e8e8",
    "text_muted":        "#888888",
    "concerts":          "#f5a623",
    "releases":          "#4ecdc4",
    "discoveries":       "#a78bfa",
    "local_candidates":  "#ff6b6b",
    "tag_bg":            "#2a2a2a",
}

PROXIMITY_LABELS = {
    0: ("📍", "Zaragoza"),
    1: ("🔴", "España"),
    2: ("🟠", "Muy cerca"),
    3: ("🟡", "Europa central"),
    4: ("🟢", "UE"),
}

CARROT_PATTERN = """
<svg style="position:absolute;top:0;left:0;width:100%;height:100%;opacity:0.045;pointer-events:none;" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <pattern id="carrots" x="0" y="0" width="60" height="60" patternUnits="userSpaceOnUse">
      <g transform="translate(15,8) rotate(15)">
        <path d="M4,0 C4,0 6,8 4,18 C2,8 0,0 4,0Z" fill="#e8874a"/>
        <line x1="4" y1="0" x2="2" y2="-5" stroke="#5a8a3c" stroke-width="1.2" stroke-linecap="round"/>
        <line x1="4" y1="0" x2="4" y2="-6" stroke="#5a8a3c" stroke-width="1.2" stroke-linecap="round"/>
        <line x1="4" y1="0" x2="6" y2="-5" stroke="#5a8a3c" stroke-width="1.2" stroke-linecap="round"/>
      </g>
      <g transform="translate(42,35) rotate(-20)">
        <path d="M3,0 C3,0 5,7 3,15 C1,7 0,0 3,0Z" fill="#e8874a"/>
        <line x1="3" y1="0" x2="1" y2="-4" stroke="#5a8a3c" stroke-width="1" stroke-linecap="round"/>
        <line x1="3" y1="0" x2="3" y2="-5" stroke="#5a8a3c" stroke-width="1" stroke-linecap="round"/>
        <line x1="3" y1="0" x2="5" y2="-4" stroke="#5a8a3c" stroke-width="1" stroke-linecap="round"/>
      </g>
    </pattern>
  </defs>
  <rect width="100%" height="100%" fill="url(#carrots)"/>
</svg>
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _e(value: object) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


def _safe_url(url: str) -> str:
    url = (url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return ""
    return _e(url)


# ─── Componentes base ─────────────────────────────────────────────────────────

def _section_header(emoji: str, title: str, color: str, count: int) -> str:
    return f"""
<tr>
  <td style="padding: 36px 0 16px 0;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="border-left: 3px solid {color}; padding: 4px 0 4px 16px;">
          <div style="font-family: Georgia, serif; font-size: 11px; letter-spacing: 3px;
            text-transform: uppercase; color: {color}; margin-bottom: 4px;">{emoji} {_e(title)}</div>
          <div style="font-family: Georgia, serif; font-size: 22px; font-weight: bold;
            color: {COLORS['text']};">{count} {'elemento' if count == 1 else 'elementos'}</div>
        </td>
      </tr>
    </table>
  </td>
</tr>
"""


def _tag(text: str, color: str) -> str:
    if not text:
        return ""
    return f"""<span style="display: inline-block; background: {COLORS['tag_bg']}; color: {color};
      font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; padding: 3px 8px;
      border-radius: 2px; margin-right: 6px; margin-bottom: 4px;
      border: 1px solid {color}33;">{_e(text)}</span>"""


def _card_open(accent: str, bg: str | None = None) -> str:
    background = bg or COLORS["surface"]
    return f"""
<tr>
  <td style="padding: 0 0 12px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="
      background: {background}; border-radius: 6px;
      border-left: 3px solid {accent}; overflow: hidden;">
      <tr><td style="padding: 20px 24px;">
"""


def _card_close() -> str:
    return "</td></tr></table></td></tr>\n"


def _secondary(inner_html: str, color: str) -> str:
    """
    Bloque de información secundaria visualmente de-enfatizado.
    Separado del contenido principal por una línea tenue.
    Gmail elimina la interactividad de <details>, así que usamos
    jerarquía visual estática en lugar de collapse/expand.
    """
    return f"""<div style="margin-top: 10px; padding-top: 10px;
  border-top: 1px solid {color}22;">
  {inner_html}
</div>"""


def _link_button(url: str, label: str, color: str) -> str:
    safe = _safe_url(url)
    if not safe:
        return ""
    return f"""<a href="{safe}" style="display: inline-block; margin-top: 12px;
      padding: 7px 16px; background: transparent; border: 1px solid {color}; color: {color};
      font-family: 'Courier New', monospace; font-size: 11px; letter-spacing: 1px;
      text-decoration: none; border-radius: 3px;">→ {_e(label)}</a>"""


def _empty_block(message: str, color: str) -> str:
    return f"""
<tr><td style="padding: 16px 24px; background: {COLORS['surface']}; border-radius: 6px;
  border-left: 3px solid {color}; margin-bottom: 12px;">
  <span style="font-size: 13px; color: {COLORS['text_muted']}; font-style: italic;">{_e(message)}</span>
</td></tr>
"""


# ─── Bloque 1: Conciertos ─────────────────────────────────────────────────────

def _render_concerts(concerts: list[dict]) -> str:
    if not concerts:
        return _empty_block("No se encontraron conciertos esta semana.", COLORS["concerts"])

    color = COLORS["concerts"]
    rows  = _section_header("🎫", "Conciertos & Giras", color, len(concerts))

    for c in concerts:
        prox_num             = c.get("proximity", 4)
        prox_emoji, prox_label = PROXIMITY_LABELS.get(prox_num, ("🟢", "UE"))
        rows += _card_open(color)
        # ── Info siempre visible ──────────────────────────────────────────────
        rows += f"""
<div style="margin-bottom: 8px;">
  {_tag(prox_emoji + " " + prox_label, color)}
  {_tag(c.get("source",""), COLORS['text_muted'])}
</div>
<div style="font-family: Georgia, serif; font-size: 17px; font-weight: bold;
  color: {COLORS['text']}; margin-bottom: 4px;">{_e(c.get("artist",""))}</div>
<div style="font-size: 12px; color: {COLORS['text_muted']};
  font-family: 'Courier New', monospace;">"""
        if c.get("dates"):     rows += f"📅 {_e(c['dates'])}&nbsp;&nbsp;"
        if c.get("locations"): rows += f"📍 {_e(c['locations'])}"
        rows += "</div>"
        # ── Sección desplegable ───────────────────────────────────────────────
        details_html = ""
        if c.get("event"):
            details_html += f"""<div style="font-size: 13px; color: {color};
  font-style: italic; margin-bottom: 8px;">{_e(c['event'])}</div>"""
        if c.get("venue") or c.get("price"):
            details_html += f"""<div style="font-size: 12px; color: {COLORS['text_muted']};
  font-family: 'Courier New', monospace; margin-bottom: 8px;">"""
            if c.get("venue"): details_html += f"🏟️ {_e(c['venue'])}&nbsp;&nbsp;"
            if c.get("price"): details_html += f"🎟️ {_e(c['price'])}"
            details_html += "</div>"
        if c.get("summary"):
            details_html += f"""<div style="font-size: 13px; color: {COLORS['text']};
  line-height: 1.6; margin-bottom: 4px;">{_e(c['summary'])}</div>"""
        details_html += _link_button(c.get("url",""), "Ver evento", color)
        rows += _secondary(details_html, color)
        rows += _card_close()

    return rows


# ─── Bloque 2: Lanzamientos ───────────────────────────────────────────────────

def _render_releases(releases: list[dict]) -> str:
    if not releases:
        return _empty_block("No se encontraron lanzamientos esta semana.", COLORS["releases"])

    color = COLORS["releases"]
    rows  = _section_header("🎵", "Nuevos Lanzamientos", color, len(releases))

    for r in releases:
        rtype_label = str(r.get("type","")).upper()
        rows += _card_open(color)
        rows += f"""
<div style="margin-bottom: 8px;">
  {_tag(rtype_label, color)}
  {_tag(r.get("source",""), COLORS['text_muted'])}
  {_tag(r.get("release_date",""), COLORS['text_muted'])}
</div>
<div style="font-family: Georgia, serif; font-size: 17px; font-weight: bold;
  color: {COLORS['text']}; margin-bottom: 2px;">{_e(r.get("title",""))}</div>
<div style="font-size: 12px; color: {color}; letter-spacing: 1px;
  text-transform: uppercase; font-family: 'Courier New', monospace;">{_e(r.get("artist",""))}</div>
"""
        details_html = ""
        if r.get("summary"):
            details_html += f"""<div style="font-size: 13px; color: {COLORS['text']};
  line-height: 1.6; margin-bottom: 4px;">{_e(r['summary'])}</div>"""
        details_html += _link_button(r.get("url",""), "Escuchar", color)
        rows += _secondary(details_html, color)
        rows += _card_close()

    return rows


# ─── Bloque 3: Descubrimientos ────────────────────────────────────────────────

def _render_discoveries(discoveries: list[dict]) -> str:
    if not discoveries:
        return _empty_block("Sin recomendaciones esta semana.", COLORS["discoveries"])

    color = COLORS["discoveries"]
    rows  = _section_header("🔭", "Descubrimientos", color, len(discoveries))

    for d in discoveries:
        rows += _card_open(color)
        rows += f"""
<div style="font-family: Georgia, serif; font-size: 18px; font-weight: bold;
  color: {COLORS['text']}; margin-bottom: 6px;">{_e(d.get("name",""))}</div>
"""
        if d.get("similar_to"):
            rows += f"""<div style="font-size: 11px; color: {color}; letter-spacing: 1.5px;
  text-transform: uppercase; font-family: 'Courier New', monospace;">
  Similar a {_e(d['similar_to'])}</div>"""
        details_html = ""
        if d.get("reason"):
            details_html += f"""<div style="font-size: 13px; color: {COLORS['text']};
  line-height: 1.6; font-style: italic; margin-bottom: 4px;">"{_e(d['reason'])}"</div>"""
        details_html += _link_button(d.get("url",""), "Descubrir", color)
        rows += _secondary(details_html, color)
        rows += _card_close()

    return rows


# ─── Bloque 4: Candidatos locales Zaragoza ────────────────────────────────────

def _render_local_candidates(local_candidates: list[dict]) -> str:
    if not local_candidates:
        return _empty_block(
            "No se encontraron candidatos locales en Zaragoza esta semana.",
            COLORS["local_candidates"],
        )

    color = COLORS["local_candidates"]
    rows  = _section_header("📍", "Candidatos Locales en Zaragoza", color, len(local_candidates))

    for item in local_candidates:
        date     = item.get("date","") or item.get("dates","")
        is_known = item.get("is_known", False)
        bg       = "#2b1a1a" if is_known else None  # fondo coral tenue para artistas seguidos
        rows += _card_open(color, bg=bg)
        rows += f"""
<div style="margin-bottom: 8px;">
  {_tag("📍 Zaragoza", color)}
  {_tag(item.get("venue",""), COLORS['text_muted'])}
  {_tag(item.get("source",""), COLORS['text_muted'])}
  {_tag("✓ Artista que sigues", color) if is_known else ""}
</div>
<div style="font-family: Georgia, serif; font-size: 18px; font-weight: bold;
  color: {COLORS['text']}; margin-bottom: 4px;">{_e(item.get("artist",""))}</div>
"""
        # fecha siempre visible
        if date:
            rows += f"""<div style="font-size: 12px; color: {COLORS['text_muted']};
  font-family: 'Courier New', monospace;">📅 {_e(date)}</div>"""
        # sección desplegable
        details_html = ""
        event = item.get("event","")
        if event and event != item.get("artist",""):
            details_html += f"""<div style="font-size: 13px; color: {color};
  font-style: italic; margin-bottom: 8px;">{_e(event)}</div>"""
        if item.get("venue"):
            details_html += f"""<div style="font-size: 12px; color: {COLORS['text_muted']};
  font-family: 'Courier New', monospace; margin-bottom: 8px;">🏟️ {_e(item['venue'])}</div>"""
        if item.get("reason"):
            details_html += f"""<div style="font-size: 13px; color: {COLORS['text']};
  line-height: 1.6; margin-bottom: 4px;">{_e(item['reason'])}</div>"""
        details_html += _link_button(item.get("url",""), "Ver candidato", color)
        rows += _secondary(details_html, color)
        rows += _card_close()

    return rows


# ─── Email completo ───────────────────────────────────────────────────────────

def build_email_html(data: dict, artists: list[str], genres: list[str]) -> str:
    concerts         = data.get("concerts",         [])
    releases         = data.get("releases",         [])
    discoveries      = data.get("discoveries",      [])
    local_candidates = data.get("local_candidates", [])

    date_str            = datetime.now().strftime("%d %b %Y").upper()
    top_artists_preview = ", ".join(artists[:8])
    if len(artists) > 8:
        top_artists_preview += f" +{len(artists) - 8} más"

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CarrotBot — Resumen Musical</title>
</head>
<body style="margin:0;padding:0;background-color:{COLORS['bg']};
  font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:{COLORS['text']};">

<table width="100%" cellpadding="0" cellspacing="0"
  style="background:{COLORS['bg']};position:relative;">
{CARROT_PATTERN}
<tr><td align="center" style="padding:32px 16px;">

<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- HEADER -->
  <tr><td style="background:{COLORS['surface2']};border-radius:8px 8px 0 0;
    padding:32px 40px 28px;border-bottom:1px solid {COLORS['border']};">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td>
        <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:4px;
          text-transform:uppercase;color:{COLORS['text_muted']};margin-bottom:8px;">
          Edición semanal · {_e(date_str)}</div>
        <div style="font-family:Georgia,serif;font-size:32px;font-weight:bold;
          color:{COLORS['text']};letter-spacing:-0.5px;">🥕 CarrotBot</div>
        <div style="font-size:13px;color:{COLORS['text_muted']};margin-top:6px;">
          Tu radar musical personalizado</div>
      </td>
      <td align="right" valign="top">
        <div style="font-family:'Courier New',monospace;font-size:10px;
          color:{COLORS['text_muted']};text-align:right;line-height:1.8;">
          <span style="color:{COLORS['concerts']};">■</span> {len(concerts)} conciertos<br>
          <span style="color:{COLORS['releases']};">■</span> {len(releases)} lanzamientos<br>
          <span style="color:{COLORS['discoveries']};">■</span> {len(discoveries)} descubrimientos<br>
          <span style="color:{COLORS['local_candidates']};">■</span> {len(local_candidates)} locales
        </div>
      </td>
    </tr></table>
  </td></tr>

  <!-- PERFIL STRIP -->
  <tr><td style="background:{COLORS['surface2']};padding:12px 40px;
    border-bottom:1px solid {COLORS['border']};">
    <span style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;
      text-transform:uppercase;color:{COLORS['text_muted']};">Siguiendo · </span>
    <span style="font-size:12px;color:{COLORS['text_muted']};font-style:italic;">
      {_e(top_artists_preview)}</span>
  </td></tr>

  <!-- CONTENIDO -->
  <tr><td style="background:rgba(15,15,15,0.92);padding:8px 40px 32px;">
    <table width="100%" cellpadding="0" cellspacing="0">
      {_render_concerts(concerts)}
      {_render_local_candidates(local_candidates)}
      {_render_releases(releases)}
      {_render_discoveries(discoveries)}
    </table>
  </td></tr>

  <!-- FOOTER -->
  <tr><td style="background:{COLORS['surface2']};border-radius:0 0 8px 8px;
    padding:20px 40px;border-top:1px solid {COLORS['border']};">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td><div style="font-family:'Courier New',monospace;font-size:10px;
        letter-spacing:2px;text-transform:uppercase;color:{COLORS['text_muted']};">
        🥕 CarrotBot · Generado automáticamente</div></td>
      <td align="right"><div style="font-family:'Courier New',monospace;font-size:10px;
        color:{COLORS['text_muted']};">{len(artists)} artistas · {len(genres)} géneros</div></td>
    </tr></table>
  </td></tr>

</table>
</td></tr></table>
</body>
</html>
"""