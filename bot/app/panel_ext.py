"""Pagine del pannello per estensioni, approvazioni, lezioni e catalogo.

Il pannello DISEGNA le pagine dal manifest con il suo codice: nessun HTML o JavaScript arriva dal bot.
Ogni testo che viene dal manifest o dai dati (titoli, etichette, aiuti, righe) passa da html.escape.
Ogni scrittura è controllata contro i tipi dei campi, con il codice anti-CSRF del pannello.
"""
import datetime as dt
import json
import os
import urllib.parse

from . import approvals, config as cfgmod, extensions as ext, profile as prof
from .db import Db
from .panel import HELP, INPUT, H, btn, card, flash, link, page, pill, update_env

PAGE_SIZE = 25
PENDING_KINDS = ("nuova_estensione", "modifica_estensione", "modifica_profilo")
BACK = "text-sm text-indigo-600 hover:underline dark:text-indigo-400"


class _Ctx:
    """Apre il database dell'account per la durata di una richiesta."""

    def __init__(self, panel, cfg):
        self.panel, self.cfg = panel, cfg

    def __enter__(self):
        self.db = Db(self.cfg.data_dir)
        self.db.slug = self.cfg.slug
        self.db.profile_dir = self.cfg.profile_dir or self.cfg.data_dir
        self.db.ext_root = self.panel.ext_root
        return self.db

    def __exit__(self, *a):
        self.db.close()


def _csrf(s) -> str:
    return f'<input type="hidden" name="csrf" value="{H(s["csrf"])}">'


def _env_path(cfg) -> str:
    return os.path.join(cfg.profile_dir or cfg.data_dir, "account.env")


def pending_count(panel, cfg) -> int:
    try:
        with _Ctx(panel, cfg) as db:
            return len(_pending(db))
    except Exception:
        return 0


def _pending(db):
    out = []
    for aid, kind in db._x("SELECT id,kind FROM approvals WHERE status='in_attesa' ORDER BY id").fetchall():
        if kind in PENDING_KINDS:
            out.append(approvals.get(db, aid))
    return out


# ------------------------------------------------------------------ campi
def _input(f: dict, value, name: str = None) -> str:
    n = H(name or f["chiave"])
    t = f["tipo"]
    if t == "testo_lungo":
        return f'<textarea class="{INPUT} mt-1" name="{n}" rows="5">{H("" if value is None else str(value))}</textarea>'
    if t == "elenco":
        v = "\n".join(value) if isinstance(value, list) else ("" if value is None else str(value))
        return f'<textarea class="{INPUT} mt-1" name="{n}" rows="4">{H(v)}</textarea>'
    if t == "si_no":
        return (f'<select class="{INPUT} mt-1" name="{n}"><option value="1"{" selected" if value is True else ""}>Sì</option>'
                f'<option value="0"{" selected" if value is not True else ""}>No</option></select>')
    if t == "scelta":
        opts = "".join(f'<option value="{H(o)}"{" selected" if value == o else ""}>{H(o)}</option>' for o in f.get("opzioni", []))
        return f'<select class="{INPUT} mt-1" name="{n}">{opts}</select>'
    kind = {"segreto": "password", "data": "date"}.get(t, "text")
    ac = ' autocomplete="off"' if t == "segreto" else ""
    mode = ' inputmode="decimal"' if t == "numero" else ""
    return f'<input class="{INPUT} mt-1" type="{kind}" name="{n}" value="{H("" if value is None or t == "segreto" else str(value))}"{ac}{mode}>'


def _field_html(f: dict, value, extra: str = "") -> str:
    aiuto = H(f.get("aiuto", ""))
    if f.get("esempio"):
        aiuto += (" " if aiuto else "") + f"Esempio: <i>{H(f['esempio'])}</i>."
    req = " *" if f.get("obbligatorio") else ""
    return (f'<div class="mt-4"><label class="block font-medium">{H(f.get("etichetta") or f["chiave"])}{req}</label>'
            + (f'<p class="{HELP}">{aiuto}</p>' if aiuto else "") + extra + _input(f, value) + "</div>")


def _show_value(v) -> str:
    if isinstance(v, list):
        return ", ".join(map(str, v))
    if v is True:
        return "Sì"
    return "" if v is None else str(v)


# ------------------------------------------------------------------ approvazioni in attesa
def _pending_cards(panel, s, cfg, db) -> str:
    out = ""
    store = ext.store_for(db)
    base = f"/account/{H(cfg.slug)}/approvazione"
    for a in _pending(db):
        corpo = f'<pre class="mt-3 whitespace-pre-wrap break-words rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-900">{H(a["testo"])}</pre>'
        if a["kind"] in ("nuova_estensione", "modifica_estensione"):
            m = store.pending((a.get("extra") or {}).get("ext", ""))
            if m:
                corpo += ('<details class="mt-3"><summary class="cursor-pointer text-sm text-indigo-600 dark:text-indigo-400">Vedi il manifest completo (JSON)</summary>'
                          f'<pre class="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{H(json.dumps(m, ensure_ascii=False, indent=2))}</pre></details>')
        bottoni = "".join(f'<form method="post" action="{base}/{a["id"]}/{c}" class="inline">{_csrf(s)}{btn(t, k)}</form> '
                          for c, t, k in (("ok", "Approva", "primary"), ("no", "Rifiuta", "ghost"), ("mai", "Non riproporre più", "ghost")))
        out += card(f"Da approvare: {H(a['titolo'])}", "Il manager lo ha proposto. <b>Non si attiva finché non approvi</b> (qui o su Telegram).",
                    corpo + f'<div class="mt-4 flex flex-wrap gap-2">{bottoni}</div>', tone="")
    return out


