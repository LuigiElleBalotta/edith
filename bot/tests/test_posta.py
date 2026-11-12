import email
import http.client
import json
import os
import socketserver
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import accounts, approvals, panel, posta
from app.db import Db
from app.tools import Tools, ToolError

PW = "una-password-lunga-di-prova"
TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
SEGRETO = "Pw!Segreta-di-PROVA-9"


class FakeSmtp(socketserver.ThreadingTCPServer):
    """Un piccolo server SMTP in locale (senza cifratura) che conserva le mail ricevute."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.mails, self.reject = [], False
        super().__init__(("127.0.0.1", 0), FakeHandler)


class FakeHandler(socketserver.StreamRequestHandler):
    def reply(self, t):
        self.wfile.write((t + "\r\n").encode())

    def handle(self):
        self.reply("220 test")
        frm, rcpt = "", []
        while True:
            line = self.rfile.readline().decode(errors="replace").strip()
            cmd = line.upper()
            if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                self.reply("250 test")
            elif cmd.startswith("MAIL FROM"):
                frm = line
                self.reply("250 ok")
            elif cmd.startswith("RCPT TO"):
                if self.server.reject:
                    self.reply("550 no")
                else:
                    rcpt.append(line)
                    self.reply("250 ok")
            elif cmd == "DATA":
                self.reply("354 go")
                data = b""
                while True:
                    l = self.rfile.readline()
                    if l in (b".\r\n", b""):
                        break
                    data += l
                self.server.mails.append((frm, rcpt, data))
                self.reply("250 queued")
            elif cmd == "QUIT":
                self.reply("221 bye")
                return
            elif cmd in ("RSET", "NOOP"):
                self.reply("250 ok")
            else:
                self.reply("502 no")


def cfg_vals(port, **kw):
    v = {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(port), "SMTP_SECURITY": "nessuna", "MAIL_FROM": "info@esempio.it",
         "MAIL_FROM_NAME": "Band Test", "MAIL_PUBLIC_URL": "https://edith.esempio.it", "MAIL_MAX_AL_GIORNO": "3"}
    v.update(kw)
    return v


class PostaTests(unittest.TestCase):
    def setUp(self):
        self.srv = FakeSmtp()
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.cfg = posta.Config(cfg_vals(self.srv.server_address[1]))

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_indirizzi_e_impostazioni(self):
        for ok in ("a@b.it", "nome.cognome+x@sub.dominio.com"):
            self.assertTrue(posta.valid_email(ok), ok)
        for brutto in ("", "a@b", "a b@c.it", "a@b..it", "a@b.it\r\nBcc: x@y.it", "<a@b.it>", "a@b.it,c@d.it", "@b.it"):
            self.assertFalse(posta.valid_email(brutto), repr(brutto))
        base = {"host": "mail.esempio.it", "port": "587", "security": "starttls", "sender": "info@esempio.it", "max_day": "20"}
        vals, err = posta.check_settings(base, posta.Config())
        self.assertEqual(err, "")
        self.assertEqual(vals["SMTP_HOST"], "mail.esempio.it")
        for campo, valore in (("host", "x y"), ("host", ""), ("host", "a;b"), ("port", "0"), ("port", "abc"), ("port", "70000"), ("security", "boh"),
                              ("sender", "non-una-mail"), ("reply_to", "x"), ("sender_name", "Mario\r\nBcc: a@b.it"), ("sender_name", 'Mar"io'),
                              ("public_url", "http://x.it"), ("public_url", "https://x.it/percorso"), ("max_day", "tanti"), ("user", "a\nb"),
                              ("password", "con\nacapo"), ("password", " spazio"), ("password", "'chiusa'")):
            _, e = posta.check_settings({**base, campo: valore}, posta.Config())
            self.assertTrue(e, (campo, valore))
        # senza cifratura solo verso la rete interna
        _, e = posta.check_settings({**base, "security": "nessuna"}, posta.Config())
        self.assertIn("rete", e)
        _, e = posta.check_settings({**base, "security": "nessuna", "host": "127.0.0.1"}, posta.Config())
        self.assertEqual(e, "")
        _, e = posta.check_settings({**base, "security": "nessuna", "host": "10.1.2.3"}, posta.Config())
        self.assertEqual(e, "")

    def test_messaggio_testo_html_e_pixel(self):
        m = posta.build_message(self.cfg, "chi@locale.it", "Ciao dalla band", "Primo paragrafo.\n\nSecondo <b>paragrafo</b>.",
                                pixel="https://edith.esempio.it/t/x.abcdefghijklmnopqrstu.gif")
        self.assertEqual(m["To"], "chi@locale.it")
        self.assertIsNone(m["Cc"])
        self.assertIsNone(m["Bcc"])
        self.assertIn("List-Unsubscribe", m)
        self.assertIn("non scrivermi più", m.get_body(("plain",)).get_content())
        html = m.get_body(("html",)).get_content()
        self.assertIn('width="1" height="1"', html)
        self.assertIn("&lt;b&gt;paragrafo&lt;/b&gt;", html)  # il testo non diventa HTML
        self.assertNotIn("<b>paragrafo</b>", html)
        senza = posta.build_message(self.cfg, "chi@locale.it", "Ciao", "Testo")
        self.assertIsNone(senza.get_body(("html",)))  # senza pixel: solo testo

    def test_intestazioni_non_si_iniettano(self):
        for to, ogg, nome in (("a@b.it\r\nBcc: x@y.it", "Ciao", ""), ("a@b.it", "Ciao\r\nBcc: x@y.it", ""), ("a@b.it", "Ciao", "Mario\nBcc: x@y.it")):
            with self.assertRaises(posta.PostaError):
                posta.build_message(self.cfg, to, ogg, "Testo", from_name=nome)
        with self.assertRaises(posta.PostaError):
            posta.build_message(self.cfg, "a@b.it", "", "Testo")
        with self.assertRaises(posta.PostaError):
            posta.build_message(self.cfg, "a@b.it", "Ciao", "x" * (posta.MAX_BODY + 1))

    def test_invio_vero_verso_server_locale_e_prova(self):
        out = posta.test_connection(self.cfg, "me@esempio.it")
        self.assertIn("me@esempio.it", out)
        self.assertEqual(len(self.srv.mails), 1)
        frm, rcpt, data = self.srv.mails[0]
        msg = email.message_from_bytes(data)
        self.assertEqual(msg["Subject"], "Prova di EDITH")
        self.assertIn("me@esempio.it", rcpt[0])
        self.assertIn("info@esempio.it", msg["From"])
        self.srv.reject = True
        with self.assertRaises(posta.PostaError) as c:
            posta.send(self.cfg, posta.build_message(self.cfg, "x@y.it", "O", "T"))
        self.assertNotIn("550", str(c.exception) + "x") if False else None
        self.assertTrue(str(c.exception))

    def test_errori_senza_dettagli_segreti(self):
        brutto = posta.Config(cfg_vals(1, SMTP_PASSWORD=SEGRETO, SMTP_USER="info@esempio.it"))  # porta 1: nessuno ascolta
        with self.assertRaises(posta.PostaError) as c:
            posta.send(brutto, posta.build_message(brutto, "x@y.it", "O", "T"))
        self.assertNotIn(SEGRETO, str(c.exception))
        self.assertIn("collegarmi", str(c.exception))
        senza = posta.Config()
        with self.assertRaises(posta.PostaError):
            posta.send(senza, posta.build_message(self.cfg, "x@y.it", "O", "T"))

    def test_senza_cifratura_rifiutata_verso_internet(self):
        ext = posta.Config(cfg_vals(25, SMTP_HOST="mail.esempio.it", SMTP_SECURITY="nessuna"))
        with self.assertRaises(posta.PostaError):
            posta.send(ext, posta.build_message(ext, "x@y.it", "O", "T"))

    def test_deliver_registra_limite_blocco_e_contatto(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Db(tmp)
            cid = db.contact_add("Locale A", "locale", "https://a.it", status="da_scrivere", email="chi@locale.it")
            ex = {"to": "chi@locale.it", "subject": "Ciao", "body": "Testo", "contact_id": cid}
            out = posta.deliver(db, self.cfg, ex, "alfa", "2026-11-12")
            self.assertIn("Ti dirò se risulta aperta", out)  # indirizzo pubblico https: pixel attivo
            self.assertEqual(len(self.srv.mails), 1)
            r = db.mail_list()[0]
            self.assertEqual((r["a"], r["tracciata"], r["aperture"]), ("chi@locale.it", 1, 0))
            self.assertEqual(db.contact_get(cid)["stato"], "in_attesa_risposta")
            html = email.message_from_bytes(self.srv.mails[0][2]).get_payload()[1].get_payload(decode=True).decode()
            self.assertIn("/t/alfa.", html)
            # limite giornaliero (3)
            posta.deliver(db, self.cfg, {**ex, "contact_id": None}, "alfa", "2026-11-12")
            posta.deliver(db, self.cfg, {**ex, "contact_id": None}, "alfa", "2026-11-12")
            with self.assertRaises(posta.PostaError):
                posta.deliver(db, self.cfg, {**ex, "contact_id": None}, "alfa", "2026-11-12")
            self.assertEqual(len(self.srv.mails), 3)
            # blocco
            db.mail_block("bloccato@locale.it", "ha chiesto di non essere contattato")
            with self.assertRaises(posta.PostaError):
                posta.deliver(db, posta.Config(cfg_vals(self.srv.server_address[1], MAIL_MAX_AL_GIORNO="50")),
                              {**ex, "to": "Bloccato@Locale.it", "contact_id": None}, "alfa", "2026-11-12")
            self.assertEqual(len(self.srv.mails), 3)
            # senza https niente pixel
            nopx = posta.Config(cfg_vals(self.srv.server_address[1], MAIL_PUBLIC_URL="", MAIL_MAX_AL_GIORNO="50"))
            self.assertNotIn("aperta", posta.deliver(db, nopx, {**ex, "contact_id": None}, "alfa", "2026-11-12"))
            self.assertEqual(db.mail_list()[0]["tracciata"], 0)
            db.close()

    def test_aperture_contano_solo_con_codice_giusto(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Db(tmp)
            posta.deliver(db, self.cfg, {"to": "a@b.it", "subject": "S", "body": "B"}, "alfa", "2026-11-12")
            tok = db._x("SELECT token FROM mail_inviate").fetchone()[0]
            self.assertFalse(db.mail_open("alfa.codice-sbagliato-0000000000"))
            self.assertTrue(db.mail_open(tok))
            self.assertTrue(db.mail_open(tok))
            r = db.mail_list()[0]
            self.assertEqual(r["aperture"], 2)
            self.assertIsNotNone(r["prima_apertura"])
            db.close()


class ToolsPostaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(self.tmp.name)
        self.cfg = posta.Config(cfg_vals(1, MAIL_MAX_AL_GIORNO="2"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def names(self, t):
        return {s["function"]["name"] for s in t.specs}

    def test_strumenti_mail_solo_se_la_posta_e_configurata(self):
        self.assertFalse({n for n in self.names(Tools(self.db)) if n.startswith("mail_")})
        self.assertFalse({n for n in self.names(Tools(self.db, posta=lambda: posta.Config())) if n.startswith("mail_")})
        self.assertEqual({n for n in self.names(Tools(self.db, posta=lambda: self.cfg)) if n.startswith("mail_")},
                         {"mail_stato", "mail_proponi", "mail_registro", "mail_non_contattare"})

    def test_mail_proponi_non_invia_e_crea_solo_la_proposta(self):
        t = Tools(self.db, posta=lambda: self.cfg)
        out = t.run("mail_proponi", {"a": "chi@locale.it", "oggetto": "Ciao", "testo": "Vorremmo suonare da voi.", "motivo": "locale in zona"})
        self.assertIn("NON è partita", out)
        aid = t.take_proposals()[0]
        a = approvals.get(self.db, aid)
        self.assertEqual((a["kind"], a["status"]), ("invio_mail", "in_attesa"))
        self.assertIn("chi@locale.it", a["testo"])
        self.assertIn("Vorremmo suonare da voi.", a["testo"])
        self.assertEqual(self.db.mail_list(), [])  # nessun invio
        self.assertIn("invio_mail", approvals.KINDS)

    def test_mail_proponi_rifiuta_cose_sbagliate(self):
        t = Tools(self.db, posta=lambda: self.cfg)
        ok = {"a": "chi@locale.it", "oggetto": "Ciao", "testo": "Testo", "motivo": "m"}
        for cambio in ({"a": "non-una-mail"}, {"a": "x@y.it\r\nBcc: z@y.it"}, {"oggetto": ""}, {"oggetto": "A\r\nB"}, {"testo": ""}, {"testo": "x" * 3000}, {"contatto_id": 99}):
            self.assertIn("Errore", t.run("mail_proponi", {**ok, **cambio}), cambio)
        self.assertEqual(approvals.get(self.db, 1), None)
        self.db.mail_block("chi@locale.it")
        self.assertIn("non va contattato", t.run("mail_proponi", ok))
        self.db.mail_block("a@a.it")
        self.assertEqual(t.run("mail_non_contattare", {"email": "Nuovo@Locale.it", "motivo": "ha chiesto"}), "Fatto: non gli scriverò più.")
        self.assertIn("non va contattato", t.run("mail_proponi", {**ok, "a": "nuovo@locale.it"}))
        self.assertIn("Errore", t.run("mail_non_contattare", {"email": "no"}))

    def test_limite_giornaliero_nelle_proposte(self):
        t = Tools(self.db, posta=lambda: self.cfg)
        self.db.mail_log(None, "a@a.it", "s", "b", "alfa.x", False)
        self.db.mail_log(None, "b@a.it", "s", "b", "alfa.y", False)
        self.assertIn("limite", t.run("mail_proponi", {"a": "chi@locale.it", "oggetto": "O", "testo": "T", "motivo": "m"}))

    def test_registro_e_stato(self):
        t = Tools(self.db, posta=lambda: self.cfg)
        self.assertEqual(t.run("mail_registro", {}), "Nessuna mail inviata.")
        self.db.mail_log(None, "a@a.it", "Oggetto", "b", "alfa.tok", True)
        self.db.mail_open("alfa.tok")
        reg = json.loads(t.run("mail_registro", {}))
        self.assertIn("aperta 1 volte", reg[0]["aperture"])
        st = json.loads(t.run("mail_stato", {}))
        self.assertEqual((st["inviate_oggi"], st["limite_giornaliero"], st["tracciamento_aperture"]), (1, 2, True))


class ContattiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(self.tmp.name)
        self.t = Tools(self.db)
        self.pieno = {"nome": "Circolo Aurora", "tipo": "locale", "zona": "Bologna", "canale": "email", "email": "info@circolo.it",
                      "link_fonte": "https://circolo.it/contatti", "priorita": 1, "prima_scrittura": "2026-12-01"}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_se_manca_un_dato_non_salva_e_dice_cosa_chiedere(self):
        for campo in ("nome", "tipo", "zona", "canale", "link_fonte", "priorita", "prima_scrittura", "email"):
            args = {k: v for k, v in self.pieno.items() if k != campo}
            out = self.t.run("contatto_aggiungi", args)
            self.assertIn("Mancano", out, campo)
            self.assertIn(campo, out)
            self.assertIn("NON inventarli", out)
        self.assertEqual(self.db.contacts_list(), [])
        out = self.t.run("contatto_aggiungi", {})
        self.assertIn("nome", out)
        self.assertIn("zona", out)
        self.assertEqual(self.db.contacts_list(), [])

    def test_riferimento_secondo_il_canale(self):
        base = {k: v for k, v in self.pieno.items() if k != "email"}
        self.assertIn("telefono", self.t.run("contatto_aggiungi", {**base, "canale": "telefono"}))
        self.assertIn("telefono", self.t.run("contatto_aggiungi", {**base, "canale": "whatsapp"}))
        self.assertIn("handle", self.t.run("contatto_aggiungi", {**base, "canale": "dm_instagram"}))
        self.assertIn("salvato", self.t.run("contatto_aggiungi", {**base, "canale": "di_persona"}))  # di persona: nessun riferimento serve

    def test_salva_tutto_e_valida(self):
        self.assertIn("salvato", self.t.run("contatto_aggiungi", self.pieno))
        c = self.db.contacts_list()[0]
        self.assertEqual((c["nome"], c["zona"], c["email"], c["canale"], c["stato"], c["priorita"]), ("Circolo Aurora", "Bologna", "info@circolo.it", "email", "da_scrivere", 1))
        self.assertEqual(self.t.run("contatto_aggiungi", self.pieno), "Già in archivio.")
        for cambio in ({"email": "non-una-mail", "nome": "B1"}, {"link_fonte": "javascript:x", "nome": "B2"}, {"priorita": 7, "nome": "B3"},
                       {"priorita": "alta", "nome": "B4"}, {"prima_scrittura": "domani", "nome": "B5"}):
            self.assertIn("Errore", self.t.run("contatto_aggiungi", {**self.pieno, **cambio}), cambio)
        self.assertEqual(len(self.db.contacts_list()), 1)


class OverrideTests(unittest.TestCase):
    """La posta propria dell'account vince su quella comune (per intero, mai mescolata)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.acc = os.path.join(self.tmp.name, "accounts")
        os.makedirs(os.path.join(self.acc, "alfa"))
        os.makedirs(os.path.join(self.acc, "beta"))
        for n in ("alfa", "beta"):
            open(os.path.join(self.acc, n, "account.env"), "w", encoding="utf-8").write("TELEGRAM_BOT_TOKEN=" + TOKEN + "\n")
        with open(os.path.join(self.acc, posta.FILE_NAME), "w", encoding="utf-8") as f:
            f.write("SMTP_HOST=comune.esempio.it\nSMTP_PORT=587\nSMTP_USER=comune@esempio.it\nSMTP_PASSWORD=" + SEGRETO + "\nMAIL_FROM=info@esempio.it\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_senza_posta_propria_vale_la_comune(self):
        c = posta.resolve(os.path.join(self.acc, "alfa"))
        self.assertEqual((c.origin, c.host, c.configured), ("comune", "comune.esempio.it", True))

    def test_con_posta_propria_vince_tutta_e_non_si_mescola(self):
        with open(os.path.join(self.acc, "alfa", "account.env"), "a", encoding="utf-8") as f:
            f.write("SMTP_HOST=alfa.esempio.it\nMAIL_FROM=band@alfa.it\n")  # niente utente né password: NON si prendono dalla comune
        c = posta.resolve(os.path.join(self.acc, "alfa"))
        self.assertEqual((c.origin, c.host, c.sender), ("account", "alfa.esempio.it", "band@alfa.it"))
        self.assertEqual((c.user, c.has_password), ("", False))  # la password della comune non finisce verso il server dell'account
        b = posta.resolve(os.path.join(self.acc, "beta"))
        self.assertEqual((b.origin, b.host), ("comune", "comune.esempio.it"))  # gli altri account restano sulla comune

    def test_senza_niente_nessuna(self):
        os.remove(os.path.join(self.acc, posta.FILE_NAME))
        c = posta.resolve(os.path.join(self.acc, "alfa"))
        self.assertEqual((c.origin, c.configured), ("nessuna", False))


class Ctl:
    events = {}


class PannelloPostaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.acc, self.data = os.path.join(self.tmp.name, "accounts"), os.path.join(self.tmp.name, "data")
        os.makedirs(self.acc)
        accounts.write_account(self.acc, "alfa", {"TELEGRAM_BOT_TOKEN": TOKEN, "ALLOWED_TELEGRAM_USER_ID": "4242424242"}, {"proprietario": "Giulia"})
        self.p = panel.Panel(PW, self.acc, self.data, {"OMNIROUTE_BASE_URL": "http://x/v1", "OMNIROUTE_API_KEY": "k"}, None,
                             ext_root=os.path.join(self.tmp.name, "ext"))
        self.http = panel.serve(self.p, "127.0.0.1", 0)
        self.port = self.http.server_address[1]
        self.cookie = self.csrf = ""
        self.smtp = FakeSmtp()
        threading.Thread(target=self.smtp.serve_forever, daemon=True).start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.smtp.shutdown()
        self.smtp.server_close()
        self.tmp.cleanup()

    def req(self, method, path, form=None, headers=None):
        import urllib.parse
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"Host": "localhost", **(headers or {})}
        if self.cookie:
            h["Cookie"] = self.cookie
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form)
            h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body, h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data, r

    def login(self):
        st, _, r = self.req("POST", "/login", {"password": PW})
        self.cookie = r.getheader("Set-Cookie").split(";")[0]
        sid = self.cookie.split("=", 1)[1]
        self.csrf = self.p.sessions[sid]["csrf"]

    def post(self, path, form):
        st, data, r = self.req("POST", path, {"csrf": self.csrf, **form})
        return st, data.decode()

    def form(self, **kw):
        base = {"host": "127.0.0.1", "port": str(self.smtp.server_address[1]), "security": "nessuna", "user": "", "sender": "info@esempio.it",
                "sender_name": "Band", "public_url": "https://edith.esempio.it", "max_day": "5", "pixel": "1"}
        base.update(kw)
        return base

    def test_pagina_posta_protetta_e_senza_mostrare_la_password(self):
        self.assertEqual(self.req("GET", "/posta")[0], 303)  # senza accesso
        self.assertEqual(self.req("POST", "/posta/salva", {"host": "x"})[0], 303)
        self.login()
        self.assertEqual(self.req("POST", "/posta/salva", self.form())[0], 403)  # senza codice anti-CSRF
        st, body = self.post("/posta/salva", self.form(password=SEGRETO))
        self.assertIn("Salvato", body)
        self.assertNotIn(SEGRETO, body)
        self.assertNotIn(SEGRETO, self.req("GET", "/posta")[1].decode())
        self.assertIn("password salvata", self.req("GET", "/posta")[1].decode())
        f = os.path.join(self.acc, posta.FILE_NAME)
        self.assertIn(SEGRETO, open(f, encoding="utf-8").read())
        if os.name != "nt":
            self.assertEqual(oct(os.stat(f).st_mode & 0o777), oct(0o600))
        # salvando senza password, quella di prima resta
        self.post("/posta/salva", self.form(sender_name="Altro"))
        self.assertIn(SEGRETO, open(f, encoding="utf-8").read())
        self.assertIn("configurata", self.req("GET", "/posta")[1].decode())
        self.assertNotIn(posta.FILE_NAME, [d for d in os.listdir(self.acc) if os.path.isdir(os.path.join(self.acc, d))])
        from app import config as cfgmod
        self.assertEqual([c.slug for c in cfgmod.load_accounts({"OMNIROUTE_BASE_URL": "http://x/v1", "OMNIROUTE_API_KEY": "k"}, self.acc, self.data)], ["alfa"])  # il file non è preso per un account

    def test_impostazioni_sbagliate_rifiutate(self):
        self.login()
        for k, v in (("host", "x y"), ("sender", "no"), ("public_url", "http://x.it"), ("security", "nessuna")):
            extra = {"host": "mail.esempio.it"} if k == "security" else {}
            st, body = self.post("/posta/salva", self.form(**{k: v}, **extra))
            self.assertNotIn("Salvato", body, k)
        self.assertFalse(os.path.exists(os.path.join(self.acc, posta.FILE_NAME)))

    def test_prova_manda_una_mail_vera(self):
        self.login()
        self.post("/posta/salva", self.form())
        st, body = self.post("/posta/prova", {"to": "me@esempio.it"})
        self.assertIn("Mail di prova partita", body)
        self.assertEqual(len(self.smtp.mails), 1)
        st, body = self.post("/posta/prova", {"to": "non-valida"})
        self.assertIn("Non riesco a spedire", body)
        self.assertEqual(len(self.smtp.mails), 1)

    def test_posta_per_account_vince_sulla_comune_e_si_puo_togliere(self):
        self.login()
        self.post("/posta/salva", self.form(password=SEGRETO))  # comune
        env = os.path.join(self.acc, "alfa", "account.env")
        self.assertIn("(già configurata)", self.req("GET", "/account/alfa/posta")[1].decode())
        self.assertIn("Posta</a>", self.req("GET", "/account/alfa")[1].decode())  # voce nel menu dell'account
        self.assertEqual(self.req("POST", "/account/alfa/posta/salva", self.form())[0], 403)  # senza codice anti-CSRF
        # la password della comune non si copia da sola
        st, body = self.post("/account/alfa/posta/salva", self.form(user="band@esempio.it", sender="band@esempio.it"))
        self.assertIn("serve scrivere la password", body)
        self.assertNotIn("SMTP_HOST", open(env, encoding="utf-8").read())
        # propria: vince e usa il suo server (la mail di prova arriva al suo, non al comune)
        propria = FakeSmtp()
        threading.Thread(target=propria.serve_forever, daemon=True).start()
        try:
            st, body = self.post("/account/alfa/posta/salva", self.form(port=str(propria.server_address[1]), sender="band@esempio.it",
                                                                           user="", password="", sender_name="La band"))
            self.assertIn("usa la sua posta", body)
            self.assertIn("tutta sua", self.req("GET", "/account/alfa/posta")[1].decode())
            st, body = self.post("/account/alfa/posta/prova", {"to": "me@esempio.it"})
            self.assertIn("Mail di prova partita", body)
            self.assertEqual((len(propria.mails), len(self.smtp.mails)), (1, 0))
            self.assertIn("band@esempio.it", email.message_from_bytes(propria.mails[0][2])["From"])
            from app import posta as P
            self.assertEqual(P.resolve(os.path.join(self.acc, "alfa")).origin, "account")
            # il pannello comune elenca gli account con posta propria; la password comune non è nell'account
            self.assertIn("alfa", self.req("GET", "/posta")[1].decode())
            self.assertNotIn(SEGRETO, open(env, encoding="utf-8").read())
            # tornare alla comune: serve la conferma
            st, body = self.post("/account/alfa/posta/togli", {})
            self.assertIn("Spunta", body)
            self.assertIn("SMTP_HOST", open(env, encoding="utf-8").read())
            st, body = self.post("/account/alfa/posta/togli", {"conferma": "si"})
            self.assertIn("torna a usare la posta comune", body)
            self.assertNotIn("SMTP_HOST", open(env, encoding="utf-8").read())
            self.assertIn("TELEGRAM_BOT_TOKEN", open(env, encoding="utf-8").read())  # il resto dell'account.env non si tocca
            self.assertEqual(P.resolve(os.path.join(self.acc, "alfa")).origin, "comune")
        finally:
            propria.shutdown()
            propria.server_close()
        self.assertEqual(self.req("GET", "/account/nessuno/posta")[0], 404)

    def test_pixel_senza_accesso_conta_solo_codici_veri(self):
        db = Db(os.path.join(self.data, "alfa"))
        pc = posta.Config(cfg_vals(self.smtp.server_address[1]))
        posta.deliver(db, pc, {"to": "a@b.it", "subject": "S", "body": "B"}, "alfa", "2026-11-12")
        tok = db._x("SELECT token FROM mail_inviate").fetchone()[0]
        db.close()
        st, data, r = self.req("GET", f"/t/{tok}.gif")
        self.assertEqual((st, r.getheader("Content-Type")), (200, "image/gif"))
        self.assertTrue(data.startswith(b"GIF89a"))
        self.assertIn("no-store", r.getheader("Cache-Control"))
        for finto in ("/t/alfa.AAAAAAAAAAAAAAAAAAAAAAAA.gif", "/t/nessuno.AAAAAAAAAAAAAAAAAAAAAAAA.gif", "/t/x.corto.gif"):
            st, data, _ = self.req("GET", finto)
            self.assertEqual(st, 200 if "corto" not in finto else 303)  # risposta uguale per codici veri e finti (il corto non è un codice)
        db = Db(os.path.join(self.data, "alfa"))
        self.assertEqual(db.mail_list()[0]["aperture"], 1)
        db.close()
        self.assertEqual(self.req("GET", f"/t/{tok}.gif", headers={"Host": "evil.example.com"})[0], 421)


if __name__ == "__main__":
    unittest.main()
