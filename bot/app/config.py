"""Configurazione: valori comuni da variabili d'ambiente + una cartella per ogni account.

Un solo contenitore gestisce più account. Ogni account ha:
- una cartella di impostazioni `<ACCOUNTS_DIR>/<nome>/` con `account.env` (segreti: codice del bot Telegram, chiavi),
  `profile.json` (chi è, che regole ha) e, se serve, la chiave dell'archivio (`kbkey`);
- una cartella di dati `<DATA_ROOT>/<nome>/` (database, file temporanei, copie di sicurezza, archivio).
Gli account non si vedono tra loro: ognuno ha database, bot Telegram, regole e chiavi proprie.
Mai segreti nel codice né nel repository.
"""
import os
import re
from dataclasses import dataclass

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,29}$")


def _req(env: dict, name: str) -> str:
    v = (env.get(name) or "").strip()
    if not v:
        raise RuntimeError(f"Variabile mancante: {name}")
    return v


@dataclass(frozen=True)
class Config:
    telegram_token: str
    allowed_user_id: int  # il primo della lista: riceve i messaggi automatici principali
    ai_base_url: str
    ai_api_key: str
    model_normal: str
    model_reason: str
    model_light: str
    data_dir: str
    history_messages: int
    max_download_bytes: int
    retention_days: int
    allowed_user_ids: tuple = ()  # tutti i proprietari abilitati (es. i membri di una band)
    slug: str = "default"
    profile_dir: str = ""  # dove stanno profile.json e la chiave dell'archivio (se vuoto: la cartella dei dati)
    ig_token: str = ""
    ig_user_id: str = ""
    graph_version: str = "v23.0"
    kb_repo: str = ""
    kb_key: str = ""
    browser_url: str = ""
    browser_token: str = ""


def parse_env_file(path: str) -> dict:
    """Legge un file CHIAVE=VALORE (niente shell, niente espansioni). Righe vuote e # ignorate."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                out[k.strip()] = v
    except OSError:
        pass
    return out


def build(env: dict, data_dir: str, profile_dir: str, slug: str) -> Config:
    ids = tuple(int(x) for x in _req(env, "ALLOWED_TELEGRAM_USER_ID").replace(" ", "").split(",") if x)
    return Config(
        telegram_token=_req(env, "TELEGRAM_BOT_TOKEN"),
        allowed_user_id=ids[0],
        ai_base_url=_req(env, "OMNIROUTE_BASE_URL").rstrip("/"),
        ai_api_key=_req(env, "OMNIROUTE_API_KEY"),
        model_normal=env.get("MODEL_NORMAL") or "cc/claude-sonnet-5-5",
        model_reason=env.get("MODEL_REASON") or "cc/claude-opus-5-5",
        model_light=env.get("MODEL_LIGHT") or "cc/claude-haiku-5-5",
        data_dir=data_dir,
        history_messages=int(env.get("HISTORY_MESSAGES") or "30"),
        # Bot API cloud: download massimo 20 MB. Oltre serve il Local Bot API Server.
        max_download_bytes=int(env.get("MAX_DOWNLOAD_BYTES") or str(20 * 1024 * 1024)),
        # Regola: i file che non servono più si eliminano. Disco del server limitato.
        retention_days=int(env.get("MEDIA_RETENTION_DAYS") or "7"),
        allowed_user_ids=ids,
        slug=slug,
        profile_dir=profile_dir,
        ig_token=(env.get("META_IG_TOKEN") or "").strip(),
        ig_user_id=(env.get("META_IG_USER_ID") or "").strip(),
        graph_version=env.get("META_GRAPH_VERSION") or "v23.0",
        kb_repo=(env.get("KB_REPO") or "").strip(),
        kb_key=(env.get("KB_KEY") or "").strip(),
        browser_url=(env.get("BROWSER_URL") or "").strip(),
        browser_token=(env.get("BROWSER_TOKEN") or "").strip(),
    )


def account_names(accounts_dir: str) -> list:
    try:
        names = sorted(n for n in os.listdir(accounts_dir)
                       if SLUG.match(n) and os.path.isfile(os.path.join(accounts_dir, n, "account.env")))
    except OSError:
        return []
    return names


def load_accounts(environ=None, accounts_dir: str = None, data_root: str = None, errors: list = None) -> list:
    """Tutti gli account configurati. Le impostazioni comuni (server AI, modelli) stanno nell'ambiente;
    ogni account può sovrascriverle nel suo account.env (es. una chiave AI propria, con modelli limitati).
    Con `errors` (una lista) un account scritto male viene saltato e segnalato (solo il nome e cosa manca, mai i valori);
    senza, l'errore viene sollevato."""
    env = dict(environ if environ is not None else os.environ)
    accounts_dir = accounts_dir or env.get("ACCOUNTS_DIR", "/config/accounts")
    data_root = data_root or env.get("DATA_ROOT", "/data")
    out = []
    for name in account_names(accounts_dir):
        adir = os.path.join(accounts_dir, name)
        own = parse_env_file(os.path.join(adir, "account.env"))
        merged = {**env, **{k: v for k, v in own.items() if v != ""}}
        kbkey = os.path.join(adir, "kbkey")
        if not merged.get("KB_KEY") and os.path.isfile(kbkey):
            merged["KB_KEY"] = kbkey
        try:
            out.append(build(merged, os.path.join(data_root, name), adir, name))
        except (RuntimeError, ValueError) as e:
            if errors is None:
                raise
            errors.append((name, str(e)))
    if not out and env.get("TELEGRAM_BOT_TOKEN"):  # modalità semplice: un solo account, tutto nell'ambiente
        d = env.get("DATA_DIR", data_root)
        out.append(build(env, d, d, "default"))
    return out


def load(slug: str = None) -> Config:
    """Per gli strumenti da riga di comando: un account, scelto con --account NOME (o la variabile ACCOUNT).
    Se ce n'è uno solo non serve indicarlo."""
    import sys
    accs = load_accounts()
    if not accs:
        raise RuntimeError("Nessun account configurato")
    if slug is None:
        a = sys.argv
        slug = a[a.index("--account") + 1] if "--account" in a and a.index("--account") + 1 < len(a) else os.environ.get("ACCOUNT", "")
    if slug:
        for c in accs:
            if c.slug == slug:
                return c
        raise RuntimeError(f"Account sconosciuto: {slug} (disponibili: {', '.join(c.slug for c in accs)})")
    if len(accs) > 1:
        raise RuntimeError(f"Più account: scegli con --account ({', '.join(c.slug for c in accs)})")
    return accs[0]
