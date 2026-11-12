"""Pannello web di configurazione (solo libreria standard, nessun JavaScript).

Fa le stesse cose di `./manager` (creare un account passo per passo, verificare i collegamenti, modificare la personalità,
riavviare, mettere da parte un account) ma da browser. Si accende solo se nell'ambiente c'è PANEL_PASSWORD.

Sicurezza:
- la password sta in .env (mai a schermo); il confronto è a tempo costante; dopo 5 errori il login si blocca per 5 minuti;
- sessione in un cookie HttpOnly + SameSite=Strict (Secure dietro HTTPS); ogni modulo ha un codice anti-CSRF;
- controllo dell'indirizzo richiesto (Host): contro il DNS rebinding sono ammessi solo gli indirizzi in PANEL_ALLOWED_HOSTS
  (predefinito: localhost, 127.0.0.1);
- niente JavaScript, niente risorse esterne: la Content-Security-Policy blocca tutto tranne il foglio di stile del pannello (static/panel.css, Tailwind già compilato);
- i segreti si scrivono ma non si mostrano mai: i campi dei token sono sempre vuoti e dicono solo se c'è un valore.
Ascolta solo in locale sul server (compose: 127.0.0.1): per usarlo da fuori serve un tunnel SSH o un proxy HTTPS tuo.
"""
import hashlib
import hmac
import html
import http.server
import json
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse

from . import accounts, config as cfgmod, logbuf

SESSION_SECONDS = 8 * 3600
MAX_BODY = 64 * 1024
MAX_UPLOAD = 26 * 1024 * 1024  # solo per il caricamento di documenti nella Biblioteca (25 MB di file + il resto del modulo)
FAIL_LIMIT, FAIL_WINDOW = 5, 300
H = html.escape

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# ---- piccoli componenti HTML (classi Tailwind; i testi di label/help sono sempre fissi, mai dati dell'utente) ----
INPUT = ("block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 shadow-sm focus:border-indigo-500 "
         "focus:outline-none focus:ring-2 focus:ring-indigo-200 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100")
BTN = {
    "primary": "inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white shadow-sm hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-300",
    "ghost": "inline-flex items-center rounded-lg border border-slate-300 px-4 py-2 font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800",
    "danger": "inline-flex items-center rounded-lg bg-red-600 px-4 py-2 font-medium text-white hover:bg-red-500 focus:outline-none focus:ring-2 focus:ring-red-300",
}
PILL = {
    "ok": "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    "no": "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
    "mu": "bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-600",
}
HELP = "mt-1 text-sm text-slate-500 dark:text-slate-400"


def btn(text, kind="primary", name="", value="1"):
    n = f' name="{name}" value="{value}"' if name else ""
    return f'<button class="{BTN[kind]}"{n}>{H(text)}</button>'


def link(text, href, kind="primary"):
    return f'<a class="{BTN[kind]}" href="{H(href)}">{H(text)}</a>'


def pill(text, tone="mu"):
    return f'<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-sm font-medium {PILL[tone]}">{H(text)}</span>'


def field(label, name, value="", help="", kind="text", required=False):
    ac = ' autocomplete="off"' if kind == "password" else ""
    r = " required" if required else ""
    h = f'<p class="{HELP}">{help}</p>' if help else ""
    return (f'<div class="mt-4"><label class="block font-medium">{label}</label>{h}'
            f'<input class="{INPUT} mt-1" type="{kind}" name="{name}" value="{H(value)}"{ac}{r}></div>')


def area(label, name, value="", help="", rows=4):
    h = f'<p class="{HELP}">{help}</p>' if help else ""
    return (f'<div class="mt-4"><label class="block font-medium">{label}</label>{h}'
            f'<textarea class="{INPUT} mt-1" name="{name}" rows="{rows}">{H(value)}</textarea></div>')


def card(title, desc, inner, ident="", tone=""):
    ring = "border-red-200 dark:border-red-900" if tone == "danger" else "border-slate-200 dark:border-slate-700"
    i = f' id="{ident}"' if ident else ""
    d = f'<p class="mt-1 text-slate-600 dark:text-slate-300">{desc}</p>' if desc else ""
    t = f'<h2 class="text-lg font-semibold">{title}</h2>' if title else ""
    return f'<section{i} class="mt-6 scroll-mt-4 rounded-2xl border {ring} bg-white p-5 shadow-sm dark:bg-slate-800">{t}{d}{inner}</section>'


def flash(msg="", err=""):
    out = ""
    if msg:
        out += f'<div role="status" class="mt-4 rounded-lg border-l-4 border-emerald-500 bg-emerald-50 px-4 py-3 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-100">{H(msg)}</div>'
    if err:
        out += f'<div role="alert" class="mt-4 rounded-lg border-l-4 border-red-500 bg-red-50 px-4 py-3 text-red-900 dark:bg-red-900/30 dark:text-red-100">{H(err)}</div>'
    return out


def page(title: str, body: str, csrf: str = "", logged: bool = True) -> str:
    nav = ""
    if logged:
        nav = ('<header class="border-b border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800"><div class="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">'
               '<a href="/" class="text-lg font-bold tracking-tight">EDITH</a>'
               f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{H(csrf)}">'
               '<button class="text-sm text-slate-600 underline hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">Esci</button></form></div></header>')
    return ('<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{H(title)} · EDITH</title><link rel="stylesheet" href="/static/panel.css"></head>'
            '<body class="min-h-screen bg-slate-50 text-base leading-relaxed text-slate-900 antialiased dark:bg-slate-900 dark:text-slate-100">'
            f'{nav}<main class="mx-auto max-w-3xl px-4 pb-16 pt-6">{body}</main></body></html>')


