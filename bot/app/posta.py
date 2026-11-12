"""Posta: invio di email con un server SMTP configurato dal proprietario (dal pannello, pagina «Posta»).

Regole:
- una mail parte SOLO dopo l'approvazione del proprietario (bottoni su Telegram, anteprima completa); il manager non invia mai da solo;
- una sola persona per mail, nessun «Cc»/«Ccn»; limite giornaliero; indirizzi che hanno chiesto di non essere contattati sono bloccati;
- i segreti (password SMTP) stanno solo in `_posta.env` (permessi 600, mai su Git, mai nei log, mai mostrati);
- la connessione è cifrata e il certificato viene verificato (si accetta «senza cifratura» solo verso localhost o indirizzi privati);
- il «pixel» di apertura è un'immagine 1x1 servita dal pannello: registra solo l'ora dell'apertura (nessun IP, nessun browser).
"""
import email.utils
import ipaddress
import os
import re
import secrets
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage

from . import config as cfgmod

FILE_NAME = "_posta.env"
CAMPI = ("SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM", "MAIL_FROM_NAME", "MAIL_REPLY_TO",
         "MAIL_PUBLIC_URL", "MAIL_PIXEL", "MAIL_FIRMA", "MAIL_MAX_AL_GIORNO")
SECURITIES = ("starttls", "ssl", "nessuna")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
MAX_BODY = 2500
TIMEOUT = 20


class PostaError(Exception):
    pass


def valid_email(addr: str) -> bool:
    addr = (addr or "").strip()
    return bool(EMAIL_RE.match(addr)) and len(addr) <= 254 and ".." not in addr


def file_for(accounts_dir: str) -> str:
    return os.path.join(accounts_dir, FILE_NAME)


class Config:
    """Impostazioni della posta (le stesse per tutti gli account)."""

    def __init__(self, values: dict = None):
        v = values or {}
        self.host = (v.get("SMTP_HOST") or "").strip()
        try:
            self.port = int(v.get("SMTP_PORT") or 587)
        except ValueError:
            self.port = 587
        self.security = v.get("SMTP_SECURITY") if v.get("SMTP_SECURITY") in SECURITIES else "starttls"
        self.user = (v.get("SMTP_USER") or "").strip()
        self._password = v.get("SMTP_PASSWORD") or ""
        self.sender = (v.get("MAIL_FROM") or "").strip()
        self.sender_name = (v.get("MAIL_FROM_NAME") or "").strip()
        self.reply_to = (v.get("MAIL_REPLY_TO") or "").strip()
        self.public_url = (v.get("MAIL_PUBLIC_URL") or "").strip().rstrip("/")
        self.pixel = (v.get("MAIL_PIXEL") or "1") != "0"
        self.firma = (v.get("MAIL_FIRMA") or "").replace("\\n", "\n").strip()
        try:
            self.max_day = max(1, min(int(v.get("MAIL_MAX_AL_GIORNO") or 20), 500))
        except ValueError:
            self.max_day = 20

    @property
    def configured(self) -> bool:
        return bool(self.host and valid_email(self.sender))

    @property
    def has_password(self) -> bool:
        return bool(self._password)

    @property
    def tracking_possible(self) -> bool:
        return self.pixel and self.public_url.startswith("https://")


def load(path: str) -> Config:
    return Config(cfgmod.parse_env_file(path) if os.path.isfile(path) else {})


def check_settings(form: dict, current: Config) -> tuple:
    """Controlla i campi del modulo. Ritorna (valori_da_scrivere, errore)."""
    host = (form.get("host") or "").strip()
    if not host or not HOST_RE.match(host):
        return None, "L'indirizzo del server non va bene (esempio: mail.tuodominio.it)."
    try:
        port = int((form.get("port") or "587").strip())
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        return None, "La porta deve essere un numero (di solito 587 o 465)."
    sec = form.get("security") or "starttls"
    if sec not in SECURITIES:
        return None, "Scegli come proteggere la connessione."
    if sec == "nessuna" and not _private_host(host):
        return None, "Senza cifratura si può usare solo un server dentro la tua rete (localhost o indirizzo privato)."
    sender = (form.get("sender") or "").strip()
    if not valid_email(sender):
        return None, "L'indirizzo da cui partono le mail non va bene (esempio: info@tuodominio.it)."
    reply = (form.get("reply_to") or "").strip()
    if reply and not valid_email(reply):
        return None, "L'indirizzo per le risposte non va bene."
    name = " ".join((form.get("sender_name") or "").split())[:80]
    if re.search(r"[\r\n<>\"]", name):
        return None, "Il nome del mittente contiene caratteri non ammessi."
    url = (form.get("public_url") or "").strip().rstrip("/")
    if url and not re.match(r"^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$", url):
        return None, "L'indirizzo pubblico del pannello deve essere del tipo https://edith.tuodominio.it (senza barre alla fine)."
    try:
        mx = max(1, min(int((form.get("max_day") or "20").strip()), 500))
    except ValueError:
        return None, "Il limite giornaliero deve essere un numero."
    user = (form.get("user") or "").strip()
    if re.search(r"[\r\n]", user):
        return None, "Il nome utente non va bene."
    password = form.get("password") or ""
    if re.search(r"[\r\n]", password):
        return None, "La password non va bene."
    firma = (form.get("firma") or "").strip()[:500].replace("\r", "").replace("\n", "\\n")
    vals = {"SMTP_HOST": host, "SMTP_PORT": str(port), "SMTP_SECURITY": sec, "SMTP_USER": user, "MAIL_FROM": sender, "MAIL_FROM_NAME": name,
            "MAIL_REPLY_TO": reply, "MAIL_PUBLIC_URL": url, "MAIL_PIXEL": "1" if form.get("pixel") else "0", "MAIL_FIRMA": firma,
            "MAIL_MAX_AL_GIORNO": str(mx)}
    if password:
        vals["SMTP_PASSWORD"] = password
    return vals, ""


