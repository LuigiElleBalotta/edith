"""Blocco di sicurezza: il manager non tocca MAI contenuti personali o non ancora classificati.

Regola (SECURITY.md): nessuna azione riferita a un contenuto con stato 'personale_non_gestito' o 'da_classificare',
né a un contenuto che non è in archivio. Ogni futura scrittura su Instagram (risposte, pubblicazioni) deve passare
da `require_manageable` prima di essere eseguita, in aggiunta all'approvazione del proprietario.
"""
import re

BLOCKED = ("personale_non_gestito", "da_classificare")


class Blocked(Exception):
    pass


def content_for_ref(db, ref: str):
    """Cerca il contenuto in archivio da link Instagram o id numerico. Ritorna (id, stato) oppure None."""
    ref = (ref or "").strip()
    if not ref:
        return None
    if ref.isdigit():
        row = db._x("SELECT id,status FROM content_items WHERE notes LIKE ? LIMIT 1", (f"%instagram_id={ref}%",)).fetchone()
    else:
        base = ref.split("?")[0].rstrip("/")
        row = db._x("SELECT id,status FROM content_items WHERE original_url IN (?,?,?) LIMIT 1",
                    (ref, base, base + "/")).fetchone()
    return (row[0], row[1]) if row else None


def require_manageable(db, ref: str) -> int:
    """Ritorna l'id del contenuto se è musicale ('pubblicato' o altri stati gestibili); altrimenti Blocked."""
    found = content_for_ref(db, ref)
    if not found:
        raise Blocked("contenuto non presente in archivio: non lo tocco")
    cid, status = found
    if status in BLOCKED:
        raise Blocked("contenuto personale o non ancora classificato: non lo tocco")
    return cid


def ref_from_text(text: str):
    m = re.search(r"https?://(?:www\.)?instagram\.com/[^\s)]+", text or "")
    return m.group(0) if m else None
