"""Estensioni: funzioni che il bot può costruirsi da solo, sempre DICHIARATIVE e sempre approvate dal proprietario.

Un'estensione è una cartella FUORI dal contenitore (EXTENSIONS_DIR/<account>/<id>/) con un manifest.json:
dati propri (collezioni), strumenti per il bot (sequenze di passi), pagine del pannello, timer e un programma.
Non c'è codice libero: i passi sono pochi e fissi, e ognuno ha le sue difese.

- niente scrittura verso l'esterno: nessun POST, nessun messaggio a terzi; si può solo LEGGERE da domini dichiarati
  e approvati, tenere i PROPRI dati e AVVISARE il proprietario;
- il bot propone, il proprietario approva (Telegram o pannello); il bot non può approvarsi da solo;
- i segreti non stanno nel manifest: sono in account.env e si usano solo come {segreto:chiave} verso un dominio approvato;
- ogni versione approvata si conserva (si può tornare indietro) e i dati non si cancellano mai da soli.
"""
import datetime as dt
import hashlib
import json
import os
import re
import socket
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import approvals

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,23}$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
FIELD_TYPES = ("testo", "testo_lungo", "numero", "si_no", "scelta", "elenco", "data", "segreto")
STEP_TYPES = ("leggi_righe", "scrivi_riga", "aggiorna_riga", "leggi_pagina", "leggi_api", "leggi_dati",
              "chiedi_al_modello", "ricorda_tra", "ricorda_il")
EFFECTS = ("leggere", "dati_propri", "avvisa_proprietario")
EFFECT_OF_STEP = {"leggi_pagina": "leggere", "leggi_api": "leggere", "scrivi_riga": "dati_propri", "aggiorna_riga": "dati_propri",
                  "ricorda_tra": "avvisa_proprietario", "ricorda_il": "avvisa_proprietario"}
EFFECT_TEXT = {"leggere": "leggere pagine e dati da siti che hai approvato (solo lettura)",
               "dati_propri": "tenere e modificare i SUOI dati (non tocca altro)",
               "avvisa_proprietario": "mandarti un messaggio su Telegram a un'ora precisa"}
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
TOP_KEYS = {"versione", "id", "nome", "descrizione", "effetti", "domini", "impostazioni", "collezioni", "strumenti", "pagine", "programma"}
STEP_KEYS = {"leggi_righe": {"collezione", "cerca", "limite"}, "scrivi_riga": {"collezione"}, "aggiorna_riga": {"collezione"},
             "leggi_pagina": {"url"}, "leggi_api": {"url", "estrai", "intestazioni"}, "leggi_dati": {"nome"},
             "chiedi_al_modello": {"istruzione"}, "ricorda_tra": {"minuti", "messaggio"}, "ricorda_il": {"quando", "messaggio"}}
SHOW_TYPES = ("tabella", "tabella_modificabile", "lista", "testo")
# letture in sola lettura dei dati dell'account, con nome (l'estensione non scrive mai SQL)
DATA_QUERIES = {
    "fatti": lambda db: db.facts_list(30),
    "contatti": lambda db: db.contacts_list(limit=30),
    "opportunita": lambda db: db.opportunities_list(limit=30),
    "appunti": lambda db: db.notes_list(limit=30),
    "piano": lambda db: db.ped_list(from_day=dt.date.today().isoformat()),
}
# protezioni tecniche (NON sono quote: servono a non bloccare il bot)
TIMEOUT = 25
MAX_BYTES = 1_500_000
MAX_TEXT = 40000
MAX_FIELD = 2000
MAX_LONG = 20000
MAX_ROWS_READ = 200
HOPS = 4


class ExtError(Exception):
    pass


# ------------------------------------------------------------------ campi e valori
def _fields(lst, where, allow_secret=True):
    if not isinstance(lst, list):
        raise ExtError(f"{where}: serve un elenco di campi")
    seen, out = set(), []
    for f in lst:
        if not isinstance(f, dict):
            raise ExtError(f"{where}: ogni campo è un oggetto")
        extra = set(f) - {"chiave", "tipo", "etichetta", "aiuto", "esempio", "predefinito", "opzioni", "obbligatorio"}
        if extra:
            raise ExtError(f"{where}: campo con voci sconosciute: {', '.join(sorted(extra))}")
        k, t = f.get("chiave"), f.get("tipo")
        if not isinstance(k, str) or not KEY_RE.match(k):
            raise ExtError(f"{where}: «chiave» non valida (minuscole, numeri, _)")
        if k in seen:
            raise ExtError(f"{where}: chiave doppia «{k}»")
        seen.add(k)
        if t not in FIELD_TYPES or (t == "segreto" and not allow_secret):
            raise ExtError(f"{where}: tipo non valido per «{k}» ({', '.join(x for x in FIELD_TYPES if allow_secret or x != 'segreto')})")
        for txt in ("etichetta", "aiuto", "esempio"):
            if txt in f and (not isinstance(f[txt], str) or len(f[txt]) > 300):
                raise ExtError(f"{where}: «{txt}» di «{k}» deve essere un testo breve")
        if t == "scelta" and not (isinstance(f.get("opzioni"), list) and f["opzioni"] and all(isinstance(o, str) and o for o in f["opzioni"])):
            raise ExtError(f"{where}: «{k}» è una scelta: servono le «opzioni»")
        out.append(f)
    return out


def coerce(field: dict, raw):
    """Porta un valore (testo di un modulo o valore JSON) al tipo del campo. Alza ExtError in italiano."""
    k, t = field["chiave"], field["tipo"]
    nome = field.get("etichetta") or k
    empty = raw is None or (isinstance(raw, str) and not raw.strip()) or (isinstance(raw, list) and not raw)
    if empty:
        if "predefinito" in field:
            return field["predefinito"]
        if field.get("obbligatorio"):
            raise ExtError(f"«{nome}» è obbligatorio")
        return [] if t == "elenco" else (False if t == "si_no" else None)
    if t in ("testo", "testo_lungo"):
        v = str(raw).strip()
        lim = MAX_LONG if t == "testo_lungo" else MAX_FIELD
        if len(v) > lim:
            raise ExtError(f"«{nome}» è troppo lungo (massimo {lim} caratteri)")
        return v
    if t == "numero":
        try:
            n = float(str(raw).replace(",", ".").strip())
        except ValueError:
            raise ExtError(f"«{nome}» deve essere un numero")
        if n != n or n in (float("inf"), float("-inf")):
            raise ExtError(f"«{nome}» deve essere un numero")
        return int(n) if n == int(n) else n
    if t == "si_no":
        return raw is True or str(raw).strip().lower() in ("1", "si", "sì", "on", "true", "yes")
    if t == "scelta":
        v = str(raw).strip()
        if v not in field["opzioni"]:
            raise ExtError(f"«{nome}»: scegli tra {', '.join(field['opzioni'])}")
        return v
    if t == "elenco":
        items = raw if isinstance(raw, list) else str(raw).replace("\r", "").split("\n")
        out = [str(i).strip() for i in items if str(i).strip()]
        if any(len(i) > 300 for i in out):
            raise ExtError(f"«{nome}»: ogni voce al massimo 300 caratteri")
        return out
    if t == "data":
        try:
            return dt.date.fromisoformat(str(raw).strip()).isoformat()
        except ValueError:
            raise ExtError(f"«{nome}» deve essere una data AAAA-MM-GG")
    raise ExtError(f"«{nome}»: tipo non gestito")