def _private_host(host: str) -> bool:
    if host.lower() in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def new_token(slug: str) -> str:
    return f"{slug}.{secrets.token_urlsafe(18)}"


def pixel_url(cfg: Config, token: str) -> str:
    return f"{cfg.public_url}/t/{token}.gif"


def _no_crlf(v: str, nome: str) -> str:
    if re.search(r"[\r\n\x00]", v or ""):
        raise PostaError(f"{nome} non valido")
    return v or ""


def build_message(cfg: Config, to: str, subject: str, text: str, from_name: str = "", pixel: str = "", reply_to: str = "") -> EmailMessage:
    if not valid_email(to):
        raise PostaError("indirizzo del destinatario non valido")
    subject = " ".join(_no_crlf(subject, "oggetto").split())
    if not subject or len(subject) > 200:
        raise PostaError("serve un oggetto (massimo 200 caratteri)")
    text = (text or "").replace("\r\n", "\n").strip()
    if not text or len(text) > MAX_BODY:
        raise PostaError(f"serve il testo (massimo {MAX_BODY} caratteri)")
    nome = " ".join(_no_crlf(from_name or cfg.sender_name, "nome mittente").split())
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((nome, cfg.sender)) if nome else cfg.sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=cfg.sender.split("@", 1)[1])
    rt = reply_to or cfg.reply_to
    if rt and valid_email(rt):
        msg["Reply-To"] = rt
    msg["List-Unsubscribe"] = f"<mailto:{cfg.sender}?subject=Non%20scrivermi%20piu>"
    corpo = text + (("\n\n" + cfg.firma) if cfg.firma else "")
    msg.set_content(corpo + f"\n\n--\nSe non vuoi più ricevere nostre mail, rispondi con «non scrivermi più» e non ti scriveremo.")
    if pixel:
        import html as _h
        parti = "".join(f"<p>{_h.escape(p).replace(chr(10), '<br>')}</p>" for p in corpo.split("\n\n"))
        msg.add_alternative(f'<html><body style="font-family:sans-serif;font-size:15px;line-height:1.5">{parti}'
                            f'<p style="color:#666;font-size:12px">Se non vuoi più ricevere nostre mail, rispondi con «non scrivermi più».</p>'
                            f'<img src="{_h.escape(pixel, quote=True)}" width="1" height="1" alt="" style="display:block;border:0;width:1px;height:1px"></body></html>',
                            subtype="html")
    return msg


def _connect(cfg: Config):
    ctx = ssl.create_default_context()
    if cfg.security == "ssl":
        s = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=TIMEOUT, context=ctx)
    else:
        s = smtplib.SMTP(cfg.host, cfg.port, timeout=TIMEOUT)
        s.ehlo()
        if cfg.security == "starttls":
            s.starttls(context=ctx)
            s.ehlo()
        elif not _private_host(cfg.host):
            s.close()
            raise PostaError("senza cifratura è ammesso solo verso la rete interna")
    if cfg.user and cfg._password:
        s.login(cfg.user, cfg._password)
    return s


def _explain(e: Exception) -> str:
    """Un errore comprensibile, mai con password o dettagli del server."""
    if isinstance(e, PostaError):
        return str(e)
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "il server ha rifiutato nome utente o password"
    if isinstance(e, ssl.SSLCertVerificationError):
        return "il certificato del server non risulta valido per questo indirizzo (usa il nome del server, non l'IP)"
    if isinstance(e, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return "la protezione della connessione non va d'accordo con il server (prova l'altra: STARTTLS o SSL)"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "il server non accetta questo destinatario"
    if isinstance(e, smtplib.SMTPSenderRefused):
        return "il server non accetta questo indirizzo come mittente"
    if isinstance(e, smtplib.SMTPResponseException):
        return f"il server ha risposto con un errore ({e.smtp_code})"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "il server non risponde in tempo"
    if isinstance(e, (socket.gaierror,)):
        return "non trovo questo indirizzo del server"
    if isinstance(e, (ConnectionError, OSError)):
        return "non riesco a collegarmi al server (indirizzo o porta sbagliati?)"
    return f"errore imprevisto ({type(e).__name__})"


def send(cfg: Config, msg: EmailMessage) -> None:
    if not cfg.configured:
        raise PostaError("la posta non è configurata")
    try:
        with _connect(cfg) as s:
            refused = s.send_message(msg)
        if refused:
            raise PostaError("il server non accetta questo destinatario")
    except PostaError:
        raise
    except Exception as e:
        raise PostaError(_explain(e)) from None


def test_connection(cfg: Config, to: str) -> str:
    """Prova vera: si collega, accede e manda una mail di prova a `to`. Ritorna un messaggio per il proprietario."""
    if not cfg.configured:
        raise PostaError("compila prima server e indirizzo mittente")
    msg = build_message(cfg, to, "Prova di EDITH", "Questa è una mail di prova mandata da EDITH.\nSe la leggi, la posta funziona.")
    send(cfg, msg)
    return f"Mail di prova partita verso {to}. Controlla la casella (anche nella posta indesiderata)."