# ------------------------------------------------------------------ pagine
def list_page(panel, s, cfg, db, msg="", err=""):
    store = ext.store_for(db)
    base = f"/account/{H(cfg.slug)}"
    righe = ""
    for i in store.ids():
        m = store.manifest(i)
        if not m:
            continue
        st = store.state(i)
        righe += (f'<a href="{base}/estensioni/{H(i)}" class="mt-3 block rounded-xl border border-slate-200 p-4 transition hover:border-indigo-400 dark:border-slate-700">'
                  f'<div class="flex items-center justify-between gap-3"><span class="font-semibold">{H(m["nome"])}</span>'
                  f'{pill("attiva", "ok") if st["attiva"] else pill("spenta", "no")}</div>'
                  f'<p class="mt-1 text-slate-600 dark:text-slate-300">{H(m.get("descrizione", ""))}</p>'
                  f'<p class="{HELP}">versione {st["versione"]}</p></a>')
    vuoto = '<p class="mt-3 text-slate-600 dark:text-slate-300">Nessuna estensione ancora.</p>'
    corpo = (f'<a href="{base}" class="{BACK}">← Torna a {H(cfg.slug)}</a><h1 class="mt-2 text-2xl font-bold">Estensioni</h1>'
             '<p class="mt-2 text-slate-600 dark:text-slate-300">Sono funzioni in più che il manager può costruirsi o che puoi installare dal catalogo: '
             'un ricettario, un timer, il meteo… Ognuna ha la sua pagina qui. <b>Niente si attiva senza il tuo OK</b>, e un\'estensione può solo leggere da siti che approvi, '
             'tenere i suoi dati e avvisarti: non pubblica e non scrive a nessuno.</p>'
             + flash(msg, err) + _pending_cards(panel, s, cfg, db)
             + card("Le tue estensioni", "", righe or vuoto)
             + f'<div class="mt-6">{link("Catalogo", base + "/catalogo", "ghost")}</div>')
    return page("Estensioni", corpo, s["csrf"])


def _table(store, ext_id, el, fields, base, s, query, editable: bool) -> str:
    coll = el["collezione"]
    cols = el.get("colonne") or [el.get("campo")]
    byk = {f["chiave"]: f for f in fields}
    q = (query.get("q", [""])[0] or "")[:100]
    pg = max(1, int((query.get("p", ["1"])[0] or "1")) if (query.get("p", ["1"])[0] or "1").isdigit() else 1)
    rows, total = store.rows(ext_id, coll, search=q, limit=PAGE_SIZE, offset=(pg - 1) * PAGE_SIZE)
    head = "".join(f'<th class="py-2 pr-3 text-left font-medium">{H(byk[c].get("etichetta") or c)}</th>' for c in cols) + ("<th></th>" if editable else "")
    body = ""
    for r in rows:
        tds = "".join(f'<td class="py-2 pr-3 align-top">{H(_show_value(r.get(c)))}</td>' for c in cols)
        if editable:
            tds += (f'<td class="py-2 text-right whitespace-nowrap"><a class="text-indigo-600 hover:underline dark:text-indigo-400" href="{base}/modifica/{H(coll)}/{r["id"]}">Modifica</a> '
                    f'<form method="post" action="{base}/riga" class="inline">{_csrf(s)}<input type="hidden" name="coll" value="{H(coll)}"><input type="hidden" name="rid" value="{r["id"]}">'
                    '<button name="azione" value="elimina_chiedi" class="ml-3 text-red-600 hover:underline">Elimina</button></form></td>')
        body += f'<tr class="border-t border-slate-200 dark:border-slate-700">{tds}</tr>'
    tab = (f'<form method="get" class="mt-3 flex gap-2"><input class="{INPUT}" name="q" value="{H(q)}" placeholder="Cerca…">{btn("Cerca", "ghost")}</form>'
           f'<div class="mt-3 overflow-x-auto"><table class="w-full text-left"><thead><tr>{head}</tr></thead><tbody>{body or ""}</tbody></table></div>')
    if not rows:
        tab += '<p class="mt-3 text-slate-600 dark:text-slate-300">Nessuna riga.</p>'
    pager = ""
    if total > PAGE_SIZE:
        pager = f'<p class="{HELP}">Pagina {pg} di {-(-total // PAGE_SIZE)} · {total} righe. '
        if pg > 1:
            pager += f'<a class="underline" href="?q={urllib.parse.quote(q)}&p={pg - 1}">← prima</a> '
        if pg * PAGE_SIZE < total:
            pager += f'<a class="underline" href="?q={urllib.parse.quote(q)}&p={pg + 1}">dopo →</a>'
        pager += "</p>"
    add = ""
    if editable:
        campi = "".join(_field_html(f, f.get("predefinito")) for f in fields)
        add = (f'<details class="mt-4"><summary class="cursor-pointer font-medium text-indigo-600 dark:text-indigo-400">+ Aggiungi</summary>'
               f'<form method="post" action="{base}/riga" class="mt-2">{_csrf(s)}<input type="hidden" name="coll" value="{H(coll)}">{campi}'
               f'<div class="mt-4">{btn("Salva", name="azione", value="aggiungi")}</div></form></details>')
    return tab + pager + add