def coerce_row(fields, form: dict, partial: bool = False) -> dict:
    out = {}
    for f in fields:
        if partial and f["chiave"] not in form:
            continue
        out[f["chiave"]] = coerce(f, form.get(f["chiave"]))
    return out


# ------------------------------------------------------------------ validazione del manifest
_TOKEN = re.compile(r"\{([^{}]*)\}")


def _check_template(s, names, secrets, where, allow_secret=False):
    for tok in _TOKEN.findall(s):
        if tok.startswith("segreto:"):
            if not allow_secret or tok[8:] not in secrets:
                raise ExtError(f"{where}: «{{{tok}}}» non è ammesso qui o il segreto non esiste")
        elif tok not in names:
            raise ExtError(f"{where}: «{{{tok}}}» non è un parametro né un'impostazione")


def _host_ok(host: str, domini) -> bool:
    return any(host == d or host.endswith("." + d) for d in domini)


def validate_manifest(m) -> dict:
    """Controlla un manifest. Ritorna il manifest (invariato) o alza ExtError con una frase chiara per chi non è tecnico."""
    if not isinstance(m, dict):
        raise ExtError("il manifest deve essere un oggetto JSON")
    extra = set(m) - TOP_KEYS
    if extra:
        raise ExtError(f"voci sconosciute nel manifest: {', '.join(sorted(extra))}")
    if m.get("versione", 1) != 1:
        raise ExtError("versione del formato non supportata (serve 1)")
    if not isinstance(m.get("id"), str) or not ID_RE.match(m["id"]):
        raise ExtError("«id»: minuscole, numeri e _, da 2 a 24 caratteri, deve iniziare con una lettera")
    if not isinstance(m.get("nome"), str) or not (1 <= len(m["nome"]) <= 60):
        raise ExtError("«nome»: un testo breve (massimo 60 caratteri)")
    if not isinstance(m.get("descrizione", ""), str) or len(m.get("descrizione", "")) > 300:
        raise ExtError("«descrizione»: massimo 300 caratteri")
    eff = m.get("effetti", [])
    eff = [eff] if isinstance(eff, str) else eff
    if not isinstance(eff, list) or any(e not in EFFECTS for e in eff):
        raise ExtError(f"«effetti»: solo {', '.join(EFFECTS)}")
    domini = m.get("domini", [])
    if not isinstance(domini, list) or any(not isinstance(d, str) or not HOST_RE.match(d) or "." not in d for d in domini):
        raise ExtError("«domini»: elenco di indirizzi come api.example.org")
    settings = _fields(m.get("impostazioni", []), "impostazioni")
    secrets = {f["chiave"] for f in settings if f["tipo"] == "segreto"}
    colls = {}
    for c in m.get("collezioni", []):
        if not isinstance(c, dict) or set(c) - {"nome", "campi"} or not isinstance(c.get("nome"), str) or not KEY_RE.match(c["nome"]):
            raise ExtError("collezioni: ognuna ha «nome» e «campi»")
        if c["nome"] in colls:
            raise ExtError(f"collezione doppia «{c['nome']}»")
        colls[c["nome"]] = _fields(c.get("campi", []), f"collezione «{c['nome']}»", allow_secret=False)
    needed, tools, used_hosts = set(), {}, set()
    for t in m.get("strumenti", []):
        if not isinstance(t, dict) or set(t) - {"nome", "descrizione", "parametri", "passi"}:
            raise ExtError("strumenti: ognuno ha «nome», «descrizione», «parametri», «passi»")
        tn = t.get("nome")
        if not isinstance(tn, str) or not re.match(r"^[a-z][a-z0-9_]{1,29}$", tn) or tn in tools:
            raise ExtError(f"strumento: nome non valido o doppio «{tn}»")
        if not isinstance(t.get("descrizione"), str) or not 1 <= len(t["descrizione"]) <= 300:
            raise ExtError(f"strumento «{tn}»: serve una descrizione breve")
        par = t.get("parametri", [])
        if isinstance(par, str):
            if not par.startswith("collezione:") or par[11:] not in colls:
                raise ExtError(f"strumento «{tn}»: «parametri» punta a una collezione che non c'è")
            par_fields = colls[par[11:]]
        else:
            par_fields = _fields(par, f"strumento «{tn}» parametri", allow_secret=False)
        names = {f["chiave"] for f in par_fields} | {f["chiave"] for f in settings if f["tipo"] != "segreto"}
        passi = t.get("passi")
        if not isinstance(passi, list) or not passi or len(passi) > 20:
            raise ExtError(f"strumento «{tn}»: servono da 1 a 20 passi")
        for p in passi:
            where = f"strumento «{tn}»"
            if not isinstance(p, dict) or p.get("tipo") not in STEP_TYPES:
                raise ExtError(f"{where}: passo non valido (ammessi: {', '.join(STEP_TYPES)})")
            tp = p["tipo"]
            bad = set(p) - STEP_KEYS[tp] - {"tipo"}
            if bad:
                raise ExtError(f"{where}, passo {tp}: voci sconosciute: {', '.join(sorted(bad))}")
            if tp in EFFECT_OF_STEP:
                needed.add(EFFECT_OF_STEP[tp])
            if tp in ("leggi_righe", "scrivi_riga", "aggiorna_riga") and p.get("collezione") not in colls:
                raise ExtError(f"{where}, passo {tp}: la collezione «{p.get('collezione')}» non esiste")
            if tp == "leggi_righe" and "cerca" in p:
                _check_template(str(p["cerca"]), names, secrets, f"{where}, cerca")
            if tp in ("leggi_pagina", "leggi_api"):
                url = p.get("url")
                if not isinstance(url, str) or not url.startswith("https://"):
                    raise ExtError(f"{where}, passo {tp}: l'indirizzo deve iniziare con https://")
                netloc = url.split("/")[2] if url.count("/") >= 2 else ""
                if not netloc or "{" in netloc or "@" in netloc or ":" in netloc:
                    raise ExtError(f"{where}, passo {tp}: il sito (dominio) deve essere scritto per intero, senza variabili, utente o porta")
                host = netloc.lower()
                used_hosts.add(host)
                if not _host_ok(host, domini):
                    raise ExtError(f"{where}: «{host}» non è tra i «domini» dichiarati")
                _check_template(url, names, secrets, f"{where}, url")
                if tp == "leggi_api":
                    ex = p.get("estrai", [])
                    if not isinstance(ex, list) or any(not isinstance(x, str) or not re.match(r"^[A-Za-z0-9_.\-]{1,120}$", x) for x in ex):
                        raise ExtError(f"{where}, leggi_api: «estrai» è un elenco di percorsi come daily.temperature")
                    hd = p.get("intestazioni", {})
                    if not isinstance(hd, dict) or any(not isinstance(k, str) or not re.match(r"^[A-Za-z][A-Za-z0-9-]{0,40}$", k) or not isinstance(v, str) for k, v in hd.items()):
                        raise ExtError(f"{where}, leggi_api: «intestazioni» non valide")
                    for v in hd.values():
                        _check_template(v, names, secrets, f"{where}, intestazioni", allow_secret=True)
            if tp == "leggi_dati" and p.get("nome") not in DATA_QUERIES:
                raise ExtError(f"{where}: «leggi_dati» ammette solo: {', '.join(sorted(DATA_QUERIES))}")
            if tp == "chiedi_al_modello" and (not isinstance(p.get("istruzione"), str) or not 1 <= len(p["istruzione"]) <= 1500):
                raise ExtError(f"{where}: «istruzione» è un testo di massimo 1500 caratteri")
            if tp in ("ricorda_tra", "ricorda_il"):
                for k in ("minuti", "quando", "messaggio"):
                    if k in p:
                        _check_template(str(p[k]), names, secrets, f"{where}, {k}")
                if not isinstance(p.get("messaggio"), str) or not 1 <= len(p["messaggio"]) <= 300:
                    raise ExtError(f"{where}: «messaggio» è un testo di massimo 300 caratteri")
                if (tp == "ricorda_tra" and "minuti" not in p) or (tp == "ricorda_il" and "quando" not in p):
                    raise ExtError(f"{where}: manca {'«minuti»' if tp == 'ricorda_tra' else '«quando»'}")
        tools[tn] = par_fields
    if not set(eff) >= needed:
        raise ExtError(f"«effetti» deve dichiarare anche: {', '.join(sorted(needed - set(eff)))}")
    if used_hosts == set() and domini:
        raise ExtError("«domini» è dichiarato ma nessun passo lo usa: toglilo")
    for pg in m.get("pagine", []):
        if not isinstance(pg, dict) or set(pg) - {"titolo", "mostra"} or not isinstance(pg.get("titolo"), str):
            raise ExtError("pagine: ognuna ha «titolo» e «mostra»")
        for el in pg.get("mostra", []):
            if not isinstance(el, dict) or el.get("tipo") not in SHOW_TYPES:
                raise ExtError(f"pagine: elemento non valido (ammessi: {', '.join(SHOW_TYPES)})")
            bad = set(el) - {"tipo", "collezione", "colonne", "campo", "testo", "titolo", "modulo"}
            if bad:
                raise ExtError(f"pagine: voci sconosciute: {', '.join(sorted(bad))}")
            if el["tipo"] in ("tabella", "tabella_modificabile", "lista"):
                if el.get("collezione") not in colls:
                    raise ExtError(f"pagine: la collezione «{el.get('collezione')}» non esiste")
                keys = {f["chiave"] for f in colls[el["collezione"]]}
                cols = el.get("colonne") or ([el["campo"]] if el.get("campo") else [])
                if not cols or any(c not in keys for c in cols):
                    raise ExtError("pagine: «colonne» (o «campo») devono essere campi della collezione")
            if el["tipo"] == "testo" and (not isinstance(el.get("testo"), str) or len(el["testo"]) > 2000):
                raise ExtError("pagine: «testo» è un testo di massimo 2000 caratteri")
    pr = m.get("programma")
    if pr is not None:
        if not isinstance(pr, dict) or set(pr) - {"strumento", "giorno", "ora", "invia"}:
            raise ExtError("programma: ammessi «strumento», «giorno», «ora», «invia»")
        if pr.get("strumento") not in tools or tools[pr["strumento"]]:
            raise ExtError("programma: «strumento» deve esistere e non avere parametri")
        if pr.get("giorno", "ogni giorno") not in GIORNI + ["ogni giorno"]:
            raise ExtError("programma: «giorno» è «ogni giorno» o un giorno della settimana")
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(pr.get("ora", ""))):
            raise ExtError("programma: «ora» è come 09:30")
    return m


