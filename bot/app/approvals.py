"""Approvazioni: il manager PROPONE, il proprietario decide con un tocco. Nulla parte senza un "Approva".

Oggi i tipi sono bozze (testi): non c'è nessun invio automatico. Quando si aggiungeranno azioni vere
(risposte ai commenti, pubblicazioni) dovranno passare da guard.require_manageable e da questo flusso.
"""
import json

from .guard import Blocked, require_manageable

KINDS = {
    "bozza_post": "Bozza di post/didascalia",
    "bozza_risposta_commento": "Bozza di risposta a un commento",
    "bozza_candidatura": "Bozza di candidatura / messaggio professionale",
    "idea_contenuto": "Idea di contenuto",
    "modifica_kb": "Modifica all'archivio",
    "invio_mail": "Invio di una mail",
    "modifica_profilo": "Nuova regola per il manager",
    "nuova_estensione": "Nuova estensione",
    "modifica_estensione": "Modifica a un'estensione",
}
HOOKS = {}  # tipo -> funzione(db, approvazione) chiamata DOPO l'approvazione; ritorna il messaggio per il proprietario
NO_HOOKS = {}  # tipo -> funzione(db, approvazione, scelta) chiamata quando la proposta NON viene approvata ("no", "mod", "mai")
NEEDS_CONTENT = ("bozza_risposta_commento",)  # tipi legati a un contenuto Instagram: devono essere musicali
CAN_BE_SILENCED = ("modifica_profilo", "nuova_estensione", "modifica_estensione")  # hanno anche «Non riproporre più»
STATUS_LABEL = {"approvata": "✅ Approvata", "rifiutata": "❌ Rifiutata", "da_modificare": "✏️ Da modificare",
                "mai_piu": "🚫 Non la riproporrò più"}


def create(db, kind: str, title: str, text: str, ref: str = "", extra: dict = None) -> int:
    if kind not in KINDS:
        raise ValueError(f"tipo non valido: {', '.join(KINDS)}")
    if not (text or "").strip():
        raise ValueError("serve il testo della bozza")
    content_id = None
    if (kind in NEEDS_CONTENT or ref) and kind != "modifica_kb":
        try:
            content_id = require_manageable(db, ref)
        except Blocked as e:
            raise ValueError(str(e))
    payload = {"titolo": (title or KINDS[kind])[:120], "testo": text[:3000], "riferimento": ref, "content_id": content_id}
    if extra:
        payload["extra"] = extra
    cur = db._x("INSERT INTO approvals(ts,kind,payload,status) VALUES(strftime('%s','now'),?,?,'in_attesa')",
                (kind, json.dumps(payload, ensure_ascii=False)))
    db.audit("manager", "approvazione_proposta", f"id={cur.lastrowid} tipo={kind}")
    return cur.lastrowid


def get(db, aid: int):
    r = db._x("SELECT id,kind,payload,status FROM approvals WHERE id=?", (aid,)).fetchone()
    return {"id": r[0], "kind": r[1], "status": r[3], **json.loads(r[2])} if r else None


def message(a: dict) -> str:
    return f"📝 **{KINDS[a['kind']]}** (#{a['id']})\n**{a['titolo']}**\n\n{a['testo']}\n\nCosa faccio?"


def keyboard(aid: int, kind: str = "") -> dict:
    rows = [[{"text": "✅ Approva", "callback_data": f"ap:{aid}:ok"},
             {"text": "❌ Rifiuta", "callback_data": f"ap:{aid}:no"},
             {"text": "✏️ Cambia", "callback_data": f"ap:{aid}:mod"}]]
    if kind in CAN_BE_SILENCED:
        rows.append([{"text": "🚫 Non riproporre più", "callback_data": f"ap:{aid}:mai"}])
    return {"inline_keyboard": rows}


def decide(db, aid: int, choice: str):
    """Ritorna (stato_nuovo, messaggio_per_il_proprietario). Una bozza già decisa non si decide due volte."""
    a = get(db, aid)
    if not a:
        return None, "Non trovo questa proposta."
    if a["status"] != "in_attesa":
        return a["status"], f"Questa proposta è già {a['status'].replace('_', ' ')}."
    new = {"ok": "approvata", "no": "rifiutata", "mod": "da_modificare", "mai": "mai_piu"}.get(choice)
    if not new or (choice == "mai" and a["kind"] not in CAN_BE_SILENCED):
        return None, "Scelta non valida."
    db._x("UPDATE approvals SET status=? WHERE id=?", (new, aid))
    db.audit("proprietario", "approvazione_" + new, f"id={aid} tipo={a['kind']}")
    if "Piano 30 giorni" in a["titolo"] and new in ("approvata", "rifiutata"):  # il calendario si aggiorna da solo
        n = db.ped_set_status("proposto", "approvato" if new == "approvata" else "scartato")
        db.audit("sistema", "ped_stato_aggiornato", f"{n} voci -> {'approvato' if new == 'approvata' else 'scartato'}")
    if new != "approvata" and a["kind"] in NO_HOOKS:  # es. la lezione rifiutata si ripropone più avanti; «mai più» no
        try:
            NO_HOOKS[a["kind"]](db, a, choice)
        except Exception as e:
            db.audit("sistema", "approvazione_no_fallita", f"id={aid} {type(e).__name__}")
    if new == "mai_piu":
        db.add_message("user", f"(Il proprietario NON vuole più che tu riproponga la proposta #{aid}: {a['titolo']}. Non riproporla.)")
        return new, "Ok, non la riproporrò più."
    hooks = {**HOOKS, **getattr(db, "hooks", {})}
    if new == "approvata" and a["kind"] in hooks:  # es. modifica all'archivio: si salva solo dopo il tuo ok
        try:
            msg = hooks[a["kind"]](db, a)
        except Exception as e:
            db.audit("sistema", "approvazione_azione_fallita", f"id={aid} {type(e).__name__}")
            msg = f"Approvata, ma non sono riuscito a completarla ({e}). Non è stato cambiato niente."
        db.add_message("user", f"(Il proprietario ha APPROVATO la proposta #{aid}: {a['titolo']}. Esito: {msg})")
        return new, msg
    if new == "approvata":
        # Nessun invio automatico: la bozza resta salvata e pronta all'uso.
        db.add_message("user", f"(Il proprietario ha APPROVATO la proposta #{aid}: {a['titolo']})")
        return new, "Approvata e salvata. Non l'ho pubblicata né inviata: la usi tu quando vuoi (o mi dici come procedere)."
    if new == "rifiutata":
        db.add_message("user", f"(Il proprietario ha RIFIUTATO la proposta #{aid}: {a['titolo']})")
        return new, "Ok, scartata."
    db.add_message("user", f"(Il proprietario vuole MODIFICARE la proposta #{aid}: {a['titolo']}. Chiedigli cosa cambiare.)")
    return new, "Dimmi cosa vuoi cambiare e ti preparo una nuova versione."
