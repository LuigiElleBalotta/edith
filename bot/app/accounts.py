"""Gestione degli account da riga di comando (procedura guidata).

  python -m app.accounts add [nome]     crea un account passo per passo (verifica ogni dato prima di salvare)
  python -m app.accounts list           elenca gli account e cosa è collegato
  python -m app.accounts check [nome]   controlla bot Telegram, IA e Instagram (senza mostrare segreti)
  python -m app.accounts remove nome    mette da parte la configurazione (i dati NON si cancellano)

I segreti vengono chiesti in modo nascosto e finiscono solo in `account.env` (permessi 600), mai a schermo né nei log.
Un account nuovo parte da solo entro 30 secondi: non serve riavviare.
"""
import datetime as dt
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import config as cfgmod
from .tg import Tg, TgError

OWNER_WAIT_SECONDS = 180


class WizardError(Exception):
    pass


# ---------- verifiche (rete): ognuna ritorna un'informazione utile o solleva WizardError ----------

def check_telegram(token: str) -> str:
    try:
        me = Tg(token).call("getMe", timeout=15)
    except TgError:
        raise WizardError("Telegram non accetta questo codice. Copialo di nuovo da @BotFather (formato 123456:ABC...).") from None
    if not me.get("is_bot"):
        raise WizardError("Questo non è il codice di un bot.")
    return me.get("username", "")


def wait_owner(token: str, seconds: int = OWNER_WAIT_SECONDS, say=print) -> dict:
    """Aspetta il primo messaggio privato al bot e ne ritorna l'autore (id, nome, username).
    Il messaggio resta in coda: il bot lo leggerà normalmente appena parte."""
    tg = Tg(token)
    end = time.time() + seconds
    while time.time() < end:
        try:
            updates = tg.get_updates(0, 10)
        except TgError:
            time.sleep(2)
            continue
        for u in updates:
            m = u.get("message") or {}
            if (m.get("chat") or {}).get("type") == "private" and (m.get("from") or {}).get("id") and not m["from"].get("is_bot"):
                f = m["from"]
                return {"id": f["id"], "nome": f.get("first_name", ""), "username": f.get("username", "")}
    raise WizardError("Non ho ricevuto nessun messaggio. Puoi riprovare, oppure inserire il tuo ID Telegram a mano.")


def check_ai(base_url: str, key: str) -> str:
    req = urllib.request.Request(base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise WizardError(f"Il servizio IA ha rifiutato la chiave (HTTP {e.code}).") from None
    except Exception as e:
        raise WizardError(f"Il servizio IA non risponde ({type(e).__name__}). Controlla l'indirizzo.") from None
    n = len(data.get("data") or [])
    return f"{n} modelli disponibili" if n else "risponde"


def check_instagram(token: str, user_id: str, version: str = "v23.0") -> str:
    from .instagram import IgError, Instagram
    try:
        p = Instagram(token, user_id, version).profile()
    except IgError as e:
        raise WizardError(f"Instagram non accetta questo token ({e}). Vedi docs/INSTAGRAM.md.") from None
    return f"@{p.get('username')} ({p.get('followers_count')} follower)"


# ---------- scrittura dei file ----------

def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:30]