def update_env(path: str, updates: dict, remove=()) -> None:
    """Riscrive account.env cambiando solo le chiavi indicate (le altre righe restano com'erano). Permessi 600, scrittura atomica."""
    lines = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        pass
    done, out = set(), []
    for ln in lines:
        k = ln.split("=", 1)[0].strip() if "=" in ln and not ln.lstrip().startswith("#") else None
        if k in remove:
            continue
        if k in updates:
            out.append(f"{k}={updates[k]}")
            done.add(k)
        elif ln != "" or out:
            out.append(ln)
    while out and out[-1] == "":
        out.pop()
    for k, v in updates.items():
        if k not in done:
            out.append(f"{k}={v}")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def save_profile(path: str, form: dict) -> None:
    """Aggiorna solo i campi modificabili dal pannello; gli altri (kb, lavori, utenti, tastiera...) restano intatti."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    for k in ("proprietario", "ambito", "identita", "benvenuto"):
        data[k] = (form.get(k) or "").strip()
    data["regole_extra"] = [r.strip() for r in (form.get("regole_extra") or "").replace("\r", "").split("\n") if r.strip()]
    for k in ("strumenti_spenti", "lavori_spenti"):
        data[k] = [x.strip() for x in (form.get(k) or "").split(",") if x.strip()]
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".profile-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def system_info():
    """Risorse del contenitore (dal sistema Linux, senza programmi esterni): coppie (nome, valore) da mostrare."""
    out = []
    try:
        with open("/proc/uptime") as f:
            sec = int(float(f.read().split()[0]))
        out.append(("Acceso da", f"{sec // 86400} g {sec % 86400 // 3600} h" if sec >= 86400 else f"{sec // 3600} h {sec % 3600 // 60} min"))
    except (OSError, ValueError, IndexError):
        pass
    try:
        with open("/proc/self/status") as f:
            for ln in f:
                if ln.startswith("VmRSS:"):
                    out.append(("Memoria usata", f"{int(ln.split()[1]) // 1024} MB"))
    except (OSError, ValueError):
        pass
    try:
        out.append(("Carico CPU", " ".join(f"{x:.2f}" for x in os.getloadavg())))
    except (OSError, AttributeError):
        pass
    try:
        st = os.statvfs("/data")
        out.append(("Spazio libero", f"{st.f_bavail * st.f_frsize // 2 ** 20} MB"))
    except (OSError, AttributeError):
        pass
    out.append(("Thread attivi", str(threading.active_count())))
    return out or [("Stato", "non disponibile")]


class Panel:
    def __init__(self, password: str, accounts_dir: str, data_root: str, env: dict = None, control=None, checks: dict = None,
                 allowed_hosts=None, ext_root: str = None, ext_ask=None, ext_fetch=None, lib_fetch=None, lib_extract=None):
        self.accounts_dir, self.data_root = accounts_dir, data_root
        self.ext_root = ext_root or (env or os.environ).get("EXTENSIONS_DIR", "/extensions")  # estensioni: FUORI dal contenitore
        self.ext_ask, self.ext_fetch = ext_ask, ext_fetch  # (solo per i test) IA e rete simulate
        self.lib_fetch, self.lib_extract = lib_fetch, lib_extract  # (solo per i test) lettura di pagine web e di PDF simulata
        self.env = dict(os.environ if env is None else env)
        self.control = control
        self.checks = {"telegram": accounts.check_telegram, "owner": accounts.wait_owner, "ai": accounts.check_ai,
                       "ig": accounts.check_instagram, "key": accounts.make_deploy_key}
        self.checks.update(checks or {})
        self.allowed = {h.strip().lower() for h in (allowed_hosts or ["localhost", "127.0.0.1"]) if h.strip()}
        self._salt = secrets.token_bytes(16)
        self._pw = hashlib.scrypt(password.encode(), salt=self._salt, n=2 ** 14, r=8, p=1)
        self.sessions, self.fails = {}, {}
        self.lock = threading.Lock()

    # ----- accesso -----
    def _hash(self, pw: str) -> bytes:
        return hashlib.scrypt(pw.encode(), salt=self._salt, n=2 ** 14, r=8, p=1)

    def locked(self, ip: str) -> bool:
        now = time.time()
        with self.lock:
            f = [t for t in self.fails.get(ip, []) if now - t < FAIL_WINDOW]
            self.fails[ip] = f
            return len(f) >= FAIL_LIMIT

    def login(self, ip: str, pw: str):
        if self.locked(ip):
            return None
        if hmac.compare_digest(self._hash(pw or ""), self._pw):
            sid = secrets.token_urlsafe(32)
            with self.lock:
                self.sessions[sid] = {"csrf": secrets.token_urlsafe(24), "exp": time.time() + SESSION_SECONDS, "draft": {}}
                self.fails.pop(ip, None)
            return sid
        with self.lock:
            self.fails.setdefault(ip, []).append(time.time())
        return None

    def session(self, sid: str):
        with self.lock:
            s = self.sessions.get(sid or "")
            if s and s["exp"] > time.time():
                return s
            self.sessions.pop(sid or "", None)
        return None

    # ----- dati -----
    def accounts(self):
        errs = []
        cfgs = cfgmod.load_accounts(self.env, self.accounts_dir, self.data_root, errors=errs)
        return cfgs, errs

    def account(self, slug: str):
        if not cfgmod.SLUG.match(slug or ""):
            return None
        for c in self.accounts()[0]:
            if c.slug == slug:
                return c
        return None

    def stats(self, cfg) -> dict:
        import sqlite3
        out = {"bot": "", "messaggi": None}
        p = os.path.join(cfg.data_dir, "manager.sqlite")
        if os.path.exists(p):
            c = None
            try:
                c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                r = c.execute("select value from kv where key='bot_username'").fetchone()
                out["bot"] = r[0] if r else ""
                out["messaggi"] = c.execute("select count(*) from messages").fetchone()[0]
            except Exception:
                pass
            finally:
                if c is not None:
                    c.close()
        return out

    # ----- pagine -----
    def _kb(self, cfg) -> bool:
        kbp = self._profile(cfg).get("kb") or {}
        return bool(cfg.kb_repo or kbp.get("repo") or kbp.get("tipo") == "interno")

    def _profile(self, cfg) -> dict:
        try:
            with open(os.path.join(cfg.profile_dir, "profile.json"), encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _own_ai(self, cfg) -> bool:
        return bool(cfgmod.parse_env_file(os.path.join(cfg.profile_dir, "account.env")).get("OMNIROUTE_API_KEY"))

    def dashboard(self, s) -> str:
        cfgs, errs = self.accounts()
        run = self.control.running() if self.control else {}
        bad = "".join(flash(err=f"«{n}» non si avvia: {w}") for n, w in errs)
        cards = ""
        for c in cfgs:
            st = self.stats(c)
            on = run.get(c.slug)
            stato = pill("attivo", "ok") if on else (pill("fermo", "no") if on is not None else pill("stato sconosciuto"))
            chips = " ".join((pill("Instagram collegato", "ok") if c.ig_token else pill("Instagram non collegato"),
                              pill("archivio collegato", "ok") if self._kb(c) else pill("senza archivio"),
                              pill(f'{st["messaggi"]} messaggi') if st["messaggi"] is not None else pill("nessun messaggio")))
            bot = f'@{H(st["bot"])} su Telegram' if st["bot"] else "bot non ancora avviato"
            cards += (f'<a href="/account/{H(c.slug)}" class="mt-4 block rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-400 hover:shadow dark:border-slate-700 dark:bg-slate-800">'
                      f'<div class="flex items-center justify-between gap-3"><h2 class="text-lg font-semibold">{H(c.slug)}</h2>{stato}</div>'
                      f'<p class="mt-1 text-slate-600 dark:text-slate-300">{bot}</p><div class="mt-3 flex flex-wrap gap-2">{chips}</div>'
                      '<p class="mt-3 text-sm font-medium text-indigo-600 dark:text-indigo-400">Apri e modifica →</p></a>')
        if not cfgs:
            cards = card("Non c'è ancora nessun account", "Un account è un profilo social (una persona, una band, un'attività) con il suo bot Telegram. Crealo qui sotto: ti guido passo passo.", "")
        intro = ('<h1 class="text-2xl font-bold">I tuoi account</h1>'
                 '<p class="mt-2 text-slate-600 dark:text-slate-300">Ogni account è un manager social che ti scrive su Telegram. '
                 'Clicca un account per cambiare come parla, chi può usarlo e le chiavi che usa.</p>')
        actions = ('<div class="mt-6 flex flex-wrap gap-3">' + link("+ Nuovo account", "/accounts/new") + link("Stato e registro", "/system", "ghost") + "</div>"
                   f'<p class="{HELP}">«Nuovo account» ti guida in 5 passi (circa 5 minuti). «Stato e registro» mostra cosa sta facendo il programma.</p>')
        return page("Account", intro + bad + actions + cards, s["csrf"])

    def account_page(self, s, cfg, msg: str = "", err: str = "") -> str:
        p = self._profile(cfg)
        csrf = f'<input type="hidden" name="csrf" value="{H(s["csrf"])}">'
        on = (self.control.running().get(cfg.slug) if self.control else None)
        st = self.stats(cfg)
        ids = ", ".join(str(i) for i in cfg.allowed_user_ids)
        a = f"/account/{H(cfg.slug)}"
        sezioni = (("personalita", "Personalità"), ("proprietari", "Chi può usarlo"), ("collegamenti", "Chiavi e collegamenti"), ("gestione", "Gestione"))
        bot = ("Bot Telegram: @" + H(st["bot"])) if st["bot"] else "Bot non ancora avviato"
        top = ('<a href="/" class="text-sm text-indigo-600 hover:underline dark:text-indigo-400">← Tutti gli account</a>'
               f'<div class="mt-2 flex items-center gap-3"><h1 class="text-2xl font-bold">{H(cfg.slug)}</h1>{pill("attivo", "ok") if on else pill("fermo", "no")}</div>'
               f'<p class="mt-1 text-slate-600 dark:text-slate-300">{bot}</p>'
               '<nav class="mt-4 flex flex-wrap gap-2 text-sm">'
               + "".join(f'<a href="#{i}" class="rounded-full border border-slate-300 px-3 py-1 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800">{t}</a>' for i, t in sezioni) + "</nav>"
               + self._ext_links(cfg))
        personalita = card("Personalità", "Come parla il manager e cosa conta per questo account. <b>Le modifiche valgono subito</b>, senza riavviare.",
            f'<form method="post" action="{a}/profile">{csrf}'
            + field("Come ti chiama il manager", "proprietario", p.get("proprietario", ""), "Il nome con cui si rivolge a te. Esempio: <i>Marta</i>.")
            + area("Chi è il manager e per chi lavora", "identita", p.get("identita", ""), "Una descrizione libera. Se la scrivi, sostituisce la presentazione di base; le regole di sicurezza restano sempre. Esempio: <i>Sei il manager social di una band indie di Milano…</i>")
            + area("Regole in più", "regole_extra", chr(10).join(p.get("regole_extra") or []), "Una regola per riga. Esempio: <i>Non proporre mai collaborazioni a pagamento.</i>")
            + field("Cosa conta come pertinente", "ambito", p.get("ambito", ""), "Serve a scegliere cosa tenere quando riceve contenuti. Vuoto = musica. Esempio: <i>cucina e ricette</i>.")
            + field("Frase di benvenuto", "benvenuto", p.get("benvenuto", ""), "Quello che il bot risponde quando scrivi /start.")
            + field("Strumenti da spegnere", "strumenti_spenti", ", ".join(p.get("strumenti_spenti") or []), "Nomi separati da virgola. Vuoto = tutti attivi. Esempio: <i>web_browser, grafico</i>.")
            + field("Lavori automatici da spegnere", "lavori_spenti", ", ".join(p.get("lavori_spenti") or []), "Compiti che il manager fa da solo (report, promemoria…). Vuoto = tutti attivi.")
            + f'<div class="mt-5">{btn("Salva (vale subito)")}</div></form>', "personalita")
        proprietari = card("Chi può usarlo", "Solo gli utenti Telegram elencati qui possono parlare con questo bot. Gli altri vengono ignorati.",
            f'<form method="post" action="{a}/owners">{csrf}'
            + field("ID Telegram", "owners", ids, "Numeri separati da virgola. Per scoprire il tuo ID scrivi a <b>@userinfobot</b> su Telegram. Esempio: <i>123456789, 987654321</i>.")
            + f'<div class="mt-5">{btn("Salva e riavvia")}</div></form>', "proprietari")
        collegamenti = card("Chiavi e collegamenti",
            "Le chiavi si scrivono ma <b>non si mostrano mai</b>, nemmeno a te. Lascia il campo vuoto per non cambiarle: ogni valore nuovo viene controllato prima di essere salvato.",
            f'<p class="mt-4">Instagram: {pill("collegato", "ok") if cfg.ig_token else pill("non collegato")} &nbsp; Chiave IA: {pill("propria", "ok") if self._own_ai(cfg) else pill("quella comune del server")}</p>'
            f'<form method="post" action="{a}/secrets">{csrf}'
            + field("Nuovo token Instagram", "ig_token", "", "Si ottiene da Meta (guida: docs/INSTAGRAM.md). Solo lettura.", "password")
            + field("ID account Instagram", "ig_user_id", cfg.ig_user_id, "Un numero lungo, non il nome utente.")
            + field("Nuova chiave IA propria", "ai_key", "", "Solo se questo account deve usare una chiave diversa da quella comune.", "password")
            + f'<div class="mt-5">{btn("Controlla e salva")}</div></form>', "collegamenti")
        gestione = card("Gestione", "Controllare che tutto funzioni, oppure riavviare.",
            f'<div class="mt-4 flex flex-wrap gap-3"><form method="post" action="{a}/check">{csrf}{btn("Verifica i collegamenti", "ghost")}</form>'
            f'<form method="post" action="{a}/restart">{csrf}{btn("Riavvia questo account", "ghost")}</form></div>'
            f'<p class="{HELP}">«Verifica» prova Telegram, intelligenza artificiale e Instagram e dice cosa non va. «Riavvia» richiede fino a 30 secondi.</p>', "gestione")
        pericolo = card("Metti da parte", "Il bot si ferma e l'account sparisce da questa lista. <b>I dati non vengono cancellati</b>: restano sul server e si possono recuperare.",
            f'<form method="post" action="{a}/remove">{csrf}<label class="mt-4 flex items-start gap-2"><input type="checkbox" name="conferma" value="si" class="mt-1.5">'
            f'<span>Sì, voglio mettere da parte «{H(cfg.slug)}»</span></label><div class="mt-4">{btn("Metti da parte", "danger")}</div></form>', "", "danger")
        return page(cfg.slug, top + flash(msg, err) + personalita + proprietari + collegamenti + gestione + pericolo, s["csrf"])

    def _ext_links(self, cfg) -> str:
        """Collegamenti alle estensioni, a «Cosa ha imparato» e al catalogo, con il numero di proposte da approvare."""
        from . import panel_ext
        n = panel_ext.pending_count(self, cfg)
        a = f"/account/{H(cfg.slug)}"
        cls = "rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-1 font-medium text-indigo-800 hover:bg-indigo-100 dark:border-indigo-700 dark:bg-indigo-950 dark:text-indigo-200"
        badge = f' <span class="rounded-full bg-red-600 px-2 text-xs text-white">{n}</span>' if n else ""
        return (f'<nav class="mt-3 flex flex-wrap gap-2 text-sm"><a class="{cls}" href="{a}/estensioni">Estensioni{badge}</a>'
                f'<a class="{cls}" href="{a}/lezioni">Cosa ha imparato</a><a class="{cls}" href="{a}/archivio">Archivio</a><a class="{cls}" href="{a}/biblioteca">Biblioteca</a><a class="{cls}" href="{a}/esperti">Esperti</a><a class="{cls}" href="{a}/catalogo">Catalogo</a></nav>')

    def check_page(self, s, cfg) -> str:
        res = ""
        hint = {"Telegram": "Controlla il codice del bot in «Chiavi e collegamenti».",
                "Intelligenza artificiale": "Controlla la chiave IA e che il servizio sia raggiungibile.",
                "Instagram": "Il token potrebbe essere scaduto: generane uno nuovo."}
        for what, fn in (("Telegram", lambda: "@" + self.checks["telegram"](cfg.telegram_token)),
                         ("Intelligenza artificiale", lambda: self.checks["ai"](cfg.ai_base_url, cfg.ai_api_key)),
                         ("Instagram", lambda: self.checks["ig"](cfg.ig_token, cfg.ig_user_id, cfg.graph_version) if cfg.ig_token else "non collegato (facoltativo)")):
            try:
                res += f'<li class="mt-3 flex gap-3"><span class="mt-0.5">{pill("ok", "ok")}</span><span><b>{H(what)}</b>: {H(str(fn()))}</span></li>'
            except accounts.WizardError as e:
                res += (f'<li class="mt-3 flex gap-3"><span class="mt-0.5">{pill("errore", "no")}</span><span><b>{H(what)}</b>: {H(str(e))}'
                        f'<br><span class="{HELP}">{hint[what]}</span></span></li>')
        return page("Verifica", f'<a href="/account/{H(cfg.slug)}" class="text-sm text-indigo-600 hover:underline dark:text-indigo-400">← Torna a {H(cfg.slug)}</a>'
                    f'<h1 class="mt-2 text-2xl font-bold">Verifica di {H(cfg.slug)}</h1>' + card("", "", f'<ul class="list-none">{res}</ul>'), s["csrf"])

    # ----- stato e registro (come ./manager status e logs) -----
    def system_page(self, s, msg: str = "", err: str = "") -> str:
        cfgs, _ = self.accounts()
        run = self.control.running() if self.control else {}
        csrf = f'<input type="hidden" name="csrf" value="{H(s["csrf"])}">'
        righe = "".join(f'<tr class="border-t border-slate-200 dark:border-slate-700"><td class="py-2 pr-3 font-medium">{H(c.slug)}</td><td>'
                        + (pill("attivo", "ok") if run.get(c.slug) else (pill("fermo", "no") if run.get(c.slug) is not None else pill("?"))) + "</td></tr>" for c in cfgs)
        info = "".join(f'<div class="rounded-lg bg-slate-50 p-3 dark:bg-slate-900"><div class="text-sm text-slate-500 dark:text-slate-400">{H(k)}</div><div class="font-semibold">{H(v)}</div></div>'
                       for k, v in system_info())
        log = logbuf.text(self._secrets()) or "(nessuna riga ancora)"
        body = ('<a href="/" class="text-sm text-indigo-600 hover:underline dark:text-indigo-400">← Tutti gli account</a>'
                '<h1 class="mt-2 text-2xl font-bold">Stato e registro</h1>' + flash(msg, err)
                + card("Risorse", "Quanto usa il programma in questo momento.", f'<div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">{info}</div>')
                + card("Account", "", f'<table class="mt-2 w-full text-left"><tbody>{righe}</tbody></table>'
                       f'<form method="post" action="/system/restart" class="mt-4">{csrf}{btn("Riavvia tutti gli account", "ghost")}</form>'
                       f'<p class="{HELP}">Riavvia ogni bot. Ci vogliono fino a 30 secondi.</p>')
                + card("Registro", "Le ultime righe di quello che il programma scrive (come <code>./manager logs</code>). Token e chiavi sono oscurati. Ricarica la pagina per aggiornare.",
                       f'<pre class="mt-4 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{H(log)}</pre>'))
        return page("Stato e registro", body, s["csrf"])

    def _secrets(self):
        """Valori da oscurare nel registro: token e chiavi di tutti gli account e della configurazione comune."""
        vals = set()
        cfgs, _ = self.accounts()
        for c in cfgs:
            for k, v in cfgmod.parse_env_file(os.path.join(c.profile_dir, "account.env")).items():
                if any(w in k.upper() for w in ("TOKEN", "KEY", "PASSWORD", "SECRET")) and len(v) >= 6:
                    vals.add(v)
        for k in ("OMNIROUTE_API_KEY", "PANEL_PASSWORD", "BROWSER_TOKEN"):
            if len(self.env.get(k) or "") >= 6:
                vals.add(self.env[k])
        return vals

    # ----- creazione guidata -----
    def wizard(self, s, form: dict) -> str:
        d = s["draft"]
        csrf = f'<input type="hidden" name="csrf" value="{H(s["csrf"])}">'
        step, err = form.get("step", "start"), ""

        head = self._head
        try:
            if step == "start" and form.get("go"):
                nome = (form.get("nome") or "").strip()
                slug = accounts.slugify(form.get("slug") or nome)
                if not nome or not cfgmod.SLUG.match(slug) or os.path.exists(os.path.join(self.accounts_dir, slug)):
                    raise accounts.WizardError("Nome mancante, non valido o già usato (il nome breve: 2-30 caratteri, minuscole, numeri, trattini).")
                d.clear()
                d.update(nome=nome, slug=slug, proprietario=(form.get("proprietario") or "").strip() or nome,
                         descrizione=(form.get("descrizione") or "").strip(), env={})
                step = "token"
            elif step == "token" and form.get("go"):
                tok = (form.get("token") or "").strip()
                d["username"] = self.checks["telegram"](tok)
                d["env"]["TELEGRAM_BOT_TOKEN"] = tok
                step = "owner"
            elif step == "owner" and form.get("manual"):
                oid = (form.get("manual_id") or "").strip()
                if not oid.isdigit() or not 4 <= len(oid) <= 15:
                    raise accounts.WizardError("L'ID Telegram è un numero (di solito 8-10 cifre).")
                d["owner"] = {"id": int(oid), "nome": "", "username": ""}
                d["env"]["ALLOWED_TELEGRAM_USER_ID"] = oid
                step = "ai"
            elif step == "owner" and form.get("check"):
                try:
                    d["found"] = self.checks["owner"](d["env"]["TELEGRAM_BOT_TOKEN"], 8)
                except accounts.WizardError:
                    raise accounts.WizardError("Non ho ancora ricevuto nessun messaggio: scrivi «ciao» al bot e riprova.")
                step = "owner_ok"
            elif step == "owner_ok" and form.get("yes"):
                f = d.pop("found")
                d["owner"] = f
                d["env"]["ALLOWED_TELEGRAM_USER_ID"] = str(f["id"])
                step = "ai"
            elif step == "owner_ok":
                d.pop("found", None)
                step = "owner"
            elif step == "ai" and form.get("go"):
                if form.get("modo") == "propria" or not (self.env.get("OMNIROUTE_API_KEY") or "").strip():
                    base = self.env.get("OMNIROUTE_BASE_URL", "") or (form.get("base") or "").strip()
                    key = (form.get("key") or "").strip()
                    self.checks["ai"](base, key)
                    d["env"]["OMNIROUTE_API_KEY"] = key
                    if base != self.env.get("OMNIROUTE_BASE_URL", ""):
                        d["env"]["OMNIROUTE_BASE_URL"] = base
                step = "ig"
            elif step == "ig" and form.get("go"):
                if (form.get("ig_token") or "").strip():
                    tok, uid = form["ig_token"].strip(), (form.get("ig_user_id") or "").strip()
                    d["ig_info"] = self.checks["ig"](tok, uid)
                    d["env"]["META_IG_TOKEN"], d["env"]["META_IG_USER_ID"] = tok, uid
                step = "kb"
            elif step == "kb" and form.get("go"):
                repo = (form.get("repo") or "").strip()
                if repo:
                    tmp = os.path.join(self.accounts_dir, f".kbkey-{d['slug']}")
                    d["pub"] = self.checks["key"](tmp)
                    with open(tmp, encoding="utf-8") as f:
                        d["kbkey"] = f.read()
                    os.remove(tmp)
                    d["env"]["KB_REPO"] = repo
                step = "fine"
            elif step == "fine" and form.get("go"):
                desc = d.get("descrizione", "")
                prof = {"proprietario": d["proprietario"], "ambito": "",
                        "identita": (f"Sei il manager social digitale di {d['proprietario']}: {desc}. Lavori con la sua approvazione. "
                                     "Parli SEMPRE in italiano semplice e naturale, come una persona.") if desc else "",
                        "regole_extra": [], "utenti": {d["env"]["ALLOWED_TELEGRAM_USER_ID"]: d["proprietario"]},
                        "benvenuto": f"Ciao {d['proprietario']}! Sono il manager social di {d['nome']}."}
                if d["env"].get("KB_REPO"):
                    prof["kb"] = {"repo": d["env"]["KB_REPO"], "branch": "main", "write_branch": "manager"}
                accounts.write_account(self.accounts_dir, d["slug"], d["env"], prof, d.get("kbkey"))
                pub, slug, user = d.get("pub", ""), d["slug"], d["username"]
                d.clear()
                if self.control:
                    self.control.rescan.set()
                extra = card("Ultimo passo: l'archivio", "Nelle impostazioni del repository aggiungi questa chiave pubblica come «Deploy key», con il permesso di scrittura:", f'<pre class="mt-3 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-slate-100 p-3 text-xs dark:bg-slate-900">{H(pub)}</pre>') if pub else ""
                return page("Fatto", '<h1 class="text-2xl font-bold">Account creato ✓</h1>' + card("", f"Parte da solo entro 30 secondi. Poi apri <b>@{H(user)}</b> su Telegram e scrivi /start.", "") + extra
                            + '<div class="mt-6">' + link("Apri l'account", f"/account/{slug}") + "</div>", s["csrf"])
        except accounts.WizardError as e:
            err = str(e)
        except OSError as e:
            err = f"Non riesco a scrivere i file ({type(e).__name__})."
        d["_step"] = step
        return self._wizard_form(s, step, err, csrf, head)

    @staticmethod
    def _head(n, t) -> str:
        bar = "".join(f'<div class="h-1.5 flex-1 rounded-full {"bg-indigo-600" if i <= n else "bg-slate-200 dark:bg-slate-700"}"></div>' for i in range(1, 6))
        return (f'<a href="/" class="text-sm text-indigo-600 hover:underline dark:text-indigo-400">← Annulla e torna agli account</a>'
                f'<div class="mt-3 flex gap-1.5">{bar}</div>'
                f'<p class="mt-3 text-sm font-medium text-slate-500 dark:text-slate-400">Nuovo account · passo {n}/5</p>'
                f'<h1 class="text-2xl font-bold">{H(t)}</h1>')

    def _wizard_form(self, s, step, err, csrf, head) -> str:
        d = s["draft"]
        e = flash(err=err) if err else ""

        def f(buttons, inner, title="", desc=""):
            return card(title, desc, f'{e}<form method="post" action="/accounts/new">{csrf}<input type="hidden" name="step" value="{step}">{inner}<div class="mt-5 flex flex-wrap gap-3">{buttons}</div></form>')
        if step == "start":
            return page("Nuovo account", head(1, "Chi è") + f(btn("Avanti", name="go"),
                field("Nome dell'account", "nome", "", "Una persona, una band, un'attività. Esempio: <i>Luna Rossa</i>.", required=True)
                + field("Nome breve per i file (facoltativo)", "slug", "", "Solo minuscole, numeri e trattini. Se lo lasci vuoto lo scelgo io. Esempio: <i>luna-rossa</i>.")
                + field("Come ti deve chiamare il manager", "proprietario", "", "Esempio: <i>Marta</i>.")
                + field("Una frase su chi sei e cosa fai (facoltativo)", "descrizione", "", "Aiuta il manager a capire il contesto. Esempio: <i>band indie di Milano</i>."),
                "", "Per iniziare servono solo un nome e come vuoi essere chiamato. Il resto si può cambiare dopo."), s["csrf"])
        if step == "token":
            return page("Bot Telegram", head(2, "Il bot Telegram") + f(btn("Verifica", name="go"),
                '<ol class="mt-4 list-decimal space-y-1 pl-5"><li>Apri Telegram e scrivi a <b>@BotFather</b>.</li><li>Manda <code>/newbot</code> e scegli un nome.</li>'
                '<li>Copia il codice lungo che ti dà e incollalo qui sotto.</li></ol>'
                + field("Codice del bot", "token", "", "Si vede come <i>123456:ABC…</i>. Non viene mai mostrato dopo il salvataggio.", "password", True),
                "", "Ogni account parla con te tramite un suo bot Telegram."), s["csrf"])
        if step in ("owner", "owner_ok"):
            if step == "owner_ok":
                fo = d.get("found") or {}
                chi = H(fo.get("nome", "")) + (f' (@{H(fo.get("username", ""))})' if fo.get("username") else "")
                return page("Sei tu?", head(2, "Sei tu?") + f(btn("Sì, sono io", name="yes") + btn("No, riprova", "ghost", "no"),
                    f'<p class="mt-4">Ho ricevuto un messaggio da <b>{chi}</b>, ID <b>{H(str(fo.get("id", "")))}</b>. Se sei tu, solo questa persona potrà usare il bot.</p>'), s["csrf"])
            return page("Chi sei", head(2, "Chi può usarlo") + f(btn("Ho scritto, controlla", name="check"),
                f'<p class="mt-4">Apri <b>@{H(d.get("username", ""))}</b> su Telegram e scrivigli «ciao». Così capisco chi sei: solo tu potrai usarlo.</p>',
                "Modo semplice", "Poi premi il pulsante qui sotto.")
                + f(btn("Usa questo ID", "ghost", "manual"),
                    field("ID Telegram", "manual_id", "", "Solo se preferisci inserirlo a mano: lo vedi scrivendo a <b>@userinfobot</b>. È un numero di 8-10 cifre."),
                    "Oppure a mano"), s["csrf"])
        if step == "ai":
            comune = bool((self.env.get("OMNIROUTE_API_KEY") or "").strip())
            scelta = ('<div class="mt-4 space-y-2"><label class="flex items-start gap-2"><input type="radio" name="modo" value="comune" checked class="mt-1.5"><span>Usa la chiave comune del server (consigliato)</span></label>'
                      '<label class="flex items-start gap-2"><input type="radio" name="modo" value="propria" class="mt-1.5"><span>Usa una chiave propria per questo account</span></label></div>') if comune else ""
            base = "" if self.env.get("OMNIROUTE_BASE_URL") else field("Indirizzo del servizio IA", "base", "", "Esempio: <i>https://ai.miodominio.it/v1</i>.")
            return page("IA", head(3, "L'intelligenza artificiale") + f(btn("Avanti", name="go"),
                scelta + base + field("Chiave del servizio IA", "key", "", "Serve solo se scegli la chiave propria.", "password"),
                "", "È il «cervello» del manager. Di solito basta la chiave comune."), s["csrf"])
        if step == "ig":
            return page("Instagram", head(4, "Instagram (facoltativo)") + f(btn("Avanti", name="go"),
                field("Token Instagram", "ig_token", "", "Solo lettura. La guida per ottenerlo è in <code>docs/INSTAGRAM.md</code>.", "password")
                + field("ID dell'account Instagram", "ig_user_id", "", "Un numero lungo, non il nome utente."),
                "", "Serve a leggere statistiche e post. Il manager non pubblica mai da solo. Puoi saltare e collegarlo dopo: lascia i campi vuoti."), s["csrf"])
        if step == "kb":
            return page("Archivio", head(5, "Archivio di conoscenza (facoltativo)") + f(btn("Avanti", name="go"),
                field("Indirizzo SSH del repository", "repo", "", "Esempio: <i>git@github.com:utente/archivio.git</i>. Lascia vuoto per saltare."),
                "", "Un repository Git con i documenti dell'account (biografia, note, materiali) che il manager può consultare."), s["csrf"])
        riepilogo = (f'<ul class="mt-4 list-disc space-y-1 pl-5"><li>Account: <b>{H(d.get("nome", ""))}</b> ({H(d.get("slug", ""))})</li><li>Bot: @{H(d.get("username", ""))}</li>'
                     f'<li>Proprietario: ID {H(d["env"].get("ALLOWED_TELEGRAM_USER_ID", ""))}</li>'
                     f'<li>Instagram: {H(d.get("ig_info", "non collegato"))}</li><li>Archivio: {"sì" if d["env"].get("KB_REPO") else "no"}</li></ul>')
        return page("Crea", "<h1 class=\"text-2xl font-bold\">Riepilogo</h1>" + f(btn("Crea l'account", name="go"), riepilogo, "", "Controlla che sia tutto giusto. Dopo la creazione l'account parte da solo."), s["csrf"])

    # ----- azioni -----
    def do_profile(self, cfg, form):
        save_profile(os.path.join(cfg.profile_dir, "profile.json"), form)

    def do_owners(self, cfg, form) -> str:
        ids = [x.strip() for x in (form.get("owners") or "").split(",") if x.strip()]
        if not ids or not all(x.isdigit() and 4 <= len(x) <= 15 for x in ids):
            return "Servono uno o più ID Telegram numerici, separati da virgola."
        update_env(os.path.join(cfg.profile_dir, "account.env"), {"ALLOWED_TELEGRAM_USER_ID": ",".join(ids)})
        return ""

    def do_secrets(self, cfg, form) -> str:
        up, rm = {}, []
        if (form.get("ig_token") or "").strip():
            uid = (form.get("ig_user_id") or cfg.ig_user_id).strip()
            try:
                self.checks["ig"](form["ig_token"].strip(), uid, cfg.graph_version)
            except accounts.WizardError as e:
                return str(e)
            up["META_IG_TOKEN"], up["META_IG_USER_ID"] = form["ig_token"].strip(), uid
        elif (form.get("ig_user_id") or "").strip() and form["ig_user_id"].strip() != cfg.ig_user_id:
            up["META_IG_USER_ID"] = form["ig_user_id"].strip()
        if (form.get("ai_key") or "").strip():
            try:
                self.checks["ai"](cfg.ai_base_url, form["ai_key"].strip())
            except accounts.WizardError as e:
                return str(e)
            up["OMNIROUTE_API_KEY"] = form["ai_key"].strip()
        if up or rm:
            update_env(os.path.join(cfg.profile_dir, "account.env"), up, rm)
        return ""

    def do_remove(self, cfg) -> str:
        dst = os.path.join(self.accounts_dir, f".{cfg.slug}.rimosso-{time.strftime('%Y-%m-%d')}")
        os.rename(os.path.join(self.accounts_dir, cfg.slug), dst)
        return f"Account «{cfg.slug}» messo da parte. Il suo bot si ferma al prossimo riavvio; i dati restano in {self.data_root}/{cfg.slug}."


def make_handler(panel: Panel):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "EDITH"
        sys_version = ""

        def log_message(self, *a):  # niente indirizzi né dati nei log
            pass

        # --- utilità ---
        def _host_ok(self) -> bool:
            h = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
            return h in panel.allowed

        def _cookie(self):
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "edith_sid":
                    return v
            return ""

        def _send(self, code, body, headers=None):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _css(self):
            try:
                with open(os.path.join(STATIC_DIR, "panel.css"), "rb") as f:
                    data = f.read()
            except OSError:
                return self._send(404, "Non trovato")
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, to, headers=None):
            self.send_response(303)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def _form(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return None
            q = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True)
            return {k: v[0] for k, v in q.items()}

        def _multipart(self, ctype: str):
            """Modulo con file allegato (solo Biblioteca). Ritorna (campi, file) oppure None se è troppo grande."""
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                return None
            import email.parser
            import email.policy
            raw = self.rfile.read(n)
            msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
            campi, files = {}, {}
            for part in (msg.iter_parts() if msg.is_multipart() else []):
                nome = part.get_param("name", header="content-disposition")
                dati = part.get_payload(decode=True) or b""
                if part.get_filename() is not None:
                    files[nome] = (part.get_filename(), dati)
                else:
                    campi[nome] = dati.decode("utf-8", "replace")
            return campi, files

        def _login_page(self, err=""):
            e = flash(err=err)
            form = ('<form method="post" action="/login">' + field("Password", "password", "", "È la riga PANEL_PASSWORD del file .env sul server.", "password", True)
                    + f'<div class="mt-5">{btn("Entra")}</div></form>')
            return page("Accesso", '<div class="mx-auto mt-16 max-w-sm"><h1 class="text-3xl font-bold tracking-tight">EDITH</h1>'
                        '<p class="mt-1 text-slate-600 dark:text-slate-300">Pannello di configurazione. Entra con la password del pannello.</p>' + e + card("", "", form) + "</div>", logged=False)

        # --- richieste ---
        def do_GET(self):
            if not self._host_ok():
                return self._send(421, "Indirizzo non ammesso")
            path = urllib.parse.urlparse(self.path).path
            if path == "/static/panel.css":
                return self._css()
            s = panel.session(self._cookie())
            if path == "/login":
                return self._send(200, self._login_page())
            if not s:
                return self._redirect("/login")
            if path == "/":
                return self._send(200, panel.dashboard(s))
            if path == "/accounts/new":
                s["draft"].clear()
                return self._send(200, panel._wizard_form(s, "start", "", f'<input type="hidden" name="csrf" value="{H(s["csrf"])}">', panel._head))
            if path == "/system":
                return self._send(200, panel.system_page(s))
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "account" and parts[2] in ("estensioni", "lezioni", "catalogo", "esperti", "biblioteca", "archivio"):
                from . import panel_ext
                cfg = panel.account(parts[1])
                if not cfg:
                    return self._send(404, page("Non trovato", "<h1>Account non trovato</h1>", s["csrf"]))
                code, html_ = panel_ext.get(panel, s, cfg, parts[2:], urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
                return self._send(code, html_)
            if len(parts) == 2 and parts[0] == "account":
                cfg = panel.account(parts[1])
                return self._send(200, panel.account_page(s, cfg)) if cfg else self._send(404, page("Non trovato", "<h1>Account non trovato</h1>", s["csrf"]))
            return self._send(404, page("Non trovato", "<h1>Pagina non trovata</h1>", s["csrf"]))

        def _scarta_corpo(self):
            """Rifiuto prima di leggere la richiesta: si svuota un corpo piccolo e si chiude la connessione, così il client
            riceve la risposta invece di una connessione interrotta (succedeva a intermittenza)."""
            self.close_connection = True
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if 0 < n <= 1_000_000:
                    self.rfile.read(n)
            except (ValueError, OSError):
                pass

        def do_POST(self):
            if not self._host_ok():
                self._scarta_corpo()
                return self._send(421, "Indirizzo non ammesso")
            path = urllib.parse.urlparse(self.path).path
            files = {}
            ctype = self.headers.get("Content-Type") or ""
            if ctype.lower().startswith("multipart/form-data"):
                if not re.fullmatch(r"/account/[a-z0-9-]+/biblioteca/file", path):
                    self._scarta_corpo()
                    return self._send(415, "Tipo di richiesta non ammesso")
                if not panel.session(self._cookie()):  # niente lettura di file da chi non ha fatto l'accesso
                    self._scarta_corpo()
                    return self._redirect("/login")
                parsed = self._multipart(ctype)
                if parsed is None:
                    return self._send(413, "File troppo grande (massimo 25 MB)")
                form, files = parsed
            else:
                form = self._form()
            if form is None:
                return self._send(413, "Richiesta troppo grande")
            ip = self.client_address[0]
            if path == "/login":
                if panel.locked(ip):
                    return self._send(429, self._login_page("Troppi tentativi: riprova tra qualche minuto."))
                sid = panel.login(ip, form.get("password", ""))
                if not sid:
                    return self._send(401, self._login_page("Password sbagliata."))
                sec = "; Secure" if (self.headers.get("X-Forwarded-Proto") or "").lower() == "https" else ""
                return self._redirect("/", {"Set-Cookie": f"edith_sid={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}{sec}"})
            s = panel.session(self._cookie())
            if not s:
                return self._redirect("/login")
            if not hmac.compare_digest(form.get("csrf", ""), s["csrf"]):
                return self._send(403, page("Richiesta rifiutata", "<h1>Richiesta rifiutata</h1><p>Ricarica la pagina e riprova.</p>", s["csrf"]))
            if path == "/logout":
                with panel.lock:
                    panel.sessions.pop(self._cookie(), None)
                return self._redirect("/login", {"Set-Cookie": "edith_sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            if path == "/accounts/new":
                return self._send(200, panel.wizard(s, form))
            if path == "/system/restart":
                ok = bool(panel.control and panel.control.restart_all())
                return self._send(200, panel.system_page(s, "Riavvio richiesto per tutti gli account: ci vogliono fino a 30 secondi." if ok else "", "" if ok else "Non posso riavviare da qui."))
            parts = path.strip("/").split("/")
            if len(parts) >= 4 and parts[0] == "account" and parts[2] in ("estensioni", "approvazione", "lezioni", "catalogo", "esperti", "biblioteca", "archivio"):
                from . import panel_ext
                cfg = panel.account(parts[1])
                if not cfg:
                    return self._send(404, page("Non trovato", "<h1>Account non trovato</h1>", s["csrf"]))
                code, html_ = panel_ext.post(panel, s, cfg, parts[2:], form, files)
                return self._send(code, html_)
            if len(parts) == 3 and parts[0] == "account":
                cfg = panel.account(parts[1])
                if not cfg:
                    return self._send(404, page("Non trovato", "<h1>Account non trovato</h1>", s["csrf"]))
                act = parts[2]
                msg = err = ""
                if act == "profile":
                    panel.do_profile(cfg, form)
                    msg = "Salvato: vale da subito."
                elif act == "owners":
                    err = panel.do_owners(cfg, form)
                    if not err:
                        msg = "Salvato. L'account si riavvia."
                        panel.control and panel.control.restart(cfg.slug)
                elif act == "secrets":
                    err = panel.do_secrets(cfg, form)
                    if not err:
                        msg = "Salvato. L'account si riavvia."
                        panel.control and panel.control.restart(cfg.slug)
                elif act == "check":
                    return self._send(200, panel.check_page(s, cfg))
                elif act == "restart":
                    ok = bool(panel.control and panel.control.restart(cfg.slug))
                    msg = "Riavvio richiesto: ci vuole fino a 30 secondi." if ok else "Non posso riavviarlo da qui."
                elif act == "remove":
                    if form.get("conferma") != "si":
                        err = "Spunta la casella per confermare."
                    else:
                        done = panel.do_remove(cfg)
                        return self._send(200, page("Messo da parte", '<h1 class="text-2xl font-bold">Fatto</h1>' + card("", H(done), "") + '<div class="mt-6">' + link("Torna agli account", "/") + "</div>", s["csrf"]))
                else:
                    return self._send(404, page("Non trovato", "<h1>Pagina non trovata</h1>", s["csrf"]))
                cfg = panel.account(parts[1]) or cfg
                return self._send(200, panel.account_page(s, cfg, msg, err))
            return self._send(404, page("Non trovato", "<h1>Pagina non trovata</h1>", s["csrf"]))

    return Handler


def serve(panel: Panel, host: str = "0.0.0.0", port: int = 8080, background: bool = True):
    srv = http.server.ThreadingHTTPServer((host, port), make_handler(panel))
    if background:
        threading.Thread(target=srv.serve_forever, name="panel", daemon=True).start()
    else:
        srv.serve_forever()
    return srv


def start_from_env(control=None, environ=None):
    """Avvia il pannello se c'è PANEL_PASSWORD. Dentro il contenitore ascolta su 0.0.0.0:8080; il compose lo pubblica solo su 127.0.0.1."""
    env = environ if environ is not None else os.environ
    pw = (env.get("PANEL_PASSWORD") or "").strip()
    if not pw:
        return None
    if len(pw) < 12:
        print("pannello NON avviato: PANEL_PASSWORD deve avere almeno 12 caratteri", flush=True)
        return None
    hosts = [h for h in (env.get("PANEL_ALLOWED_HOSTS") or "localhost,127.0.0.1").split(",")]
    p = Panel(pw, env.get("ACCOUNTS_DIR", "/config/accounts"), env.get("DATA_ROOT", "/data"), dict(env), control, allowed_hosts=hosts)
    srv = serve(p, "0.0.0.0", 8080)
    print("pannello web attivo (solo da localhost: tunnel SSH o proxy HTTPS)", flush=True)
    return srv