def ext_page(panel, s, cfg, db, ext_id, query=None, msg="", err="", extra=""):
    store = ext.store_for(db)
    m = store.manifest(ext_id)
    if not m:
        return page("Non trovata", "<h1>Estensione non trovata</h1>", s["csrf"])
    query = query or {}
    st = store.state(ext_id)
    base = f"/account/{H(cfg.slug)}/estensioni/{H(ext_id)}"
    colls = {c["nome"]: c["campi"] for c in m.get("collezioni", [])}
    azioni = (f'<form method="post" action="{base}/attiva" class="inline">{_csrf(s)}<input type="hidden" name="on" value="{"0" if st["attiva"] else "1"}">'
              f'{btn("Spegni" if st["attiva"] else "Accendi", "ghost")}</form> ')
    if len(store.versions(ext_id)) > 1 and st["versione"] > min(store.versions(ext_id)):
        azioni += f'<form method="post" action="{base}/indietro" class="inline">{_csrf(s)}{btn("Torna alla versione precedente", "ghost")}</form> '
    if m.get("programma"):
        azioni += f'<form method="post" action="{base}/esegui" class="inline">{_csrf(s)}{btn("Esegui ora", "ghost")}</form>'
    top = (f'<a href="/account/{H(cfg.slug)}/estensioni" class="{BACK}">← Estensioni</a>'
           f'<div class="mt-2 flex items-center gap-3"><h1 class="text-2xl font-bold">{H(m["nome"])}</h1>{pill("attiva", "ok") if st["attiva"] else pill("spenta", "no")}</div>'
           f'<p class="mt-1 text-slate-600 dark:text-slate-300">{H(m.get("descrizione", ""))}</p>'
           f'<p class="{HELP}">Versione {st["versione"]} · {H(", ".join(m.get("domini", [])) or "non si collega a nessun sito")}</p>'
           f'<div class="mt-4 flex flex-wrap gap-2">{azioni}</div>')
    body = top + flash(msg, err) + extra
    if m.get("impostazioni"):
        vals = store.settings(ext_id)
        env = cfgmod.parse_env_file(_env_path(cfg))
        campi = ""
        for f in m["impostazioni"]:
            if f["tipo"] == "segreto":
                ok = bool(env.get(ext.secret_env_name(ext_id, f["chiave"])))
                campi += _field_html(f, "", f'<p class="mt-1">{pill("impostato", "ok") if ok else pill("non impostato")} <span class="{HELP}">Lascia vuoto per non cambiarlo; non si mostra mai.</span></p>')
            else:
                campi += _field_html(f, vals.get(f["chiave"]))
        body += card("Impostazioni", "", f'<form method="post" action="{base}/impostazioni">{_csrf(s)}{campi}<div class="mt-5">{btn("Salva")}</div></form>')
    for pg in m.get("pagine", []):
        parts = ""
        for el in pg["mostra"]:
            t = el["tipo"]
            if t == "testo":
                parts += f'<p class="mt-3">{H(el["testo"])}</p>'
            elif t in ("tabella", "tabella_modificabile"):
                parts += _table(store, ext_id, el, colls[el["collezione"]], base, s, query, t == "tabella_modificabile")
            elif t == "lista":
                rows, _ = store.rows(ext_id, el["collezione"], limit=100)
                parts += '<ul class="mt-3 list-disc pl-5">' + "".join(f'<li>{H(_show_value(r.get(el["campo"])))}</li>' for r in rows) + "</ul>"
        body += card(H(pg["titolo"]), "", parts)
    return page(m["nome"], body, s["csrf"])