def riassunto(m: dict, vecchio: dict = None) -> str:
    """Riepilogo in italiano semplice per chi deve approvare (Telegram e pannello)."""
    L = [f"🧩 {m['nome']}" + (f" — {m['descrizione']}" if m.get("descrizione") else "")]
    eff = m.get("effetti", [])
    eff = [eff] if isinstance(eff, str) else eff
    L.append("Può: " + ("; ".join(EFFECT_TEXT[e] for e in eff) if eff else "solo rispondere con quello che ha"))
    dom = m.get("domini", [])
    L.append("Si collega a: " + (", ".join(dom) if dom else "nessun sito"))
    colls = m.get("collezioni", [])
    if colls:
        L.append("Dati che tiene: " + "; ".join(f"{c['nome']} ({', '.join(f['chiave'] for f in c['campi'])})" for c in colls))
    if m.get("impostazioni"):
        L.append("Impostazioni nel pannello: " + ", ".join(f.get("etichetta") or f["chiave"] for f in m["impostazioni"]))
    for t in m.get("strumenti", []):
        L.append(f"Strumento per il bot «{t['nome']}»: {t['descrizione']}")
    pr = m.get("programma")
    if pr:
        L.append(f"Parte da solo: {pr.get('giorno', 'ogni giorno')} alle {pr['ora']} (strumento «{pr['strumento']}»)")
    if m.get("pagine"):
        L.append("Pagine nel pannello: " + ", ".join(p["titolo"] for p in m["pagine"]))
    L.append("NON può: pubblicare, scrivere a nessuno, mandare dati fuori, leggere le tue chiavi.")
    if vecchio:
        oe = {e for e in ([vecchio.get("effetti")] if isinstance(vecchio.get("effetti"), str) else vecchio.get("effetti", []))}
        ne = set(eff)
        nd = sorted(set(dom) - set(vecchio.get("domini", [])))
        L.append("— Cambia rispetto alla versione approvata —")
        L.append("⚠️ Nuovi siti: " + ", ".join(nd) if nd else "Siti: invariati")
        L.append(("⚠️ Nuovi permessi: " + ", ".join(sorted(ne - oe))) if ne - oe else "Permessi: invariati")
        a = {t["nome"] for t in m.get("strumenti", [])}
        b = {t["nome"] for t in vecchio.get("strumenti", [])}
        if a - b or b - a:
            L.append(f"Strumenti nuovi: {', '.join(sorted(a - b)) or '-'}; tolti: {', '.join(sorted(b - a)) or '-'}")
    out = "\n".join(L)
    return out if len(out) <= 2900 else out[:2890] + "…"


