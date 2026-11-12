"""Classificazione PROVVISORIA dei contenuti importati (musica / personale / incerto) dalle didascalie.

Regole:
- usa la corsia leggera (dati pubblici: didascalie di post già pubblici);
- il risultato è un'IPOTESI, marcata nelle note; nulla di "verificato";
- se l'IA è incerta o la risposta non è valida, il contenuto resta 'da_classificare' (decide il proprietario);
- 'personale' => stato 'personale_non_gestito': l'agente non lo tocca mai.
"""
import json
import re
import sys

from . import config as cfgmod
from .agent import Agent
from .ai import Ai, AiError
from .db import Db

AMBITO_PREDEFINITO = ("musica: cover, canto, concerti, prove, band, strumenti. Un reel o un video il cui testo cita un titolo di "
                      "canzone, un artista o è solo il titolo di un brano è pertinente")

ISTRUZIONE = (
    "Classifica ogni post Instagram dell'account. Per ognuno rispondi con un oggetto JSON "
    "con chiavi: id (numero dato), categoria ('musica' = pertinente all'attività dell'account: {ambito}; "
    "'personale' = vita privata, animali, paesaggi, famiglia, senza legame con l'attività; 'incerto' se non sei sicuro), "
    "canzone (titolo se è chiaramente citato, altrimenti null), artista_originale (se chiaramente citato, altrimenti null). "
    "Usa 'personale' solo se è chiaramente estraneo all'attività. "
    "Se non c'è modo di capirlo dal testo, 'incerto'. "
    "Non inventare titoli o artisti. Rispondi SOLO con un array JSON, nessun altro testo."
)


def istruzione(profile: dict = None) -> str:
    """L'ambito dell'account (campo `ambito` del profilo) dice cosa conta come pertinente."""
    ambito = ((profile or {}).get("ambito") or "").strip() or AMBITO_PREDEFINITO
    return ISTRUZIONE.replace("{ambito}", ambito)


def parse_answer(text: str):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    return [d for d in data if isinstance(d, dict) and isinstance(d.get("id"), int)]


def classify_batch(db: Db, agent: Agent, batch_size: int = 15, seen: set = None) -> int:
    """`seen`: id già provati in questa esecuzione (così un 'incerto' non blocca il ciclo)."""
    seen = set() if seen is None else seen
    rows = db.content_to_classify(batch_size, exclude=seen)
    if not rows:
        return 0
    seen.update(r[0] for r in rows)
    payload = "\n".join(
        f"[{cid}] ({mtype}, {(pub or '')[:10]}) " + (cap or "(nessuna didascalia)").replace("\n", " ")[:400]
        for cid, cap, mtype, pub in rows)
    valid_ids = {r[0] for r in rows}
    try:
        out = agent.background(istruzione(getattr(agent, "profile", None)), payload, max_tokens=2500)
    except AiError:
        return -1
    changed = 0
    for d in parse_answer(out):
        cid = d["id"]
        if cid not in valid_ids:
            continue
        cat = d.get("categoria")
        song, artist = d.get("canzone"), d.get("artista_originale")
        song = song if isinstance(song, str) and song.strip() else None
        artist = artist if isinstance(artist, str) and artist.strip() else None
        nota = " | ipotesi_IA da didascalia, non verificata"
        if cat == "musica":
            db.content_set_status(cid, "pubblicato", song=song, original_artist=artist, note=nota + " (categoria=musica)")
            changed += 1
        elif cat == "personale":
            db.content_set_status(cid, "personale_non_gestito", note=nota + " (categoria=personale)")
            changed += 1
        # 'incerto' o altro: resta da_classificare
    return changed


def classify_pending(db: Db, agent: Agent, max_calls: int = 10) -> dict:
    """Prova a classificare TUTTI i contenuti ancora 'da_classificare' (anche quelli rimasti incerti nei giorni scorsi).
    Ipotesi dell'IA marcata nelle note; gli incerti restano bloccati. Salva un riepilogo (kv 'classif:ultimo') che il bot
    conosce e può riferire al proprietario, così può correggere con archivio_classifica."""
    import datetime as dt
    ids = [r[0] for r in db.content_to_classify(1000)]
    if not ids:
        return {}
    seen, errore = set(), False
    for _ in range(max_calls):
        if not db.content_to_classify(1, exclude=seen):
            break
        if classify_batch(db, agent, seen=seen) < 0:
            errore = True
            break
    q = ",".join("?" * len(ids))
    rows = db._x(f"SELECT status,COUNT(*) FROM content_items WHERE id IN ({q}) GROUP BY status", ids).fetchall()
    st = dict(rows)
    out = {"musicali": st.get("pubblicato", 0), "personali": st.get("personale_non_gestito", 0),
           "incerti": st.get("da_classificare", 0)}
    if errore:
        out["errore"] = "IA non raggiungibile"
    db.set("classif:ultimo", json.dumps({"data": dt.datetime.now().strftime("%d/%m %H:%M"), **out}, ensure_ascii=False))
    db.audit("sistema", "classificazione_automatica", json.dumps(out, ensure_ascii=False))
    return out


def main() -> int:
    cfg = cfgmod.load()
    db = Db(cfg.data_dir)
    agent = Agent(Ai(cfg.ai_base_url, cfg.ai_api_key, timeout=180), cfg, db)
    seen = set()
    for _ in range(40):  # tetto di sicurezza: max 40 chiamate IA
        if not db.content_to_classify(1, exclude=seen):
            break
        n = classify_batch(db, agent, seen=seen)
        if n < 0:
            print("IA non raggiungibile: mi fermo")
            return 1
        print(f"provati finora: {len(seen)} | archivio: {db.content_summary()}", flush=True)
    print("archivio:", db.content_summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