def edit_row_page(panel, s, cfg, db, ext_id, coll, rid, err=""):
    store = ext.store_for(db)
    m = store.manifest(ext_id)
    row = store.row_get(ext_id, coll, rid) if m else None
    if not m or not row or coll not in {c["nome"] for c in m.get("collezioni", [])}:
        return page("Non trovata", "<h1>Riga non trovata</h1>", s["csrf"])
    fields = store._fields_of(ext_id, coll)
    base = f"/account/{H(cfg.slug)}/estensioni/{H(ext_id)}"
    campi = "".join(_field_html(f, row.get(f["chiave"])) for f in fields)
    form = (f'<form method="post" action="{base}/riga">{_csrf(s)}<input type="hidden" name="coll" value="{H(coll)}"><input type="hidden" name="rid" value="{rid}">'
            f'{campi}<div class="mt-5 flex gap-3">{btn("Salva", name="azione", value="salva")}{link("Annulla", base, "ghost")}</div></form>')
    return page("Modifica", f'<a href="{base}" class="{BACK}">← {H(m["nome"])}</a><h1 class="mt-2 text-2xl font-bold">Modifica riga #{rid}</h1>' + flash(err=err) + card("", "", form), s["csrf"])


def lessons_page(panel, s, cfg, db, msg="", err=""):
    base = f"/account/{H(cfg.slug)}"
    regole = prof.load(db.profile_dir).get("regole_extra") or []
    righe = ""
    for l in db.lessons_list(limit=100):
        quando = ""
        if l["stato"] == "rifiutata" and l["riproponi_dopo"]:
            quando = f' · riproponibile dal {dt.datetime.fromtimestamp(l["riproponi_dopo"]).strftime("%d/%m/%Y")}'
        tono = {"adottata": "ok", "rifiutata": "no"}.get(l["stato"], "mu")
        righe += (f'<li class="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-3 dark:border-slate-700"><span>{H(l["testo"])} '
                  f'<span class="{HELP}">×{l["ripetizioni"]}{H(quando)}</span></span><span class="flex items-center gap-2">{pill(l["stato"].replace("_", " "), tono)}'
                  f'<form method="post" action="{base}/lezioni/{l["id"]}/scarta" class="inline">{_csrf(s)}'
                  '<button class="text-sm text-red-600 hover:underline">Non riproporre più</button></form></span></li>')
    scartate = ""
    for l in db.lessons_list("mai_piu", limit=100):
        scartate += (f'<li class="mt-2 flex items-center justify-between gap-2"><span class="line-through opacity-70">{H(l["testo"])}</span>'
                     f'<form method="post" action="{base}/lezioni/{l["id"]}/riattiva" class="inline">{_csrf(s)}<button class="text-sm text-indigo-600 hover:underline dark:text-indigo-400">Riattiva</button></form></li>')
    giorni = prof.load(db.profile_dir).get("riproponi_dopo_giorni", 14)
    corpo = (f'<a href="{base}" class="{BACK}">← Torna a {H(cfg.slug)}</a><h1 class="mt-2 text-2xl font-bold">Cosa ha imparato</h1>'
             '<p class="mt-2 text-slate-600 dark:text-slate-300">Il manager annota quello che nota usandolo. Quando una lezione vale la pena ti propone una regola, '
             f'<b>che cambia solo se approvi</b>. Se la rifiuti, la riproporrà non prima di {int(giorni)} giorni; con «Non riproporre più» non torna mai.</p>'
             + flash(msg, err) + _pending_cards(panel, s, cfg, db)
             + card("Lezioni", "", f'<ul class="list-none">{righe}</ul>' if righe else '<p class="mt-3 text-slate-600 dark:text-slate-300">Ancora nessuna lezione.</p>')
             + card("Regole extra attive", "Per cambiarle a mano: Personalità, nella pagina dell'account.",
                    ('<ul class="mt-3 list-disc pl-5">' + "".join(f"<li>{H(r)}</li>" for r in regole) + "</ul>") if regole else '<p class="mt-3 text-slate-600 dark:text-slate-300">Nessuna.</p>'))
    if scartate:
        corpo += card("Scartate per sempre", "", f'<ul class="list-none">{scartate}</ul>')
    return page("Cosa ha imparato", corpo, s["csrf"])


def catalog_page(panel, s, cfg, db, msg="", err=""):
    store = ext.store_for(db)
    base = f"/account/{H(cfg.slug)}"
    righe = ""
    for v in ext.catalog_list():
        gia = store.manifest(v["id"]) is not None
        stato = pill("installata", "ok") if gia else (pill("verificata", "ok") if v["verificata"] else pill("impronta non valida", "no"))
        azione = ""
        if v["verificata"] and not gia:
            azione = f'<form method="post" action="{base}/catalogo/{H(v["id"])}/proponi" class="mt-3">{_csrf(s)}{btn("Proponi l\'installazione", "ghost")}</form>'
        righe += (f'<div class="mt-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700"><div class="flex items-center justify-between gap-3">'
                  f'<span class="font-semibold">{H(v["nome"])}</span>{stato}</div><p class="mt-1 text-slate-600 dark:text-slate-300">{H(v["descrizione"])}</p>{azione}</div>')
    corpo = (f'<a href="{base}/estensioni" class="{BACK}">← Estensioni</a><h1 class="mt-2 text-2xl font-bold">Catalogo</h1>'
             '<p class="mt-2 text-slate-600 dark:text-slate-300">Estensioni già pronte, controllate con un\'impronta. «Proponi» non installa: crea una richiesta che <b>approvi tu</b> '
             'dopo aver visto cosa può fare.</p>' + flash(msg, err) + _pending_cards(panel, s, cfg, db) + card("Disponibili", "", righe or "<p>Il catalogo è vuoto.</p>"))
    return page("Catalogo", corpo, s["csrf"])