# ------------------------------------------------------------------ archivio su disco
def _atomic_write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def secret_env_name(ext_id: str, key: str) -> str:
    return f"EXT_{ext_id.upper()}_{key.upper()}"


class ExtStore:
    """Le estensioni di UN account: root/<account>/<id>/ (manifest, versioni, in attesa, dati)."""

    def __init__(self, root: str, slug: str):
        if not re.match(r"^[a-z0-9][a-z0-9_-]{0,40}$", slug or ""):
            raise ExtError("nome account non valido")
        self.dir = os.path.join(root, slug)
        self._lock = threading.Lock()

    def _p(self, ext_id: str, *more) -> str:
        if not ID_RE.match(ext_id or ""):
            raise ExtError("id estensione non valido")
        return os.path.join(self.dir, ext_id, *more)

    def _read(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def ids(self):
        try:
            return sorted(d for d in os.listdir(self.dir) if ID_RE.match(d) and os.path.isdir(os.path.join(self.dir, d)))
        except OSError:
            return []

    def manifest(self, ext_id):
        return self._read(self._p(ext_id, "manifest.json"))

    def pending(self, ext_id):
        return self._read(self._p(ext_id, "in_attesa", "manifest.json"))

    def state(self, ext_id) -> dict:
        s = self._read(self._p(ext_id, "stato.json")) or {}
        return {"attiva": bool(s.get("attiva", False)), "versione": int(s.get("versione", 0))}

    def _set_state(self, ext_id, attiva=None, versione=None):
        s = self.state(ext_id)
        if attiva is not None:
            s["attiva"] = bool(attiva)
        if versione is not None:
            s["versione"] = int(versione)
        _atomic_write(self._p(ext_id, "stato.json"), json.dumps(s))

    def versions(self, ext_id):
        try:
            return sorted(int(f[1:-5]) for f in os.listdir(self._p(ext_id, "versioni")) if re.match(r"^v\d+\.json$", f))
        except OSError:
            return []

    def propose(self, m: dict) -> dict:
        validate_manifest(m)
        _atomic_write(self._p(m["id"], "in_attesa", "manifest.json"), json.dumps(m, ensure_ascii=False, indent=2))
        return m

    def reject(self, ext_id):
        try:
            os.remove(self._p(ext_id, "in_attesa", "manifest.json"))
        except OSError:
            pass

    def approve(self, ext_id) -> int:
        """Porta la proposta in attesa a manifest.json (si conserva la versione) e accende l'estensione. Ritorna il numero di versione."""
        m = self.pending(ext_id)
        if m is None:
            raise ExtError("non c'è nessuna proposta in attesa per questa estensione")
        validate_manifest(m)
        if m["id"] != ext_id:
            raise ExtError("proposta incoerente")
        n = (max(self.versions(ext_id) or [0])) + 1
        text = json.dumps(m, ensure_ascii=False, indent=2)
        _atomic_write(self._p(ext_id, "versioni", f"v{n}.json"), text)
        _atomic_write(self._p(ext_id, "manifest.json"), text)
        self._set_state(ext_id, attiva=True, versione=n)
        self.reject(ext_id)
        self._data(ext_id).close()
        return n

    def set_active(self, ext_id, on: bool):
        if self.manifest(ext_id) is None:
            raise ExtError("estensione non approvata")
        self._set_state(ext_id, attiva=on)

    def rollback(self, ext_id) -> int:
        """Torna alla versione approvata prima di quella attuale."""
        cur = self.state(ext_id)["versione"]
        older = [v for v in self.versions(ext_id) if v < cur]
        if not older:
            raise ExtError("non c'è una versione precedente")
        v = max(older)
        m = self._read(self._p(ext_id, "versioni", f"v{v}.json"))
        _atomic_write(self._p(ext_id, "manifest.json"), json.dumps(m, ensure_ascii=False, indent=2))
        self._set_state(ext_id, versione=v)
        return v

    # --- dati propri dell'estensione (un file SQLite dentro la sua cartella: portabile) ---
    def _data(self, ext_id):
        os.makedirs(self._p(ext_id), exist_ok=True)
        c = sqlite3.connect(self._p(ext_id, "dati.sqlite"), timeout=10)
        c.execute("CREATE TABLE IF NOT EXISTS righe(id INTEGER PRIMARY KEY AUTOINCREMENT, coll TEXT NOT NULL, ts REAL NOT NULL, data TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS impostazioni(chiave TEXT PRIMARY KEY, valore TEXT NOT NULL)")
        c.commit()
        return c

    def _fields_of(self, ext_id, coll):
        m = self.manifest(ext_id)
        for c in (m or {}).get("collezioni", []):
            if c["nome"] == coll:
                return c["campi"]
        raise ExtError(f"collezione «{coll}» sconosciuta")

    def row_add(self, ext_id, coll, values: dict) -> int:
        fields = self._fields_of(ext_id, coll)
        row = coerce_row(fields, values)
        c = self._data(ext_id)
        try:
            cur = c.execute("INSERT INTO righe(coll,ts,data) VALUES(?,?,?)", (coll, time.time(), json.dumps(row, ensure_ascii=False)))
            c.commit()
            return cur.lastrowid
        finally:
            c.close()

    def row_get(self, ext_id, coll, rid: int):
        c = self._data(ext_id)
        try:
            r = c.execute("SELECT id,data FROM righe WHERE coll=? AND id=?", (coll, rid)).fetchone()
        finally:
            c.close()
        return {"id": r[0], **json.loads(r[1])} if r else None

    def row_update(self, ext_id, coll, rid: int, values: dict) -> bool:
        fields = self._fields_of(ext_id, coll)
        cur = self.row_get(ext_id, coll, rid)
        if cur is None:
            return False
        cur.pop("id")
        cur.update(coerce_row(fields, values, partial=True))
        for f in fields:  # un campo obbligatorio non può restare vuoto
            if f.get("obbligatorio") and cur.get(f["chiave"]) in (None, "", []):
                raise ExtError(f"«{f.get('etichetta') or f['chiave']}» è obbligatorio")
        c = self._data(ext_id)
        try:
            c.execute("UPDATE righe SET data=? WHERE coll=? AND id=?", (json.dumps(cur, ensure_ascii=False), coll, rid))
            c.commit()
        finally:
            c.close()
        return True

    def row_delete(self, ext_id, coll, rid: int) -> bool:
        c = self._data(ext_id)
        try:
            n = c.execute("DELETE FROM righe WHERE coll=? AND id=?", (coll, rid)).rowcount
            c.commit()
            return n > 0
        finally:
            c.close()

    def rows(self, ext_id, coll, search: str = "", limit: int = 50, offset: int = 0):
        """Ritorna (righe, totale). Il testo cercato si confronta con tutti i campi."""
        like = f"%{search.strip().lower()}%" if search and search.strip() else None
        c = self._data(ext_id)
        try:
            q, a = "FROM righe WHERE coll=?", [coll]
            if like:
                q += " AND lower(data) LIKE ?"
                a.append(like)
            total = c.execute("SELECT COUNT(*) " + q, a).fetchone()[0]
            rs = c.execute("SELECT id,data " + q + " ORDER BY id DESC LIMIT ? OFFSET ?", (*a, limit, offset)).fetchall()
        finally:
            c.close()
        return [{"id": r[0], **json.loads(r[1])} for r in rs], total

    # --- impostazioni (i segreti NON stanno qui: in account.env) ---
    def settings(self, ext_id) -> dict:
        m = self.manifest(ext_id) or {}
        out = {f["chiave"]: f.get("predefinito") for f in m.get("impostazioni", []) if f["tipo"] != "segreto"}
        c = self._data(ext_id)
        try:
            for k, v in c.execute("SELECT chiave,valore FROM impostazioni").fetchall():
                if k in out:
                    out[k] = json.loads(v)
        finally:
            c.close()
        return out

    def save_settings(self, ext_id, form: dict) -> dict:
        """Salva i valori non segreti (controllati contro il manifest). Ritorna {NOME_ENV: valore} dei segreti nuovi: li scrive chi chiama."""
        m = self.manifest(ext_id) or {}
        vals, secrets = {}, {}
        for f in m.get("impostazioni", []):
            if f["tipo"] == "segreto":
                v = (form.get(f["chiave"]) or "").strip()
                if v:
                    if len(v) > 500 or "\n" in v or "\r" in v:
                        raise ExtError(f"«{f.get('etichetta') or f['chiave']}» non è valido")
                    secrets[secret_env_name(ext_id, f["chiave"])] = v
            else:
                vals[f["chiave"]] = coerce(f, form.get(f["chiave"]))
        c = self._data(ext_id)
        try:
            for k, v in vals.items():
                c.execute("INSERT INTO impostazioni(chiave,valore) VALUES(?,?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore", (k, json.dumps(v, ensure_ascii=False)))
            c.commit()
        finally:
            c.close()
        return secrets


def store_for(db) -> ExtStore:
    return ExtStore(db.ext_root, db.slug)


# ------------------------------------------------------------------ rete: solo domini approvati
def fetch_allowed(url: str, domini, headers: dict = None, opener=None, resolver=socket.getaddrinfo):
    """GET su un indirizzo pubblico E dentro i domini approvati, a ogni reindirizzamento. Ritorna (tipo, testo)."""
    from .tools import _NoRedirect, check_public_url, ToolError
    opener = opener or urllib.request.build_opener(_NoRedirect).open
    for _ in range(HOPS + 1):
        try:
            url = check_public_url(url, resolver)
        except ToolError as e:
            raise ExtError(str(e))
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if not _host_ok(host, domini):
            raise ExtError(f"«{host}» non è tra i siti approvati per questa estensione")
        h = {"User-Agent": "EDITH/1.0 (+estensione)", "Accept": "application/json,text/html,text/plain;q=0.9"}
        h.update(headers or {})
        try:
            with opener(urllib.request.Request(url, headers=h), timeout=TIMEOUT) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                if not any(x in ctype for x in ("html", "text", "json")):
                    raise ExtError(f"tipo di contenuto non leggibile: {ctype or 'sconosciuto'}")
                return ctype, r.read(MAX_BYTES).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers is not None else None
            if e.code in (301, 302, 303, 307, 308) and loc:
                url = urllib.parse.urljoin(url, loc)
                continue
            raise ExtError(f"il sito ha risposto con errore {e.code}") from None
        except ExtError:
            raise
        except Exception as e:
            raise ExtError(f"lettura fallita: {type(e).__name__}") from None
    raise ExtError("troppi reindirizzamenti")


def _dig(obj, path: str):
    for seg in path.split("."):
        if isinstance(obj, list):
            try:
                obj = obj[int(seg)]
            except (ValueError, IndexError):
                return "(non trovato)"
        elif isinstance(obj, dict) and seg in obj:
            obj = obj[seg]
        else:
            return "(non trovato)"
    return obj


# ------------------------------------------------------------------ esecuzione
def _subst(s: str, ctx: dict, quote: bool = False, secrets=None) -> str:
    def one(mo):
        tok = mo.group(1)
        if tok.startswith("segreto:"):
            v = (secrets or (lambda k: ""))(tok[8:])
            if not v:
                raise ExtError(f"manca il segreto «{tok[8:]}»: scrivilo nelle impostazioni dell'estensione")
            return v
        v = ctx.get(tok)
        if v is None or v == "":
            raise ExtError(f"manca il valore «{tok}»")
        v = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
        return urllib.parse.quote(v, safe="") if quote else v
    return _TOKEN.sub(one, s)


def _row_text(r: dict) -> str:
    return f"#{r['id']} " + " | ".join(f"{k}: {', '.join(v) if isinstance(v, list) else v}" for k, v in r.items() if k != "id" and v not in (None, "", []))


class Runtime:
    """Esegue gli strumenti delle estensioni approvate e attive di un account."""

    def __init__(self, store: ExtStore, db, ask=None, secrets=None, fetch=fetch_allowed):
        self.store, self.db, self.ask, self._secrets, self._fetch = store, db, ask, secrets, fetch

    def _active(self):
        for i in self.store.ids():
            m = self.store.manifest(i)
            if m and self.store.state(i)["attiva"]:
                yield i, m

    @staticmethod
    def _schema(fields):
        props, req = {}, []
        for f in fields:
            t = f["tipo"]
            p = {"type": {"numero": "number", "si_no": "boolean", "elenco": "array"}.get(t, "string")}
            if t == "elenco":
                p["items"] = {"type": "string"}
            if t == "scelta":
                p["enum"] = f["opzioni"]
            if f.get("aiuto") or f.get("etichetta"):
                p["description"] = f.get("aiuto") or f.get("etichetta")
            props[f["chiave"]] = p
            if f.get("obbligatorio") and "predefinito" not in f:
                req.append(f["chiave"])
        return {"type": "object", "properties": props, **({"required": req} if req else {})}

    def _tool_fields(self, m, t):
        """Campi che lo strumento accetta. Se aggiorna una riga serve «id» e gli altri campi sono facoltativi (si cambia solo ciò che viene passato)."""
        par = t.get("parametri", [])
        if isinstance(par, str):
            par = next((c["campi"] for c in m.get("collezioni", []) if c["nome"] == par[11:]), [])
        if any(p.get("tipo") == "aggiorna_riga" for p in t["passi"]):
            par = [{"chiave": "id", "tipo": "numero", "obbligatorio": True, "aiuto": "numero della riga da cambiare"}] +                   [{k: v for k, v in f.items() if k not in ("obbligatorio", "predefinito")} for f in par if f["chiave"] != "id"]
        return par

    def specs(self) -> list:
        out = []
        for i, m in self._active():
            for t in m.get("strumenti", []):
                fields = self._tool_fields(m, t)
                out.append({"type": "function", "function": {
                    "name": f"x_{i}_{t['nome']}",
                    "description": f"[Estensione «{m['nome']}»] {t['descrizione']}",
                    "parameters": self._schema(fields)}})
        return out

    def owns(self, name: str) -> bool:
        return any(s["function"]["name"] == name for s in self.specs())

    def run(self, name: str, args) -> str:
        for i, m in self._active():
            for t in m.get("strumenti", []):
                if name == f"x_{i}_{t['nome']}":
                    return self.run_tool(i, t["nome"], args or {})
        raise ExtError("strumento dell'estensione non disponibile")

    def run_tool(self, ext_id: str, tool: str, args: dict) -> str:
        m = self.store.manifest(ext_id)
        if not m or not self.store.state(ext_id)["attiva"]:
            raise ExtError("estensione spenta o non approvata")
        t = next((x for x in m.get("strumenti", []) if x["nome"] == tool), None)
        if t is None:
            raise ExtError("strumento sconosciuto")
        fields = self._tool_fields(m, t)
        args = args if isinstance(args, dict) else {}
        ctx = {k: v for k, v in self.store.settings(ext_id).items()}
        given = coerce_row(fields, args)
        ctx.update({k: v for k, v in given.items() if v is not None})
        sec = (lambda k: (self._secrets(ext_id, k) if self._secrets else "") or "")
        domini = m.get("domini", [])
        out = []
        for p in t["passi"]:
            tp = p["tipo"]
            if tp == "leggi_righe":
                rows, total = self.store.rows(ext_id, p["collezione"], _subst(str(p["cerca"]), ctx) if p.get("cerca") else "",
                                              limit=min(int(p.get("limite", 20)), MAX_ROWS_READ))
                out.append("\n".join(_row_text(r) for r in rows) + (f"\n({total} in tutto)" if total > len(rows) else "") if rows else "(nessun risultato)")
            elif tp == "scrivi_riga":
                rid = self.store.row_add(ext_id, p["collezione"], {k: given.get(k) for k in (f["chiave"] for f in self.store._fields_of(ext_id, p["collezione"]))})
                self.db.audit("estensione", "riga_aggiunta", f"{ext_id}/{p['collezione']} #{rid}")
                out.append(f"Salvato (riga #{rid}).")
            elif tp == "aggiorna_riga":
                rid = int(given.get("id") or 0)
                vals = {k: given[k] for k in args if k != "id" and k in given and k in {f["chiave"] for f in self.store._fields_of(ext_id, p["collezione"])}}
                ok = self.store.row_update(ext_id, p["collezione"], rid, vals)
                self.db.audit("estensione", "riga_aggiornata", f"{ext_id}/{p['collezione']} #{rid}")
                out.append(f"Riga #{rid} aggiornata." if ok else f"Non trovo la riga #{rid}.")
            elif tp in ("leggi_pagina", "leggi_api"):
                url = _subst(p["url"], ctx, quote=True)
                hd = {k: _subst(v, ctx, secrets=sec) for k, v in (p.get("intestazioni") or {}).items()}
                ctype, body = self._fetch(url, domini, hd or None)
                if tp == "leggi_api":
                    try:
                        data = json.loads(body)
                    except ValueError:
                        raise ExtError("la risposta del sito non è JSON")
                    ex = p.get("estrai") or []
                    out.append("\n".join(f"{x}: {json.dumps(_dig(data, x), ensure_ascii=False)[:2000]}" for x in ex) if ex
                               else json.dumps(data, ensure_ascii=False)[:MAX_TEXT])
                else:
                    from .tools import html_to_text
                    out.append(html_to_text(body) if "html" in ctype else body[:MAX_TEXT])
            elif tp == "leggi_dati":
                out.append(json.dumps(DATA_QUERIES[p["nome"]](self.db), ensure_ascii=False, default=str)[:MAX_TEXT])
            elif tp == "chiedi_al_modello":
                if not self.ask:
                    raise ExtError("l'intelligenza artificiale non è disponibile qui")
                out.append(self.ask(p["istruzione"], "\n\n".join(out)))
            elif tp in ("ricorda_tra", "ricorda_il"):
                msg = _subst(p["messaggio"], ctx).strip()[:300]
                if tp == "ricorda_tra":
                    try:
                        minuti = float(_subst(str(p["minuti"]), ctx).replace(",", "."))
                    except ValueError:
                        raise ExtError("«minuti» deve essere un numero")
                    if not 0 < minuti <= 60 * 24 * 365:
                        raise ExtError("«minuti» deve essere tra 0 e un anno")
                    due = time.time() + minuti * 60
                else:
                    from .scheduler import TZ
                    s = _subst(str(p["quando"]), ctx).strip().replace("T", " ")
                    try:
                        due = dt.datetime.fromisoformat(s if " " in s else s + " 09:00").replace(tzinfo=TZ).timestamp()
                    except ValueError:
                        raise ExtError("«quando» deve essere AAAA-MM-GG oppure AAAA-MM-GG HH:MM")
                    if due <= time.time():
                        raise ExtError("«quando» è già passato")
                tid = self.db.timer_add(ext_id, due, msg)
                self.db.audit("estensione", "timer_creato", f"{ext_id} #{tid}")
                out.append(f"Timer #{tid}: ti avviso alle {dt.datetime.fromtimestamp(due).strftime('%H:%M del %d/%m')}.")
        return ("\n\n".join(x for x in out if x))[:MAX_TEXT] or "(fatto)"


# ------------------------------------------------------------------ timer e programmi (ciclo principale)
def run_timers(db, tg, owner_id: int, now: float = None) -> list:
    """Invia i messaggi dei timer scaduti. Al massimo 5 tentativi per timer."""
    sent = []
    for tid, ext, msg, att in db.timers_due(now or time.time()):
        if att >= 5:
            db.timer_set(tid, "fallito")
            continue
        db.timer_set(tid, "in_attesa", attempts=att + 1)
        try:
            tg.send(owner_id, f"⏰ {msg}")
            db.timer_set(tid, "fatto")
            db.audit("estensione", "timer_scattato", f"{ext} #{tid}")
            sent.append(tid)
        except Exception as e:
            db.audit("estensione", "timer_errore", f"#{tid} {type(e).__name__}")
    return sent


def run_schedules(db, tg, owner_id: int, runtime: Runtime, now: dt.datetime = None) -> list:
    """Esegue i «programma» delle estensioni attive (una prova al giorno)."""
    from .scheduler import TZ
    now = now or dt.datetime.now(TZ)
    done = []
    for ext_id, m in list(runtime._active()):
        pr = m.get("programma")
        if not pr:
            continue
        giorno = pr.get("giorno", "ogni giorno")
        if giorno != "ogni giorno" and now.weekday() != GIORNI.index(giorno):
            continue
        h, mi = (int(x) for x in pr["ora"].split(":"))
        key = f"ext:{ext_id}:prog"
        if (now.hour, now.minute) < (h, mi) or db.get(key) == now.date().isoformat():
            continue
        db.set(key, now.date().isoformat())  # una sola prova al giorno: niente messaggi ripetuti se qualcosa va storto
        try:
            text = runtime.run_tool(ext_id, pr["strumento"], {})
            if pr.get("invia", True):
                tg.send(owner_id, f"🧩 {m['nome']}\n{text}", silent=True)
            db.audit("estensione", "programma_ok", ext_id)
            done.append(ext_id)
        except Exception as e:
            db.audit("estensione", "programma_errore", f"{ext_id}: {type(e).__name__}")
    return done


# ------------------------------------------------------------------ approvazioni (Telegram e pannello)
def pending_approval(db, ext_id: str):
    for aid, kind, payload in db._x("SELECT id,kind,payload FROM approvals WHERE status='in_attesa' AND kind IN ('nuova_estensione','modifica_estensione')").fetchall():
        try:
            if (json.loads(payload).get("extra") or {}).get("ext") == ext_id:
                return aid
        except ValueError:
            continue
    return None


def propose(db, m: dict, origine: str = "") -> int:
    """Valida, mette in attesa e crea l'approvazione. Ritorna l'id dell'approvazione."""
    store = store_for(db)
    validate_manifest(m)
    ext_id = m["id"]
    if db.get(f"ext:mai:{ext_id}", "") == "1":
        raise ExtError("il proprietario ha detto di NON riproporre questa estensione")
    if pending_approval(db, ext_id):
        raise ExtError("c'è già una proposta in attesa di risposta per questa estensione: aspetta che il proprietario decida")
    vecchio = store.manifest(ext_id)
    store.propose(m)
    kind = "modifica_estensione" if vecchio else "nuova_estensione"
    testo = riassunto(m, vecchio) + (f"\nOrigine: {origine}" if origine else "")
    aid = approvals.create(db, kind, f"{'Modifica a' if vecchio else 'Nuova estensione:'} {m['nome']}", testo,
                           extra={"ext": ext_id, "sha256": hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()})
    db.audit("manager", "estensione_proposta", f"{ext_id} approvazione #{aid}")
    return aid


def _hook_ok(db, a):
    ext_id = (a.get("extra") or {}).get("ext")
    store = store_for(db)
    n = store.approve(ext_id)
    m = store.manifest(ext_id)
    db.audit("proprietario", "estensione_approvata", f"{ext_id} v{n}")
    return f"Estensione «{m['nome']}» attiva (versione {n}). La sua pagina è nel pannello, sotto «Estensioni»."


def _hook_no(db, a, choice):
    ext_id = (a.get("extra") or {}).get("ext")
    store_for(db).reject(ext_id)
    if choice == "mai":
        db.set(f"ext:mai:{ext_id}", "1")
    db.audit("proprietario", "estensione_" + {"mai": "silenziata", "no": "rifiutata", "mod": "da_modificare"}.get(choice, "no"), ext_id or "")


def _hook_profilo_ok(db, a):
    from . import profile as prof
    ex = a.get("extra") or {}
    msg = prof.apply_rule(db.profile_dir, ex.get("azione", ""), ex.get("nuovo", ""), ex.get("vecchio", ""))
    if ex.get("lezione"):
        db.lesson_set(int(ex["lezione"]), "adottata")
    db.audit("proprietario", "regola_approvata", ex.get("azione", ""))
    return msg + " Vale da subito."


def _hook_profilo_no(db, a, choice):
    ex = a.get("extra") or {}
    if not ex.get("lezione"):
        return
    from . import profile as prof
    giorni = prof.load(db.profile_dir).get("riproponi_dopo_giorni", 14)
    if choice == "mai":
        db.lesson_set(int(ex["lezione"]), "mai_piu")
    else:
        db.lesson_set(int(ex["lezione"]), "rifiutata", time.time() + max(1, int(giorni)) * 86400)


# ------------------------------------------------------------------ catalogo (estensioni già riviste, nell'immagine)
CATALOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalogo")


def catalog_list(directory: str = None) -> list:
    """Estensioni del catalogo: [{id, nome, descrizione, sha256, verificata}]. «verificata» = l'impronta coincide con INDICE.json."""
    d = directory or CATALOG_DIR
    try:
        with open(os.path.join(d, "INDICE.json"), encoding="utf-8") as f:
            indice = json.load(f)
    except (OSError, ValueError):
        indice = {}
    out = []
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".json") and n != "INDICE.json")
    except OSError:
        return []
    for n in names:
        try:
            with open(os.path.join(d, n), "rb") as f:
                raw = f.read()
            m = json.loads(raw.decode("utf-8"))
            validate_manifest(m)
        except (OSError, ValueError, ExtError):
            continue
        h = hashlib.sha256(raw).hexdigest()
        out.append({"id": m["id"], "nome": m["nome"], "descrizione": m.get("descrizione", ""), "sha256": h,
                    "verificata": indice.get(m["id"]) == h, "file": n})
    return out


