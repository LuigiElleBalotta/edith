"""Registro in memoria: tiene le ultime righe scritte dal programma, per mostrarle nel pannello web (come `./manager logs`).

Non scrive niente su disco. Al momento di mostrare le righe, i valori segreti noti (token, chiavi, password) vengono oscurati.
"""
import collections
import re
import sys
import threading

MAX_LINES = 400
_lines = collections.deque(maxlen=MAX_LINES)
_partial = {"s": ""}
_lock = threading.Lock()
# oscuramento generico: codici dei bot Telegram negli indirizzi e valori dopo Bearer/token/key
_PATTERNS = (re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"),
             re.compile(r"((?:Bearer|access_token=|token=|key=)\s*)[A-Za-z0-9._~+/=-]{12,}", re.I))


class _Tee:
    def __init__(self, real):
        self._real = real

    def write(self, data):
        n = self._real.write(data)
        try:
            with _lock:
                buf = _partial["s"] + (data if isinstance(data, str) else str(data))
                *done, _partial["s"] = buf.split("\n")
                _partial["s"] = _partial["s"][-2000:]
                for ln in done:
                    _lines.append(ln[:2000])
        except Exception:
            pass
        return n

    def __getattr__(self, name):
        return getattr(self._real, name)


def install():
    """Mette il registro in ascolto su stdout e stderr (una volta sola)."""
    for name in ("stdout", "stderr"):
        cur = getattr(sys, name)
        if not isinstance(cur, _Tee):
            setattr(sys, name, _Tee(cur))


def text(secrets=(), last: int = 200) -> str:
    """Ultime righe, con i valori segreti sostituiti da ***."""
    with _lock:
        out = "\n".join(list(_lines)[-last:])
    return mask(out, secrets)


def mask(text: str, secrets=()) -> str:
    """Oscura i valori segreti noti e i modelli comuni (codice bot Telegram, Bearer/token/key)."""
    out = text or ""
    for v in sorted((x for x in secrets if x), key=len, reverse=True):
        out = out.replace(v, "***")
    out = _PATTERNS[0].sub("bot***", out)
    out = _PATTERNS[1].sub(r"\1***", out)
    return out