STATO_LIB = {"nuova": ("in coda per lo studio", "mu"), "in_studio": ("lo sto studiando…", "mu"), "studiata": ("studiato", "ok"), "errore": ("errore", "no")}


def library_page(panel, s, cfg, db, msg="", err=""):
    from . import biblioteca as bib
    base = f"/account/{H(cfg.slug)}"
    csrf = _csrf(s)
    righe = ""
    for f in bib.elenco(db):
        testo_stato, tono = STATO_LIB.get(f["stato"], (f["stato"], "mu"))
        azioni = (f'<form method="post" action="{base}/biblioteca/{f["id"]}/ristudia" class="inline">{csrf}<button class="text-sm text-indigo-600 hover:underline dark:text-indigo-400">Studia di nuovo</button></form> '
                  f'<form method="post" action="{base}/biblioteca/{f["id"]}/elimina_chiedi" class="ml-3 inline">{csrf}<button class="text-sm text-red-600 hover:underline">Elimina</button></form>')
        riass = (f'<details class="mt-2"><summary class="cursor-pointer text-sm text-indigo-600 dark:text-indigo-400">Riassunto</summary><p class="mt-1">{H(f["riassunto"])}</p></details>' if f["riassunto"] else "")
        righe += (f'<li class="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700"><div class="flex flex-wrap items-center justify-between gap-2">'
                  f'<span class="font-medium">{H(f["titolo"])}</span>{pill(testo_stato, tono)}</div>'
                  f'<p class="{HELP}">{H(f["tipo"])} · {f["pagine"]} pagine · {f["pezzi"]} pezzi'
                  + (f' · {f["principi"]} principi annotati' if f["principi"] else "") + (f' · {H(f["nota"])}' if f["nota"] else "") + f'</p>{riass}'
                  f'<div class="mt-2">{azioni}</div></li>')
    n_esp = len(bib.elenco(db, True)) - len(bib.elenco(db))
    aggiungi = (
        f'<form method="post" enctype="multipart/form-data" action="{base}/biblioteca/file" class="mt-4">{csrf}'
        f'<p class="font-medium">Un file</p><p class="{HELP}">PDF, Word (.docx), PowerPoint (.pptx), testo o Markdown, fino a 25 MB.</p>'
        f'<input class="{INPUT} mt-2" type="file" name="file" accept=".pdf,.docx,.pptx,.txt,.md,.markdown" required>'
        f'<input class="{INPUT} mt-2" name="titolo" placeholder="Titolo (facoltativo)"><div class="mt-3">{btn("Carica e studia")}</div></form>'
        f'<form method="post" action="{base}/biblioteca/link" class="mt-6 border-t border-slate-200 pt-4 dark:border-slate-700">{csrf}'
        f'<p class="font-medium">Un link</p><p class="{HELP}">Una pagina web pubblica (si legge solo quella pagina).</p>'
        f'<input class="{INPUT} mt-2" name="url" placeholder="https://…" required><input class="{INPUT} mt-2" name="titolo" placeholder="Titolo (facoltativo)">'
        f'<div class="mt-3">{btn("Leggi e studia")}</div></form>'
        f'<form method="post" action="{base}/biblioteca/testo" class="mt-6 border-t border-slate-200 pt-4 dark:border-slate-700">{csrf}'
        f'<p class="font-medium">Un testo incollato</p><input class="{INPUT} mt-2" name="titolo" placeholder="Titolo"><textarea class="{INPUT} mt-2" name="testo" rows="6" required></textarea>'
        f'<div class="mt-3">{btn("Salva e studia")}</div></form>')
    corpo = (f'<a href="{base}" class="{BACK}">← Torna a {H(cfg.slug)}</a><h1 class="mt-2 text-2xl font-bold">Biblioteca</h1>'
             '<p class="mt-2 text-slate-600 dark:text-slate-300">Qui dai al manager i documenti da cui imparare: un corso in PDF, una guida, i tuoi appunti. '
             'Lui li legge, li studia (ne ricava un riassunto e dei <b>principi</b>, che diventano regole solo se approvi) e, quando una tua domanda c\'entra, '
             '<b>cerca da solo i passaggi giusti</b> e ti dice da dove vengono. Puoi anche mandarglieli su Telegram con <code>/impara</code>.</p>'
             f'<p class="{HELP}">Limiti: i PDF fatti solo di immagini non si leggono; il testo dei documenti resta sul tuo server (non su Git) e i pezzi pertinenti vanno al servizio IA già usato; '
             'il manager li tratta come nozioni di terzi, non come istruzioni e non come misure del tuo account. Rispetta il diritto d\'autore: per uso tuo.</p>'
             + flash(msg, err) + card("Aggiungi un documento", "", aggiungi)
             + card("I tuoi documenti", "", f'<ul class="list-none">{righe}</ul>' if righe else '<p class="mt-3 text-slate-600 dark:text-slate-300">Ancora nessun documento.</p>')
             + f'<p class="{HELP} mt-6">In più, la ricerca automatica usa i ruoli di {n_esp} esperti (<a class="underline" href="{base}/esperti">Esperti</a>).</p>')
    return page("Biblioteca", corpo, s["csrf"])