def write_account(accounts_dir: str, slug: str, env: dict, profile: dict, kbkey: str = None) -> str:
    """Crea la cartella dell'account. account.env è leggibile solo dal proprietario (600)."""
    if not cfgmod.SLUG.match(slug):
        raise WizardError("Il nome deve avere 2-30 caratteri: lettere minuscole, numeri e trattini.")
    d = os.path.join(accounts_dir, slug)
    if os.path.exists(d):
        raise WizardError(f"L'account '{slug}' esiste già.")
    os.makedirs(d, mode=0o700)
    lines = [f"{k}={v}" for k, v in env.items() if v not in ("", None)]
    fd = os.open(os.path.join(d, "account.env"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# Segreti di questo account: non va mai nel repository.\n" + "\n".join(lines) + "\n")
    with open(os.path.join(d, "profile.json"), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if kbkey:
        fd = os.open(os.path.join(d, "kbkey"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(kbkey)
    return d


def make_deploy_key(path: str) -> str:
    """Chiave SSH per l'archivio di conoscenza (solo di questo account). Ritorna la parte pubblica."""
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "manager-bot", "-f", path, "-q"], check=True)
    os.chmod(path, 0o600)
    with open(path + ".pub", encoding="utf-8") as f:
        pub = f.read().strip()
    os.remove(path + ".pub")
    return pub


def public_from_key(path: str) -> str:
    """Parte pubblica di una chiave privata già esistente."""
    out = subprocess.run(["ssh-keygen", "-y", "-f", path], check=True, capture_output=True, text=True)
    return out.stdout.strip()


# ---------- procedura guidata ----------

class IO:
    """Ingresso/uscita sostituibile nei test."""
    def ask(self, q: str, default: str = "") -> str:
        a = input(f"{q}{f' [{default}]' if default else ''}: ").strip()
        return a or default

    def secret(self, q: str) -> str:
        return getpass.getpass(f"{q} (non verrà mostrato): ").strip()

    def yes(self, q: str, default: bool = False) -> bool:
        a = input(f"{q} [{'S/n' if default else 's/N'}]: ").strip().lower()
        return default if not a else a in ("s", "si", "sì", "y", "yes")

    def say(self, text: str = ""):
        print(text, flush=True)


def _retry(io, fn, what: str):
    """Chiede un dato e lo verifica; se non va, lo richiede (max 3 volte)."""
    for _ in range(3):
        try:
            return fn()
        except WizardError as e:
            io.say(f"  ✗ {e}")
    raise WizardError(f"Non riesco a verificare {what}. Riprova più tardi con: python -m app.accounts add")


def add(io: IO = None, env: dict = None, accounts_dir: str = None, check=None) -> str:
    io = io or IO()
    env = env if env is not None else os.environ
    accounts_dir = accounts_dir or env.get("ACCOUNTS_DIR", "/config/accounts")
    c = {"telegram": check_telegram, "owner": wait_owner, "ai": check_ai, "ig": check_instagram, "key": make_deploy_key}
    c.update(check or {})

    io.say("\n=== Nuovo account ===\n")
    nome = io.ask("Come si chiama questo account (una persona, una band, un'attività: il nome con cui lo conosci)")
    slug = slugify(io.ask("Nome breve per i file (lettere, numeri, trattini)", slugify(nome)))
    if not cfgmod.SLUG.match(slug) or os.path.exists(os.path.join(accounts_dir, slug)):
        raise WizardError("Nome non valido o già usato.")
    proprietario = io.ask("Come ti deve chiamare il manager? (il tuo nome)")
    descrizione = io.ask("Descrivi in una frase chi sei e cosa fai (es. «cantautrice pop di Milano» o «pizzeria a Parma»). Invio per saltare")

    io.say("\n1/4  Il bot Telegram")
    io.say("  Su Telegram scrivi a @BotFather: /newbot, scegli un nome, e copia il codice che ti dà.")
    env_out, username = {}, ""

    def _tg():
        nonlocal username
        tok = io.secret("  Codice del bot")
        username = c["telegram"](tok)
        env_out["TELEGRAM_BOT_TOKEN"] = tok
    _retry(io, _tg, "il codice del bot")
    io.say(f"  ✓ Bot trovato: @{username}")

    io.say(f"\n  Ora apri @{username} su Telegram e scrivigli «ciao». Così capisco chi sei (solo tu potrai usarlo).")
    owner = None
    if io.yes("  Aspetto il tuo messaggio?", True):
        try:
            owner = c["owner"](env_out["TELEGRAM_BOT_TOKEN"], say=io.say)
            io.say(f"  Ho ricevuto un messaggio da {owner['nome']}" + (f" (@{owner['username']})" if owner['username'] else "") + f", ID {owner['id']}.")
            if not io.yes("  Sei tu?", True):
                owner = None
        except WizardError as e:
            io.say(f"  {e}")
    owner_id = str(owner["id"]) if owner else _retry(io, lambda: _num(io.ask("  Il tuo ID Telegram numerico (lo vedi scrivendo a @userinfobot)")), "l'ID")
    env_out["ALLOWED_TELEGRAM_USER_ID"] = owner_id

    io.say("\n2/4  L'intelligenza artificiale")
    base = env.get("OMNIROUTE_BASE_URL", "")
    if base and (env.get("OMNIROUTE_API_KEY") or "").strip() and not io.yes("  Uso una chiave propria per questo account? (No = chiave comune del server)", False):
        io.say("  ✓ Uso la chiave comune del server.")
    else:
        base = base or io.ask("  Indirizzo del servizio IA compatibile OpenAI (es. https://ai.miodominio.it/v1)")

        def _ai():
            k = io.secret("  Chiave del servizio IA")
            info = c["ai"](base, k)
            env_out["OMNIROUTE_API_KEY"] = k
            io.say(f"  ✓ Funziona ({info}).")
        _retry(io, _ai, "la chiave IA")
        if base != env.get("OMNIROUTE_BASE_URL", ""):
            env_out["OMNIROUTE_BASE_URL"] = base

    io.say("\n3/4  Instagram (facoltativo, solo lettura)")
    io.say("  Serve un token di Meta: la guida passo per passo è in docs/INSTAGRAM.md. Si può aggiungere anche dopo.")
    if io.yes("  Collego Instagram adesso?", False):
        def _ig():
            tok = io.secret("  Token Instagram")
            uid = io.ask("  ID dell'account Instagram (numero)")
            info = c["ig"](tok, uid)
            env_out["META_IG_TOKEN"], env_out["META_IG_USER_ID"] = tok, uid
            io.say(f"  ✓ Collegato: {info}.")
        try:
            _retry(io, _ig, "Instagram")
        except WizardError as e:
            io.say(f"  {e} Vado avanti senza Instagram.")

    io.say("\n4/4  Archivio di conoscenza (facoltativo)")
    io.say("  Un repository GitHub con i documenti dell'account (calendario, contatti, regole). Il bot lo legge e propone modifiche.")
    kbkey = None
    pub = ""
    if io.yes("  Ne ho uno da collegare?", False):
        repo = io.ask("  Indirizzo SSH del repository (es. git@github.com:utente/archivio.git)")
        env_out["KB_REPO"] = repo
        tmp = os.path.join(accounts_dir, f".kbkey-{slug}")
        pub = c["key"](tmp)
        with open(tmp, encoding="utf-8") as f:
            kbkey = f.read()
        os.remove(tmp)

    identita = ""
    if descrizione:
        identita = (f"Sei il manager social digitale di {proprietario}: {descrizione}. Lavori con la sua approvazione. "
                    "Parli SEMPRE in italiano semplice e naturale, come una persona.")
    profile = {"proprietario": proprietario, "identita": identita, "regole_extra": [], "utenti": {owner_id: proprietario},
               "benvenuto": f"Ciao {proprietario}! Sono il manager social di {nome}." }
    if env_out.get("KB_REPO"):
        profile["kb"] = {"repo": env_out["KB_REPO"], "branch": "main", "write_branch": "manager"}
    d = write_account(accounts_dir, slug, env_out, profile, kbkey)

    io.say(f"\n✓ Account «{nome}» creato in {d}")
    io.say(f"  Parte da solo entro 30 secondi. Poi apri @{username} e scrivi /start.")
    if pub:
        io.say("\n  Archivio: aggiungi questa chiave pubblica come «Deploy key» (con permesso di scrittura) nelle impostazioni del repository:\n")
        io.say("  " + pub)
    return slug


def _num(s: str) -> str:
    if not re.fullmatch(r"\d{4,15}", s or ""):
        raise WizardError("L'ID Telegram è un numero (di solito 8-10 cifre).")
    return s


def describe(cfg) -> str:
    kb = "archivio" if cfg.kb_repo else "-"
    return f"{cfg.slug:<20} Telegram ✓  Instagram {'✓' if cfg.ig_token else '-'}  {kb}  proprietari: {len(cfg.allowed_user_ids)}"


def cmd_list(env=None, say=print) -> int:
    errs = []
    accs = cfgmod.load_accounts(env, errors=errs)
    for a in accs:
        say(describe(a))
    for n, why in errs:
        say(f"{n:<20} ✗ {why}")
    if not accs and not errs:
        say("Nessun account. Aggiungine uno con: python -m app.accounts add")
    return 0


def cmd_check(name: str = None, env=None, say=print) -> int:
    errs = []
    bad = 0
    for a in cfgmod.load_accounts(env, errors=errs):
        if name and a.slug != name:
            continue
        say(f"\n{a.slug}")
        for what, fn in (("Telegram", lambda: "@" + check_telegram(a.telegram_token)),
                         ("IA", lambda: check_ai(a.ai_base_url, a.ai_api_key)),
                         ("Instagram", lambda: check_instagram(a.ig_token, a.ig_user_id, a.graph_version) if a.ig_token else "non collegato")):
            try:
                say(f"  ✓ {what}: {fn()}")
            except WizardError as e:
                bad += 1
                say(f"  ✗ {what}: {e}")
    for n, why in errs:
        bad += 1
        say(f"\n{n}\n  ✗ {why}")
    return 1 if bad else 0


def cmd_remove(name: str, env=None, say=print) -> int:
    env = env if env is not None else os.environ
    adir = env.get("ACCOUNTS_DIR", "/config/accounts")
    src = os.path.join(adir, name)
    if not cfgmod.SLUG.match(name or "") or not os.path.isdir(src):
        say("Account non trovato.")
        return 1
    dst = os.path.join(adir, f".{name}.rimosso-{dt.date.today().isoformat()}")
    os.rename(src, dst)
    say(f"Configurazione messa da parte in {dst}. Il bot di '{name}' si ferma al prossimo riavvio. "
        f"I dati (database, file) restano in {env.get('DATA_ROOT', '/data')}/{name}: cancellali tu, se vuoi.")
    return 0


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "add"
    try:
        if cmd == "add":
            add()
            return 0
        if cmd == "list":
            return cmd_list()
        if cmd == "check":
            return cmd_check(a[1] if len(a) > 1 else None)
        if cmd == "remove" and len(a) > 1:
            return cmd_remove(a[1])
    except WizardError as e:
        print(f"✗ {e}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nInterrotto: non è stato salvato niente.")
        return 130
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
