"""Da Markdown (come scrive il modello) al HTML ristretto di Telegram. Solo libreria standard.

Telegram non capisce titoli, tabelle ed elenchi Markdown: li converto in grassetto, righe semplici e testo a
larghezza fissa. Se qualcosa va storto chi chiama ripiega sul testo semplice.
"""
import html
import re

_FENCE = re.compile(r"^```")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
MAX_PRE_WIDTH = 40  # oltre questa larghezza una tabella non sta sul telefono: la trasformo in righe


def _inline(s: str) -> str:
    """s è già 'escapato' per HTML."""
    codes = []

    def keep(m):
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"
    s = re.sub(r"`([^`\n]+)`", keep, s)
    s = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def _cells(line: str):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table(rows) -> str:
    data = [_cells(r) for r in rows if not _TABLE_SEP.match(r)]
    if not data:
        return ""
    n = max(len(r) for r in data)
    data = [r + [""] * (n - len(r)) for r in data]
    plain = [[re.sub(r"[*_`]", "", c) for c in r] for r in data]
    widths = [max(len(r[i]) for r in plain) for i in range(n)]
    if sum(widths) + 3 * (n - 1) <= MAX_PRE_WIDTH:
        lines = [" | ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in plain]
        lines.insert(1, "-+-".join("-" * w for w in widths))
        return "<pre>" + html.escape("\n".join(lines)) + "</pre>"
    out = []
    head = plain[0]
    for r in plain[1:]:
        out.append("• <b>" + html.escape(r[0]) + "</b>")
        for h, c in zip(head[1:], r[1:]):
            if c:
                out.append(f"   {html.escape(h)}: {html.escape(c)}")
    return "\n".join(out)


def md_to_html(text: str) -> str:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if _FENCE.match(ln.strip()):
            buf = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i].strip()):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre>" + html.escape("\n".join(buf)) + "</pre>")
            continue
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        i += 1
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", ln)
        if m:
            out.append("<b>" + _inline(html.escape(m.group(2))) + "</b>")
            continue
        if re.match(r"^\s*([-*_])\1{2,}\s*$", ln):
            out.append("──────────")
            continue
        m = re.match(r"^(\s*)[-*+]\s+(.*)$", ln)
        if m:
            out.append(m.group(1) + "• " + _inline(html.escape(m.group(2))))
            continue
        m = re.match(r"^\s*>\s?(.*)$", ln)
        if m:
            out.append("▎" + _inline(html.escape(m.group(1))))
            continue
        out.append(_inline(html.escape(ln)))
    return "\n".join(out)