DIVISIONI = {"marketing": "Marketing e social", "design": "Design e immagine", "sales": "Vendite e contatti", "paid-media": "Pubblicità a pagamento",
             "support": "Supporto e analisi", "product": "Prodotto e tendenze", "research": "Ricerca", "specialized": "Specialisti"}


def experts_page(panel, s, cfg, db, msg="", err=""):
    from . import esperti as esp
    base = f"/account/{H(cfg.slug)}"
    spenti = set(prof.load(db.profile_dir).get("esperti_spenti") or [])
    gruppi = {}
    for eid, m in sorted(esp.catalog().items()):
        gruppi.setdefault(m["divisione"], []).append((eid, m))
    corpo = (f'<a href="{base}" class="{BACK}">← Torna a {H(cfg.slug)}</a><h1 class="mt-2 text-2xl font-bold">Esperti</h1>'
             '<p class="mt-2 text-slate-600 dark:text-slate-300">Sono consulenti che il manager può interpellare per un <b>parere</b> (strategia social, contenuti, PR, bandi…). '
             'Un esperto <b>non vede il tuo account</b> (riceve solo ciò che il manager gli passa, senza chiavi), <b>non può agire</b> e il suo parere resta un\'ipotesi da verificare coi tuoi dati. '
             'Qui scegli quali può usare per questo account.</p>' + flash(msg, err))
    for div, voci in sorted(gruppi.items(), key=lambda kv: list(DIVISIONI).index(kv[0]) if kv[0] in DIVISIONI else 99):
        righe = ""
        for eid, m in voci:
            on = eid not in spenti and m["verificato"]
            stato = pill("attivo", "ok") if on else pill("spento" if m["verificato"] else "impronta non valida", "no" if not m["verificato"] else "mu")
            azione = ""
            if m["verificato"]:
                azione = (f'<form method="post" action="{base}/esperti/{H(eid)}/{"spegni" if on else "accendi"}" class="inline">{_csrf(s)}'
                          f'<button class="text-sm text-indigo-600 hover:underline dark:text-indigo-400">{"Spegni" if on else "Accendi"}</button></form>')
            righe += (f'<li class="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700"><div class="flex flex-wrap items-center justify-between gap-2">'
                      f'<span class="font-medium">{H(m["nome"])}</span><span class="flex items-center gap-3">{stato}{azione}</span></div>'
                      f'<p class="{HELP}">{H(m["descrizione"][:220])}</p></li>')
        corpo += card(H(DIVISIONI.get(div, div)), "", f'<ul class="list-none">{righe}</ul>')
    corpo += (f'<p class="{HELP} mt-6">I ruoli vengono dal progetto <a class="underline" href="https://github.com/msitarzewski/agency-agents">agency-agents</a> '
              '(licenza MIT), importati senza modifiche da una versione fissa e ricontrollati a ogni uso.</p>')
    return page("Esperti", corpo, s["csrf"])


# ------------------------------------------------------------------ instradamento
def _runtime(panel, cfg, db):
    ai = panel.ext_ask
    if ai is None:
        from .ai import Ai
        client = Ai(cfg.ai_base_url, cfg.ai_api_key)
        ai = lambda istr, dati="": client.chat(cfg.model_light, [{"role": "user", "content": istr + (chr(10) * 2 + "DATI:" + chr(10) + dati[:30000] if dati else "")}], max_tokens=1500)
    sec = lambda e, k: cfgmod.parse_env_file(_env_path(cfg)).get(ext.secret_env_name(e, k), "")
    return ext.Runtime(ext.store_for(db), db, ask=ai, secrets=sec, **({"fetch": panel.ext_fetch} if panel.ext_fetch else {}))


def get(panel, s, cfg, parts, query):
    """GET /account/<slug>/<parts...>. Ritorna (codice, html)."""
    with _Ctx(panel, cfg) as db:
        try:
            if parts == ["estensioni"]:
                return 200, list_page(panel, s, cfg, db)
            if len(parts) == 2 and parts[0] == "estensioni":
                return 200, ext_page(panel, s, cfg, db, parts[1], query)
            if len(parts) == 5 and parts[0] == "estensioni" and parts[2] == "modifica" and parts[4].isdigit():
                return 200, edit_row_page(panel, s, cfg, db, parts[1], parts[3], int(parts[4]))
            if parts == ["lezioni"]:
                return 200, lessons_page(panel, s, cfg, db)
            if parts == ["catalogo"]:
                return 200, catalog_page(panel, s, cfg, db)
            if parts == ["esperti"]:
                return 200, experts_page(panel, s, cfg, db)
            if parts == ["biblioteca"]:
                return 200, library_page(panel, s, cfg, db)
        except ext.ExtError as e:
            return 200, page("Errore", flash(err=str(e)), s["csrf"])
    return 404, page("Non trovato", "<h1>Pagina non trovata</h1>", s["csrf"])


