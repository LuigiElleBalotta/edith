"""Grafici: dati scelti dall'IA, disegno fatto da codice nostro (mai HTML/SVG scritto dal modello).

Produce un SVG pulito (solo forme e testo, tutto 'escapato'); l'immagine PNG la ottiene il browser interno.
Tipi: "barre" (verticali, o orizzontali se le etichette sono lunghe), "barre_orizzontali", "linea".
"""
import html

W, H = 900, 560
BG, FG, MUTED, GRID = "#14161c", "#f2f3f5", "#9aa0ac", "#2a2e38"
COLORS = ["#6c8cff", "#ff5a7a", "#35d0a0"]
MAX_POINTS = 40
MAX_SERIES = 3


class ChartError(Exception):
    pass


def _num(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ChartError("i valori devono essere numeri")
    if x != x or x in (float("inf"), float("-inf")):
        raise ChartError("valore non valido")
    return x


def fmt(x: float) -> str:
    """Numero all'italiana: 12101 -> 12.101, 0.65 -> 0,65."""
    if abs(x) >= 100 or x == int(x):
        s = f"{x:,.0f}"
    elif abs(x) >= 10:
        s = f"{x:,.1f}"
    else:
        s = f"{x:,.2f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    mag = 10 ** (len(str(int(v))) - 1) if v >= 1 else 1.0
    if v < 1:
        return 1.0
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


def _t(s, limit=60) -> str:
    return html.escape(str(s)[:limit])


def _text(x, y, s, size=16, fill=FG, anchor="start", weight="normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{s}</text>')


def validate(spec: dict):
    tipo = spec.get("tipo", "barre")
    if tipo not in ("barre", "barre_orizzontali", "linea"):
        raise ChartError("tipo non valido: usa barre, barre_orizzontali o linea")
    labels = [str(x) for x in (spec.get("etichette") or [])]
    series = spec.get("serie") or []
    if not labels or not series:
        raise ChartError("servono etichette e almeno una serie di valori")
    if len(labels) > MAX_POINTS or len(series) > MAX_SERIES:
        raise ChartError(f"massimo {MAX_POINTS} punti e {MAX_SERIES} serie")
    clean = []
    for s in series:
        vals = [_num(v) for v in (s.get("valori") or [])]
        if len(vals) != len(labels):
            raise ChartError("ogni serie deve avere tanti valori quante sono le etichette")
        clean.append((str(s.get("nome") or ""), vals))
    return tipo, labels, clean


def render_svg(spec: dict) -> str:
    tipo, labels, series = validate(spec)
    if tipo == "barre" and (max(len(l) for l in labels) > 11 or len(labels) > 8) and len(series) == 1:
        tipo = "barre_orizzontali"
    title = _t(spec.get("titolo") or "", 80)
    sub = _t(spec.get("sottotitolo") or "", 110)
    unit = _t(spec.get("unita") or "", 30)
    allv = [v for _, vs in series for v in vs]
    vmax = nice_max(max(allv + [0]))
    vmin = min(allv + [0])
    if vmin < 0:
        raise ChartError("valori negativi non supportati")
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             f'font-family="DejaVu Sans, Liberation Sans, Arial, sans-serif">',
             f'<rect width="{W}" height="{H}" rx="18" fill="{BG}"/>',
             _text(40, 58, title, 28, FG, weight="bold")]
    if sub:
        parts.append(_text(40, 88, sub, 16, MUTED))
    top = 120
    if len(series) > 1:  # legenda
        x = 40
        for i, (name, _) in enumerate(series):
            parts.append(f'<rect x="{x}" y="{top - 6}" width="14" height="14" rx="3" fill="{COLORS[i]}"/>')
            parts.append(_text(x + 20, top + 6, _t(name, 22), 15, MUTED))
            x += 40 + 9 * len(name[:22])
        top += 24
    bottom = H - 70
    left, right = 70, W - 40
    if tipo == "barre_orizzontali":
        labw = min(220, 9 * max(len(l[:26]) for l in labels) + 16)
        left = 40 + labw
        n = len(labels)
        slot = (bottom + 30 - top) / n
        k = len(series)
        bh = max(6, min(34, slot * 0.7 / k))
        for g in range(5):
            gx = left + (right - 60 - left) * g / 4
            parts.append(f'<line x1="{gx:.1f}" y1="{top}" x2="{gx:.1f}" y2="{bottom + 30}" stroke="{GRID}"/>')
            parts.append(_text(gx, bottom + 52, fmt(vmax * g / 4), 13, MUTED, "middle"))
        for i, lab in enumerate(labels):
            cy = top + slot * i + slot / 2
            parts.append(_text(left - 12, cy + 5, _t(lab, 26), 15, FG, "end"))
            for j, (_, vs) in enumerate(series):
                y = cy - (bh * k) / 2 + j * bh
                w = (right - 60 - left) * vs[i] / vmax
                parts.append(f'<rect x="{left}" y="{y:.1f}" width="{max(w, 1):.1f}" height="{bh - 3:.1f}" rx="4" fill="{COLORS[j]}"/>')
                parts.append(_text(left + w + 8, y + bh / 2 + 3, fmt(vs[i]), 14, FG))
    else:
        n = len(labels)
        slot = (right - left) / n
        for g in range(5):
            gy = bottom - (bottom - top) * g / 4
            parts.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{right}" y2="{gy:.1f}" stroke="{GRID}"/>')
            parts.append(_text(left - 10, gy + 5, fmt(vmax * g / 4), 13, MUTED, "end"))
        rot = n > 7 or max(len(l) for l in labels) > 9
        for i, lab in enumerate(labels):
            cx = left + slot * i + slot / 2
            if rot:
                parts.append(f'<text x="{cx:.1f}" y="{bottom + 22}" font-size="13" fill="{MUTED}" text-anchor="end" '
                             f'transform="rotate(-35 {cx:.1f} {bottom + 22})">{_t(lab, 16)}</text>')
            else:
                parts.append(_text(cx, bottom + 26, _t(lab, 16), 14, MUTED, "middle"))
        if tipo == "barre":
            k = len(series)
            bw = max(6, min(70, slot * 0.7 / k))
            for i in range(n):
                cx = left + slot * i + slot / 2
                for j, (_, vs) in enumerate(series):
                    h = (bottom - top) * vs[i] / vmax
                    x = cx - (bw * k) / 2 + j * bw
                    parts.append(f'<rect x="{x:.1f}" y="{bottom - h:.1f}" width="{bw - 3:.1f}" height="{max(h, 1):.1f}" rx="4" fill="{COLORS[j]}"/>')
                    if n <= 12:
                        parts.append(_text(x + (bw - 3) / 2, bottom - h - 7, fmt(vs[i]), 12, FG, "middle"))
        else:  # linea
            for j, (_, vs) in enumerate(series):
                pts = [(left + slot * i + slot / 2, bottom - (bottom - top) * v / vmax) for i, v in enumerate(vs)]
                parts.append('<polyline fill="none" stroke="%s" stroke-width="3.5" stroke-linejoin="round" points="%s"/>'
                             % (COLORS[j], " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)))
                for (x, y), v in zip(pts, vs):
                    parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{COLORS[j]}"/>')
                    if n <= 12:
                        parts.append(_text(x, y - 11, fmt(v), 12, FG, "middle"))
    if unit:  # unità di misura una sola volta, sopra gli assi
        parts.append(_text(left if tipo != "barre_orizzontali" else 40, top - 14 if len(series) == 1 else top - 2,
                           unit, 13, MUTED))
    parts.append(_text(W - 40, 36, "EDITH", 12, "#4a4f5c", "end"))
    parts.append("</svg>")
    return "".join(parts)