def catalog_install(db, ext_id: str, directory: str = None) -> int:
    """Mette in attesa un'estensione del catalogo (controllando l'impronta) e chiede l'approvazione. Ritorna l'id dell'approvazione."""
    d = directory or CATALOG_DIR
    voce = next((c for c in catalog_list(d) if c["id"] == ext_id), None)
    if voce is None:
        raise ExtError("estensione non presente nel catalogo")
    if not voce["verificata"]:
        raise ExtError("l'impronta di questa estensione non coincide con l'indice del catalogo: non la installo")
    with open(os.path.join(d, voce["file"]), encoding="utf-8") as f:
        m = json.load(f)
    return propose(db, m, origine="dal catalogo (impronta verificata)")


FORMATO = """FORMATO DELLE ESTENSIONI (manifest JSON). Una estensione è DICHIARATIVA: non scrivi codice, descrivi dati, strumenti e pagine.
Non può pubblicare, scrivere a nessuno né fare richieste che inviano dati: solo leggere da siti approvati, tenere dati PROPRI e avvisare il proprietario.
Si attiva SOLO se il proprietario approva (Telegram o pannello).

Voci del manifest (altre = errore): versione (1), id (minuscole/numeri/_, 2-24, inizia con lettera), nome, descrizione, effetti, domini,
impostazioni, collezioni, strumenti, pagine, programma.

- effetti: lista tra "leggere" (leggi_pagina/leggi_api), "dati_propri" (scrivi_riga/aggiorna_riga), "avvisa_proprietario" (ricorda_tra/ricorda_il).
  Devono comprendere TUTTI quelli che i passi usano.
- domini: i siti a cui si collega (es. "api.open-meteo.com"); ogni url dei passi deve essere https e su uno di questi domini, scritto per intero.
- campo (impostazioni, parametri, campi di collezione): {chiave, tipo, etichetta, aiuto, esempio, predefinito, opzioni, obbligatorio}.
  tipo: testo, testo_lungo, numero, si_no, scelta (con opzioni), elenco, data (AAAA-MM-GG), segreto (solo impostazioni).
- impostazioni: lista di campi che il proprietario compila nel pannello. I segreti si usano solo come {segreto:chiave} nelle intestazioni di leggi_api.
- collezioni: [{nome, campi:[campo]}] = dati propri; il proprietario li modifica dal pannello e tu li usi con gli strumenti.
- strumenti: [{nome, descrizione, parametri, passi}]. parametri = lista di campi OPPURE "collezione:<nome>" (usa i campi di quella collezione).
  Il bot li vede come x_<id>_<nome>.
- passi (in ordine; {x} = parametro o impostazione; l'ultimo testo ottenuto va al passo dopo):
  leggi_righe {collezione, cerca?, limite?}   scrivi_riga {collezione}   aggiorna_riga {collezione} (serve il parametro id)
  leggi_pagina {url}   leggi_api {url, estrai:["a.b.0"], intestazioni?}   leggi_dati {nome: fatti|contatti|opportunita|appunti|piano}
  chiedi_al_modello {istruzione}   ricorda_tra {minuti, messaggio}   ricorda_il {quando "AAAA-MM-GG HH:MM", messaggio}
- pagine: [{titolo, mostra:[ {tipo:"tabella"|"tabella_modificabile", collezione, colonne:[chiavi]} | {tipo:"lista", collezione, campo} | {tipo:"testo", testo} ]}]
  (le impostazioni compaiono da sole nella pagina).
- programma: {strumento, giorno:"ogni giorno" o "lunedì".., ora:"09:30", invia:true} (lo strumento non deve avere parametri).

Esempio minimo (timer):
{"id":"timer_cottura","nome":"Timer di cottura","descrizione":"Avvisa quando finisce una fase.","effetti":["avvisa_proprietario"],
 "strumenti":[{"nome":"timer_avvia","descrizione":"Avvisa tra N minuti.","parametri":[{"chiave":"minuti","tipo":"numero","obbligatorio":true},{"chiave":"cosa","tipo":"testo","obbligatorio":true}],
 "passi":[{"tipo":"ricorda_tra","minuti":"{minuti}","messaggio":"{cosa}: tempo scaduto"}]}]}

Prima di proporre: l'utente ne ha davvero bisogno? Spiegagli in due righe cosa farebbe. Dopo estensione_proponi aspetta la sua risposta: se rifiuta, non insistere; se preme «Non riproporre più», mai più."""


approvals.HOOKS["nuova_estensione"] = _hook_ok
approvals.HOOKS["modifica_estensione"] = _hook_ok
approvals.HOOKS["modifica_profilo"] = _hook_profilo_ok
approvals.NO_HOOKS["nuova_estensione"] = _hook_no
approvals.NO_HOOKS["modifica_estensione"] = _hook_no
approvals.NO_HOOKS["modifica_profilo"] = _hook_profilo_no