def post(panel, s, cfg, parts, form, files=None):
    """POST /account/<slug>/<parts...>. Ritorna (codice, html)."""
    with _Ctx(panel, cfg) as db:
        try:
            if len(parts) == 3 and parts[0] == "approvazione" and parts[1].isdigit() and parts[2] in ("ok", "no", "mai"):
                a = approvals.get(db, int(parts[1]))
                if not a or a["kind"] not in PENDING_KINDS:
                    return 404, page("Non trovato", "<h1>Proposta non trovata</h1>", s["csrf"])
                status, text = approvals.decide(db, int(parts[1]), parts[2])
                back = lessons_page if a["kind"] == "modifica_profilo" else list_page
                return 200, back(panel, s, cfg, db, msg=f"{approvals.STATUS_LABEL.get(status, '')} {text}".strip())
            if len(parts) == 3 and parts[0] == "lezioni" and parts[1].isdigit() and parts[2] in ("scarta", "riattiva"):
                if db.lesson_get(int(parts[1])) is None:
                    return 404, page("Non trovato", "<h1>Lezione non trovata</h1>", s["csrf"])
                db.lesson_set(int(parts[1]), "mai_piu" if parts[2] == "scarta" else "nuova")
                db.audit("proprietario", "lezione_" + parts[2], f"#{parts[1]}")
                return 200, lessons_page(panel, s, cfg, db, msg="Fatto.")
            if parts and parts[0] == "biblioteca":
                return _lib_action(panel, s, cfg, db, parts, form, files or {})
            if len(parts) == 3 and parts[0] == "esperti" and parts[2] in ("accendi", "spegni"):
                from . import esperti as esp
                m = esp.catalog().get(parts[1])
                if m is None or not m["verificato"]:
                    return 404, page("Non trovato", "<h1>Esperto non trovato</h1>", s["csrf"])
                prof.set_expert(db.profile_dir, parts[1], parts[2] == "accendi")
                db.audit("proprietario", "esperto_" + parts[2], parts[1])
                return 200, experts_page(panel, s, cfg, db, msg=f"«{m['nome']}»: {'acceso' if parts[2] == 'accendi' else 'spento'}.")
            if len(parts) == 3 and parts[0] == "catalogo" and parts[2] == "proponi":
                ext.catalog_install(db, parts[1])
                return 200, list_page(panel, s, cfg, db, msg="Proposta creata: leggila qui sotto e approvala se ti va bene.")
            if len(parts) == 3 and parts[0] == "estensioni":
                return _ext_action(panel, s, cfg, db, parts[1], parts[2], form)
        except ext.ExtError as e:
            if len(parts) == 3 and parts[0] == "estensioni":
                return 200, ext_page(panel, s, cfg, db, parts[1], err=str(e))
            return 200, list_page(panel, s, cfg, db, err=str(e))
    return 404, page("Non trovato", "<h1>Pagina non trovata</h1>", s["csrf"])


def _lib_action(panel, s, cfg, db, parts, form, files):
    from . import biblioteca as bib
    base = f"/account/{H(cfg.slug)}"
    ok = "Letto «{t}»: {p} pagine, {n} pezzi. Lo studio parte entro un minuto e ti scrivo su Telegram quando finisce. Intanto ci si può già cercare dentro."
    try:
        if parts == ["biblioteca", "file"]:
            if "file" not in files or not files["file"][1]:
                raise bib.BibliotecaError("scegli un file")
            nome, dati = files["file"]
            fid, nuovo = bib.aggiungi_file(db, nome, dati, form.get("titolo", ""), extractor=panel.lib_extract)
        elif parts == ["biblioteca", "link"]:
            fid, nuovo = bib.aggiungi_link(db, (form.get("url") or "").strip(), form.get("titolo", ""), fetch=panel.lib_fetch)
        elif parts == ["biblioteca", "testo"]:
            fid, nuovo = bib.aggiungi_testo(db, form.get("titolo", ""), form.get("testo", ""))
        elif len(parts) == 3 and parts[1].isdigit() and parts[2] in ("elimina_chiedi", "elimina", "ristudia"):
            fid = int(parts[1])
            f = next((x for x in bib.elenco(db) if x["id"] == fid), None)
            if f is None:
                return 404, page("Non trovato", "<h1>Documento non trovato</h1>", s["csrf"])
            if parts[2] == "elimina_chiedi":
                conferma = (f'<form method="post" action="{base}/biblioteca/{fid}/elimina">{_csrf(s)}'
                            f'<p class="mt-3">Vuoi togliere «{H(f["titolo"])}» dalla biblioteca? Il testo del documento viene cancellato dal server. '
                            f'I principi già annotati e le regole già approvate restano.</p>'
                            f'<div class="mt-4 flex gap-3">{btn("Sì, elimina", "danger")}{link("No, torna indietro", base + "/biblioteca", "ghost")}</div></form>')
                return 200, page("Elimina", card("Eliminare il documento?", "", conferma), s["csrf"])
            if parts[2] == "elimina":
                bib.rimuovi(db, fid)
                return 200, library_page(panel, s, cfg, db, msg="Documento eliminato.")
            db._x("UPDATE fonti SET stato='nuova', nota=NULL WHERE id=? AND stato IN ('studiata','errore')", (fid,))
            return 200, library_page(panel, s, cfg, db, msg="Lo studierò di nuovo entro un minuto.")
        else:
            return 404, page("Non trovato", "<h1>Pagina non trovata</h1>", s["csrf"])
    except bib.BibliotecaError as e:
        return 200, library_page(panel, s, cfg, db, err=f"Non posso aggiungerlo: {e}.")
    t, p, n = db._x("SELECT titolo,pagine,pezzi FROM fonti WHERE id=?", (fid,)).fetchone()
    return 200, library_page(panel, s, cfg, db, msg=ok.format(t=t, p=p, n=n) if nuovo else f"«{t}» era già in biblioteca.")


def _ext_action(panel, s, cfg, db, ext_id, act, form):
    store = ext.store_for(db)
    if store.manifest(ext_id) is None:
        return 404, page("Non trovato", "<h1>Estensione non trovata</h1>", s["csrf"])
    msg = ""
    extra = ""
    if act == "impostazioni":
        segreti = store.save_settings(ext_id, form)
        if segreti:
            update_env(_env_path(cfg), segreti)
        db.audit("proprietario", "estensione_impostazioni", ext_id)
        msg = "Impostazioni salvate."
    elif act == "attiva":
        store.set_active(ext_id, form.get("on") == "1")
        db.audit("proprietario", "estensione_" + ("accesa" if form.get("on") == "1" else "spenta"), ext_id)
        msg = "Acceso." if form.get("on") == "1" else "Spenta."
    elif act == "indietro":
        v = store.rollback(ext_id)
        db.audit("proprietario", "estensione_indietro", f"{ext_id} v{v}")
        msg = f"Tornato alla versione {v}."
    elif act == "esegui":
        pr = (store.manifest(ext_id) or {}).get("programma")
        if not pr:
            raise ext.ExtError("questa estensione non ha un programma")
        testo = _runtime(panel, cfg, db).run_tool(ext_id, pr["strumento"], {})
        extra = card("Risultato", "", f'<pre class="mt-3 whitespace-pre-wrap break-words rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-900">{H(testo)}</pre>')
    elif act == "riga":
        coll, azione = form.get("coll", ""), form.get("azione", "")
        rid = int(form["rid"]) if (form.get("rid") or "").isdigit() else 0
        if azione == "aggiungi":
            rid = store.row_add(ext_id, coll, form)
            db.audit("proprietario", "riga_aggiunta", f"{ext_id}/{coll} #{rid}")
            msg = f"Aggiunta (riga #{rid})."
        elif azione == "salva":
            if not store.row_update(ext_id, coll, rid, form):
                raise ext.ExtError("riga non trovata")
            db.audit("proprietario", "riga_modificata", f"{ext_id}/{coll} #{rid}")
            msg = "Salvato."
        elif azione == "elimina_chiedi":
            r = store.row_get(ext_id, coll, rid)
            if not r:
                raise ext.ExtError("riga non trovata")
            base = f"/account/{H(cfg.slug)}/estensioni/{H(ext_id)}"
            conferma = (f'<form method="post" action="{base}/riga">{_csrf(s)}<input type="hidden" name="coll" value="{H(coll)}"><input type="hidden" name="rid" value="{rid}">'
                        f'<p class="mt-3">Vuoi eliminare «{H(_show_value(next(iter(v for k, v in r.items() if k != "id"), "")))}»? I dati non tornano indietro.</p>'
                        f'<div class="mt-4 flex gap-3">{btn("Sì, elimina", "danger", "azione", "elimina")}{link("No, torna indietro", base, "ghost")}</div></form>')
            return 200, page("Elimina", card("Eliminare la riga?", "", conferma), s["csrf"])
        elif azione == "elimina":
            if not store.row_delete(ext_id, coll, rid):
                raise ext.ExtError("riga non trovata")
            db.audit("proprietario", "riga_eliminata", f"{ext_id}/{coll} #{rid}")
            msg = "Eliminata."
        else:
            raise ext.ExtError("azione non valida")
    else:
        return 404, page("Non trovato", "<h1>Pagina non trovata</h1>", s["csrf"])
    return 200, ext_page(panel, s, cfg, db, ext_id, msg=msg, extra=extra)
