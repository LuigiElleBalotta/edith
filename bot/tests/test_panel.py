import http.client
import json
import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import accounts, config, extensions, panel  # noqa: E402
from app.db import Db  # noqa: E402

PW = "una-password-lunga-12"
TOKEN = "123456:AAH-token-segretissimo-del-bot"
IGTOK = "EAAtokenInstagramSegretissimo"
ENV = {"OMNIROUTE_BASE_URL": "http://ai/v1", "OMNIROUTE_API_KEY": "chiave-comune"}


def fake_tg(t):
    if t != TOKEN:
        raise accounts.WizardError("Telegram non accetta questo codice.")
    return "mio_bot"


def fake_key(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("PRIVATA")
    return "ssh-ed25519 AAAA pub"


def ig_rifiuta(*a):
    raise accounts.WizardError("Instagram non accetta questo token")


CHECKS = {"telegram": fake_tg, "owner": lambda tok, secs=8: {"id": 4242424242, "nome": "Giulia", "username": "giulia"},
          "ai": lambda b, k: "ok", "ig": lambda t, u, v="v23.0": "@giulia (10 follower)", "key": fake_key}


def leggi(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Client:
    def __init__(self, port, host="127.0.0.1"):
        self.port, self.host, self.cookie, self.csrf = port, host, "", ""

    def req(self, method, path, form=None, host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"Host": host or self.host, **(headers or {})}
        if self.cookie:
            h["Cookie"] = self.cookie
        body = urllib.parse.urlencode(form).encode() if form is not None else None
        if body is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body, h)
        r = c.getresponse()
        data = r.read().decode()
        if r.getheader("Set-Cookie"):
            self.cookie = r.getheader("Set-Cookie").split(";")[0]
        c.close()
        return r.status, data, r

    def login(self, pw=PW):
        st, _, r = self.req("POST", "/login", {"password": pw})
        if st == 303:
            _, html, _ = self.req("GET", "/")
            self.csrf = html.split('name="csrf" value="')[1].split('"')[0]
        return st

    def post(self, path, form, **kw):
        return self.req("POST", path, {"csrf": self.csrf, **form}, **kw)

    def upload(self, path, fields, files, csrf=True, host=None):
        """Modulo con file allegato (multipart)."""
        conf = "----prova1234"
        nl = chr(13) + chr(10)
        corpo = b""
        for k, v in ({"csrf": self.csrf, **fields} if csrf else fields).items():
            corpo += (f"--{conf}{nl}Content-Disposition: form-data; name=\"{k}\"{nl}{nl}{v}{nl}").encode()
        for k, (nome, dati) in files.items():
            corpo += (f"--{conf}{nl}Content-Disposition: form-data; name=\"{k}\"; filename=\"{nome}\"{nl}Content-Type: application/octet-stream{nl}{nl}").encode() + dati + nl.encode()
        corpo += f"--{conf}--{nl}".encode()
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {"Host": host or self.host, "Content-Type": f"multipart/form-data; boundary={conf}"}
        if self.cookie:
            h["Cookie"] = self.cookie
        c.request("POST", path, corpo, h)
        r = c.getresponse()
        data = r.read().decode()
        c.close()
        return r.status, data, r


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.acc, self.data = os.path.join(self.tmp.name, "accounts"), os.path.join(self.tmp.name, "data")
        os.makedirs(self.acc)
        self.p = panel.Panel(PW, self.acc, self.data, ENV, checks=CHECKS, ext_root=os.path.join(self.tmp.name, "ext"))
        self.srv = panel.serve(self.p, "127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        self.c = Client(self.port)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def make_account(self, name="alfa"):
        accounts.write_account(self.acc, name, {"TELEGRAM_BOT_TOKEN": TOKEN, "ALLOWED_TELEGRAM_USER_ID": "4242424242",
                                                "META_IG_TOKEN": IGTOK, "META_IG_USER_ID": "17"},
                               {"proprietario": "Giulia", "identita": "Sei <b>il manager</b>", "kb": {"repo": "git@x:y.git", "branch": "main"},
                                "lavori": {"agg": {"hour": 9}}, "utenti": {"4242424242": "Giulia"}})

    # ---- stile e pagina di sistema ----
    def test_foglio_di_stile_locale_e_csp_rigida(self):
        st, body, r = self.c.req("GET", "/static/panel.css")
        self.assertEqual(st, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/css"))
        self.assertGreater(len(body), 2000)
        self.assertEqual(self.c.req("GET", "/static/panel.css", host="evil.example.com")[0], 421)
        csp = self.c.req("GET", "/login")[2].getheader("Content-Security-Policy")
        self.assertIn('/static/panel.css?v=' + panel.CSS_VERSION, self.c.req("GET", "/login")[1])  # l'indirizzo cambia a ogni aggiornamento del foglio di stile
        self.assertEqual(self.c.req("GET", "/static/panel.css?v=" + panel.CSS_VERSION)[0], 200)
        self.assertIn("style-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("<script", self.c.req("GET", "/login")[1])

    def test_pagina_sistema_oscura_i_segreti_e_riavvia_tutto(self):
        from app import logbuf

        class Ctl:
            events = {"alfa": 1}
            rescan = type("E", (), {"set": lambda s: None})()

            def running(self):
                return {"alfa": True}

            def restart_all(self):
                self.fatto = True
                return True
        self.make_account()
        self.p.control = ctl = Ctl()
        for ln in (f"errore con {TOKEN}", f"url https://api.telegram.org/bot123456789:AAHabcdefghijklmnopqrstuvwxyz/getMe", f"chiave {IGTOK} e {PW}"):
            logbuf._lines.append(ln)
        self.p.env["PANEL_PASSWORD"] = PW
        self.assertEqual(self.c.login(), 303)
        st, body, _ = self.c.req("GET", "/system")
        self.assertEqual(st, 200)
        self.assertIn("Stato e registro", body)
        for secret in (TOKEN, IGTOK, PW, "AAHabcdefghijklmnopqrstuvwxyz"):
            self.assertNotIn(secret, body)
        self.assertIn("***", body)
        self.assertEqual(self.c.req("POST", "/system/restart", {})[0], 403)  # senza CSRF
        st, body, _ = self.c.post("/system/restart", {})
        self.assertEqual(st, 200)
        self.assertTrue(ctl.fatto)

    # ---- estensioni, approvazioni, lezioni, catalogo ----
    def adb(self, nome="alfa"):
        db = Db(os.path.join(self.data, nome))
        db.slug, db.ext_root = nome, self.p.ext_root
        return db

    def cat(self, nome):
        with open(os.path.join(os.path.dirname(__file__), "..", "catalogo", nome + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def attiva(self, nome, account="alfa", manifest=None):
        st = extensions.ExtStore(self.p.ext_root, account)
        st.propose(manifest or self.cat(nome))
        st.approve((manifest or self.cat(nome))["id"])
        return st

    def test_pagina_estensione_righe_modifica_elimina(self):
        self.make_account()
        self.attiva("ricettario")
        self.assertEqual(self.c.login(), 303)
        st, body, _ = self.c.req("GET", "/account/alfa/estensioni")
        self.assertEqual(st, 200)
        self.assertIn("Ricettario", body)
        st, body, _ = self.c.req("GET", "/account/alfa/estensioni/ricettario")
        self.assertIn("Aggiungi", body)
        self.assertEqual(self.c.req("POST", "/account/alfa/estensioni/ricettario/riga", {"coll": "ricette", "azione": "aggiungi", "titolo": "x"})[0], 403)  # senza CSRF
        st, body, _ = self.c.post("/account/alfa/estensioni/ricettario/riga", {"coll": "ricette", "azione": "aggiungi", "titolo": "<script>alert(1)</script>", "ingredienti": "uova\nfarina"})
        self.assertEqual(st, 200)
        self.assertIn("Aggiunta", body)
        self.assertNotIn("<script>alert", body)
        self.assertIn("&lt;script&gt;", body)
        st, body, _ = self.c.req("GET", "/account/alfa/estensioni/ricettario/modifica/ricette/1")
        self.assertIn("uova", body)
        st, body, _ = self.c.post("/account/alfa/estensioni/ricettario/riga", {"coll": "ricette", "rid": "1", "azione": "salva", "titolo": "Frittata", "ingredienti": "uova"})
        self.assertIn("Salvato", body)
        self.assertIn("Frittata", body)
        st, body, _ = self.c.post("/account/alfa/estensioni/ricettario/riga", {"coll": "ricette", "rid": "1", "azione": "elimina_chiedi"})
        self.assertIn("Sì, elimina", body)
        self.assertIn("Frittata", self.c.req("GET", "/account/alfa/estensioni/ricettario")[1])  # ancora lì finché non conferma
        st, body, _ = self.c.post("/account/alfa/estensioni/ricettario/riga", {"coll": "ricette", "rid": "1", "azione": "elimina"})
        self.assertIn("Eliminata", body)
        st, body, _ = self.c.post("/account/alfa/estensioni/ricettario/riga", {"coll": "ricette", "azione": "aggiungi", "porzioni": "tante"})
        self.assertIn("obbligatorio", body)

    def test_impostazioni_valori_errori_e_segreti(self):
        self.make_account()
        m = self.cat("meteo")
        m["impostazioni"].append({"chiave": "chiave", "tipo": "segreto", "etichetta": "Chiave del servizio"})
        self.attiva("meteo", manifest=m)
        self.assertEqual(self.c.login(), 303)
        st, body, _ = self.c.post("/account/alfa/estensioni/meteo/impostazioni", {"citta_lat": "45,5", "citta_lon": "9.2", "chiave": "SEGRETISSIMA123"})
        self.assertIn("Impostazioni salvate", body)
        self.assertNotIn("SEGRETISSIMA123", body)
        self.assertIn("impostato", body)
        env = config.parse_env_file(os.path.join(self.acc, "alfa", "account.env"))
        self.assertEqual(env["EXT_METEO_CHIAVE"], "SEGRETISSIMA123")
        self.assertEqual(os.stat(os.path.join(self.acc, "alfa", "account.env")).st_mode & 0o777, 0o600) if os.name != "nt" else None
        st, body, _ = self.c.post("/account/alfa/estensioni/meteo/impostazioni", {"citta_lat": "nord", "citta_lon": "9"})
        self.assertIn("numero", body)

    def test_esegui_ora_spegni_e_accendi(self):
        self.make_account()
        self.attiva("meteo")
        self.p.ext_fetch = lambda url, domini, headers=None: ("application/json", json.dumps({"daily": {"temperature_2m_max": [19], "precipitation_sum": [0]}}))
        self.assertEqual(self.c.login(), 303)
        st, body, _ = self.c.post("/account/alfa/estensioni/meteo/esegui", {})
        self.assertIn("daily.temperature_2m_max.0: 19", body)
        st, body, _ = self.c.post("/account/alfa/estensioni/meteo/attiva", {"on": "0"})
        self.assertIn("Spenta", body)
        self.assertFalse(extensions.ExtStore(self.p.ext_root, "alfa").state("meteo")["attiva"])
        self.assertIn("Acceso", self.c.post("/account/alfa/estensioni/meteo/attiva", {"on": "1"})[1])

    def test_approvazione_dal_pannello_e_non_riproporre_piu(self):
        self.make_account()
        db = self.adb()
        aid = extensions.propose(db, self.cat("timer_cottura"))
        aid2 = extensions.propose(db, self.cat("meteo"))
        db.close()
        self.assertEqual(self.c.login(), 303)
        st, body, _ = self.c.req("GET", "/account/alfa")
        self.assertIn("Estensioni", body)
        st, body, _ = self.c.req("GET", "/account/alfa/estensioni")
        self.assertIn("Da approvare", body)
        self.assertIn("Timer di cottura", body)
        self.assertIn("Vedi il manifest completo", body)
        self.assertEqual(self.c.req("POST", f"/account/alfa/approvazione/{aid}/ok", {})[0], 403)
        st, body, _ = self.c.post(f"/account/alfa/approvazione/{aid}/ok", {})
        self.assertIn("attiva", body)
        self.assertTrue(extensions.ExtStore(self.p.ext_root, "alfa").state("timer_cottura")["attiva"])
        st, body, _ = self.c.post(f"/account/alfa/approvazione/{aid2}/mai", {})
        self.assertIn("non la riproporrò", body)
        db = self.adb()
        self.assertEqual(db.get("ext:mai:meteo"), "1")
        db.close()
        self.assertEqual(self.c.post("/account/alfa/approvazione/9999/ok", {})[0], 404)
        self.assertIn("già", self.c.post(f"/account/alfa/approvazione/{aid}/ok", {})[1])  # già decisa: non si decide due volte

    def test_lezioni_pagina_scarta_e_riattiva(self):
        self.make_account()
        db = self.adb()
        lid = db.lesson_add("Preferisce i post del venerdì", "due volte")[0]
        db.close()
        self.assertEqual(self.c.login(), 303)
        st, body, _ = self.c.req("GET", "/account/alfa/lezioni")
        self.assertIn("venerdì", body)
        self.assertIn("Non riproporre più", body)
        self.assertIn("Fatto", self.c.post(f"/account/alfa/lezioni/{lid}/scarta", {})[1])
        body = self.c.req("GET", "/account/alfa/lezioni")[1]
        self.assertIn("Scartate per sempre", body)
        self.assertIn("Fatto", self.c.post(f"/account/alfa/lezioni/{lid}/riattiva", {})[1])
        self.assertEqual(self.c.post("/account/alfa/lezioni/999/scarta", {})[0], 404)

    def test_catalogo_propone_ma_non_installa(self):
        self.make_account()
        self.assertEqual(self.c.login(), 303)
        st, body, _ = self.c.req("GET", "/account/alfa/catalogo")
        for n in ("Ricettario", "Timer di cottura", "Meteo"):
            self.assertIn(n, body)
        st, body, _ = self.c.post("/account/alfa/catalogo/meteo/proponi", {})
        self.assertIn("Proposta creata", body)
        self.assertIn("Da approvare", body)
        self.assertIsNone(extensions.ExtStore(self.p.ext_root, "alfa").manifest("meteo"))  # non è installata finché non approvi
        self.assertIn("catalogo", self.c.post("/account/alfa/catalogo/inesistente/proponi", {})[1])

    def test_estensioni_di_un_account_non_si_vedono_da_un_altro(self):
        self.make_account("alfa")
        self.make_account("beta")
        self.attiva("ricettario", "alfa")
        self.assertEqual(self.c.login(), 303)
        self.assertIn("Estensione non trovata", self.c.req("GET", "/account/beta/estensioni/ricettario")[1])
        self.assertNotIn("Ricettario", self.c.req("GET", "/account/beta/estensioni")[1])
        self.assertEqual(self.c.post("/account/beta/estensioni/ricettario/riga", {"coll": "ricette", "azione": "aggiungi", "titolo": "x"})[0], 404)

    def test_testi_del_manifest_vengono_neutralizzati_e_percorsi_ostili_non_rompono(self):
        self.make_account()
        m = self.cat("timer_cottura")
        m["nome"] = "<img src=x onerror=alert(1)>"
        m["descrizione"] = "<script>boom()</script>"
        self.attiva("x", manifest=m)
        self.assertEqual(self.c.login(), 303)
        for url in ("/account/alfa/estensioni", "/account/alfa/estensioni/timer_cottura"):
            body = self.c.req("GET", url)[1]
            self.assertNotIn("<img src=x", body)
            self.assertNotIn("<script>boom", body)
        for bad in ("..%2f..%2fetc", "a%2fb", "X" * 40):
            self.assertIn(self.c.req("GET", f"/account/alfa/estensioni/{bad}")[0], (200, 404))
        self.assertIn(self.c.req("GET", "/account/alfa/estensioni/ricettario/modifica/ricette/abc")[0], (404,))

    def test_pagina_esperti_accendi_e_spegni(self):
        self.make_account()
        self.assertEqual(self.c.login(), 303)
        self.assertIn("Esperti", self.c.req("GET", "/account/alfa")[1])
        st, body, _ = self.c.req("GET", "/account/alfa/esperti")
        self.assertEqual(st, 200)
        self.assertIn("Social Media Strategist", body)
        self.assertIn("non può agire", body)
        self.assertEqual(self.c.req("POST", "/account/alfa/esperti/grant_writer/spegni", {})[0], 403)  # senza CSRF
        st, body, _ = self.c.post("/account/alfa/esperti/grant_writer/spegni", {})
        self.assertIn("spento", body)
        with open(os.path.join(self.acc, "alfa", "profile.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d["esperti_spenti"], ["grant_writer"])
        self.assertEqual(d["kb"]["repo"], "git@x:y.git")  # il resto del profilo non si tocca
        self.assertIn("acceso", self.c.post("/account/alfa/esperti/grant_writer/accendi", {})[1])
        self.assertEqual(self.c.post("/account/alfa/esperti/non_esiste/spegni", {})[0], 404)

    # ---- biblioteca ----
    TESTO_CORSO = ("Le storie" + chr(10) * 2 + "Le storie di Instagram durano 24 ore e servono a restare vicino alla community. "
                   "Usa gli adesivi con le domande per aumentare la copertura delle storie e i messaggi diretti. " * 2)

    def test_biblioteca_testo_link_e_file(self):
        self.make_account()
        from app.tools import ToolError

        def finta_fetch(url):  # come la lettura vera: gli indirizzi non pubblici si bloccano
            if "127.0.0.1" in url:
                raise ToolError("indirizzo non pubblico: bloccato")
            return "Una guida sul booking dei locali e dei festival per band emergenti. " * 4
        self.p.lib_fetch = finta_fetch
        self.p.lib_extract = lambda data: [(1, "Pagina uno del corso sui reel e sui sottotitoli " * 5), (2, "Pagina due sulle storie e la copertura " * 5)]
        self.assertEqual(self.c.login(), 303)
        self.assertIn("Biblioteca", self.c.req("GET", "/account/alfa")[1])
        st, body, _ = self.c.req("GET", "/account/alfa/biblioteca")
        self.assertEqual(st, 200)
        self.assertIn("Ancora nessun documento", body)
        self.assertIn("/impara", body)
        st, body, _ = self.c.post("/account/alfa/biblioteca/testo", {"titolo": "<script>alert(1)</script>", "testo": self.TESTO_CORSO})
        self.assertIn("Letto", body)
        self.assertNotIn("<script>alert", body)
        self.assertIn("&lt;script&gt;", body)
        st, body, _ = self.c.post("/account/alfa/biblioteca/link", {"url": "https://esempio.it/guida", "titolo": "Guida booking"})
        self.assertIn("Guida booking", body)
        st, body, _ = self.c.upload("/account/alfa/biblioteca/file", {"titolo": "Corso PDF"}, {"file": ("corso.pdf", b"%PDF-finto")})
        self.assertEqual(st, 200)
        self.assertIn("Corso PDF", body)
        self.assertIn("2 pagine", body)
        st, body, _ = self.c.upload("/account/alfa/biblioteca/file", {}, {"file": ("appunti.txt", self.TESTO_CORSO.encode())})
        self.assertIn("appunti", body)
        st, body, _ = self.c.upload("/account/alfa/biblioteca/file", {}, {"file": ("virus.exe", b"x" * 100)})
        self.assertIn("non supportato", body)
        st, body, _ = self.c.post("/account/alfa/biblioteca/link", {"url": "http://127.0.0.1/segreto"})
        self.assertIn("Non posso aggiungerlo", body)
        st, body, _ = self.c.post("/account/alfa/biblioteca/link", {"url": "https://esempio.it/guida", "titolo": "Guida booking"})
        self.assertIn("era già in biblioteca", body)

    def rifiutato(self, *a, **k):
        """Stato HTTP di un caricamento: se il server rifiuta e chiude prima che il client finisca di inviare, su alcuni sistemi la
        connessione cade (è comunque un rifiuto: 0)."""
        try:
            return self.c.upload(*a, **k)[0]
        except ConnectionError:
            return 0

    def test_biblioteca_sicurezza_del_caricamento(self):
        self.make_account()
        self.assertEqual(self.c.upload("/account/alfa/biblioteca/file", {}, {"file": ("a.txt", b"x" * 100)}, csrf=False)[0], 303)  # senza accesso
        self.assertEqual(self.c.login(), 303)
        self.assertEqual(self.c.upload("/account/alfa/biblioteca/file", {}, {"file": ("a.txt", b"x" * 100)}, csrf=False)[0], 403)  # senza codice anti-CSRF
        self.assertIn(self.rifiutato("/account/alfa/profile", {}, {"file": ("a.txt", b"x")}), (0, 415))  # i file si accettano solo qui
        self.assertIn(self.rifiutato("/login", {}, {"file": ("a.txt", b"x")}), (0, 415))
        self.assertEqual(self.c.upload("/account/alfa/biblioteca/file", {}, {"file": ("a.txt", b"x" * 100)}, host="evil.example.com")[0], 421)
        vecchio = panel.MAX_UPLOAD
        panel.MAX_UPLOAD = 2000
        try:
            self.assertIn(self.rifiutato("/account/alfa/biblioteca/file", {}, {"file": ("a.txt", b"x" * 5000)}), (0, 413))
        finally:
            panel.MAX_UPLOAD = vecchio

    # ---- archivio (uguale per tutti gli account) ----
    def senza_archivio(self, nome="beta"):
        accounts.write_account(self.acc, nome, {"TELEGRAM_BOT_TOKEN": TOKEN, "ALLOWED_TELEGRAM_USER_ID": "4242424242"},
                               {"proprietario": "Luca", "utenti": {"4242424242": "Luca"}})

    def test_archivio_interno_da_sito_per_account_senza_archivio(self):
        self.senza_archivio()
        self.assertEqual(self.c.login(), 303)
        st, body, _ = self.c.req("GET", "/account/beta/archivio")
        self.assertIn("Crea l&#x27;archivio interno", body)
        self.assertIn("Archivio</a>", self.c.req("GET", "/account/beta")[1])  # voce nel menu dell'account
        self.assertEqual(self.c.req("POST", "/account/beta/archivio/attiva", {})[0], 403)  # senza codice anti-CSRF
        self.assertIn("Archivio creato", self.c.post("/account/beta/archivio/attiva", {})[1])
        self.assertEqual(json.load(open(os.path.join(self.acc, "beta", "profile.json"), encoding="utf-8"))["kb"], {"tipo": "interno"})
        self.assertIn("già un archivio", self.c.post("/account/beta/archivio/attiva", {})[1])
        # nota nuova, poi modifica: la versione di prima resta in .versioni
        self.assertIn("Salvato «note/idee.md»", self.c.post("/account/beta/archivio/nota", {"percorso": "note/idee", "testo": "uno <b>x</b>"})[1])
        self.c.post("/account/beta/archivio/nota", {"percorso": "note/idee.md", "testo": "due"})
        self.assertIn("note/idee.md", self.c.req("GET", "/account/beta/archivio")[1])
        ed = self.c.req("GET", "/account/beta/archivio/modifica?p=note/idee.md")[1]
        self.assertIn("due", ed)
        radice = os.path.join(self.data, "beta", "archivio")
        self.assertEqual(open(os.path.join(radice, "note", "idee.md"), encoding="utf-8").read(), "due")
        self.assertEqual(len(os.listdir(os.path.join(radice, ".versioni"))), 1)
        self.assertNotIn(".versioni", self.c.req("GET", "/account/beta/archivio")[1].replace("Quando modifichi un file, la versione di prima resta salvata", ""))
        self.assertEqual(self.c.req("GET", "/account/alfa/archivio")[0], 404)  # account inesistente

    def test_archivio_percorsi_vietati_e_testo_escapato(self):
        self.senza_archivio()
        self.assertEqual(self.c.login(), 303)
        self.c.post("/account/beta/archivio/attiva", {})
        radice = os.path.join(self.data, "beta", "archivio")
        for brutto in ("../fuori.md", "secrets/chiave.md", ".versioni/x.md", ".git/config.md", "a/../../b.md", "x.exe"):
            self.assertIn("Non posso salvarlo", self.c.post("/account/beta/archivio/nota", {"percorso": brutto, "testo": "x"})[1], brutto)
        self.assertFalse(os.path.exists(os.path.join(self.data, "beta", "fuori.md")))
        self.c.post("/account/beta/archivio/nota", {"percorso": "/etc/passwd.md", "testo": "x"})  # la barra iniziale si toglie: resta DENTRO l'archivio
        self.assertTrue(os.path.exists(os.path.join(radice, "etc", "passwd.md")))
        self.c.post("/account/beta/archivio/nota", {"percorso": "a.md", "testo": "<script>alert(1)</script>"})
        pagina = self.c.req("GET", "/account/beta/archivio/modifica?p=a.md")[1]
        self.assertNotIn("<script>alert(1)</script>", pagina)
        self.assertIn("&lt;script&gt;", pagina)
        self.assertIn("non consentito", self.c.req("GET", "/account/beta/archivio/modifica?p=../x.md")[1])

    def test_archivio_git_dal_sito_accetta_solo_indirizzi_ssh(self):
        self.senza_archivio()
        self.assertEqual(self.c.login(), 303)
        for brutto in ("--upload-pack=touch /tmp/x", "https://x.it/r.git", "/etc/passwd", "git@x:y.git; rm -rf /", "file:///tmp/r"):
            self.assertIn("non va bene", self.c.post("/account/beta/archivio/git", {"repo": brutto})[1], brutto)
        self.assertNotIn("kb", json.load(open(os.path.join(self.acc, "beta", "profile.json"), encoding="utf-8")))
        from app import accounts as acc_mod
        vecchio = acc_mod.make_deploy_key
        acc_mod.make_deploy_key = lambda path: (open(path, "w").write("CHIAVE-PRIVATA-DI-PROVA"), "ssh-ed25519 AAAAPUBBLICA manager-bot")[1]
        try:
            body = self.c.post("/account/beta/archivio/git", {"repo": "git@github.com:utente/archivio.git"})[1]
        finally:
            acc_mod.make_deploy_key = vecchio
        self.assertIn("ssh-ed25519 AAAAPUBBLICA", body)
        self.assertNotIn("CHIAVE-PRIVATA-DI-PROVA", body)  # la chiave privata non si mostra mai
        self.assertEqual(json.load(open(os.path.join(self.acc, "beta", "profile.json"), encoding="utf-8"))["kb"]["repo"], "git@github.com:utente/archivio.git")
        self.assertTrue(os.path.exists(os.path.join(self.acc, "beta", "kbkey")))
        self.assertIn("già un archivio", self.c.post("/account/beta/archivio/attiva", {})[1])

    def test_biblioteca_elimina_ristudia_e_isolamento(self):
        self.make_account("alfa")
        self.make_account("beta")
        self.assertEqual(self.c.login(), 303)
        self.c.post("/account/alfa/biblioteca/testo", {"titolo": "Corso storie", "testo": self.TESTO_CORSO})
        self.assertNotIn("Corso storie", self.c.req("GET", "/account/beta/biblioteca")[1])  # ogni account ha la sua biblioteca
        st, body, _ = self.c.post("/account/alfa/biblioteca/1/elimina_chiedi", {})
        self.assertIn("Sì, elimina", body)
        self.assertIn("Corso storie", self.c.req("GET", "/account/alfa/biblioteca")[1])  # ancora lì finché non conferma
        db = self.adb()
        db._x("UPDATE fonti SET stato='errore' WHERE id=1")
        db.close()
        self.assertIn("di nuovo", self.c.post("/account/alfa/biblioteca/1/ristudia", {})[1])
        db = self.adb()
        self.assertEqual(db._x("SELECT stato FROM fonti WHERE id=1").fetchone()[0], "nuova")
        db.close()
        self.assertIn("eliminato", self.c.post("/account/alfa/biblioteca/1/elimina", {})[1])
        self.assertIn("Ancora nessun documento", self.c.req("GET", "/account/alfa/biblioteca")[1])
        self.assertEqual(self.c.post("/account/alfa/biblioteca/99/elimina", {})[0], 404)
        self.assertEqual(self.c.req("POST", "/account/alfa/biblioteca/1/elimina", {})[0], 403)

    # ---- accesso e difese ----
    def test_senza_login_non_si_vede_niente(self):
        st, body, r = self.c.req("GET", "/")
        self.assertEqual((st, r.getheader("Location")), (303, "/login"))
        self.assertEqual(self.c.req("GET", "/account/alfa")[0], 303)
        self.assertEqual(self.c.req("POST", "/accounts/new", {"step": "start"})[0], 303)

    def test_host_non_ammesso_dns_rebinding(self):
        self.assertEqual(self.c.req("GET", "/login", host="evil.example.com")[0], 421)
        self.assertEqual(self.c.req("POST", "/login", {"password": PW}, host="evil.example.com:8080")[0], 421)
        self.assertEqual(self.c.req("GET", "/login", host="localhost:8787")[0], 200)

    def test_password_sbagliata_e_blocco(self):
        for _ in range(5):
            self.assertEqual(self.c.login("sbagliata"), 401)
        self.assertEqual(self.c.login(PW), 429)  # bloccato anche con la password giusta
        self.assertEqual(self.c.cookie, "")

    def test_cookie_e_intestazioni_di_sicurezza(self):
        st, _, r = self.c.req("POST", "/login", {"password": PW})
        sc = r.getheader("Set-Cookie")
        self.assertIn("HttpOnly", sc)
        self.assertIn("SameSite=Strict", sc)
        self.assertNotIn("Secure", sc)
        _, _, r = self.c.req("POST", "/login", {"password": PW}, headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", r.getheader("Set-Cookie"))
        _, _, r = self.c.req("GET", "/login")
        self.assertIn("default-src 'none'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(r.getheader("Cache-Control"), "no-store")

    def test_csrf_obbligatorio(self):
        self.make_account()
        self.assertEqual(self.c.login(), 303)
        self.assertEqual(self.c.req("POST", "/account/alfa/profile", {"proprietario": "X"})[0], 403)
        self.assertEqual(self.c.req("POST", "/account/alfa/profile", {"csrf": "sbagliato", "proprietario": "X"})[0], 403)
        self.assertEqual(self.c.post("/account/alfa/profile", {"proprietario": "Ok"})[0], 200)

    def test_logout_chiude_la_sessione(self):
        self.c.login()
        self.c.post("/logout", {})
        self.assertEqual(self.c.req("GET", "/")[0], 303)

    # ---- niente segreti, niente script ----
    def test_i_segreti_non_si_mostrano_mai(self):
        self.make_account()
        self.c.login()
        for path in ("/", "/account/alfa"):
            st, body, _ = self.c.req("GET", path)
            self.assertEqual(st, 200)
            for secret in (TOKEN, IGTOK, "chiave-comune", PW):
                self.assertNotIn(secret, body)
        st, body, _ = self.c.post("/account/alfa/check", {})
        self.assertNotIn(TOKEN, body)
        self.assertIn("@mio_bot", body)

    def test_html_nei_campi_viene_neutralizzato(self):
        self.make_account()
        self.c.login()
        self.c.post("/account/alfa/profile", {"proprietario": "<script>alert(1)</script>", "identita": "</textarea><script>x</script>"})
        _, body, _ = self.c.req("GET", "/account/alfa")
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    # ---- modifiche ----
    def test_profilo_salva_solo_i_suoi_campi(self):
        self.make_account()
        self.c.login()
        self.c.post("/account/alfa/profile", {"proprietario": "Giulia R.", "identita": "Nuova", "regole_extra": "uno\n\n due \n",
                                              "ambito": "ricette", "benvenuto": "Ciao!", "strumenti_spenti": "web_browser, grafico", "lavori_spenti": ""})
        d = json.loads(leggi(os.path.join(self.acc, "alfa", "profile.json")))
        self.assertEqual((d["proprietario"], d["identita"], d["ambito"]), ("Giulia R.", "Nuova", "ricette"))
        self.assertEqual(d["regole_extra"], ["uno", "due"])
        self.assertEqual(d["strumenti_spenti"], ["web_browser", "grafico"])
        self.assertEqual(d["kb"]["repo"], "git@x:y.git")      # non toccato
        self.assertEqual(d["lavori"], {"agg": {"hour": 9}})  # non toccato
        self.assertEqual(d["utenti"], {"4242424242": "Giulia"})

    def test_segreti_nuovi_si_scrivono_e_si_verificano(self):
        self.make_account()
        self.c.login()
        st, body, _ = self.c.post("/account/alfa/secrets", {"ig_token": "EAAnuovo", "ig_user_id": "99", "ai_key": "sk-nuova"})
        self.assertNotIn("EAAnuovo", body)
        env = config.parse_env_file(os.path.join(self.acc, "alfa", "account.env"))
        self.assertEqual((env["META_IG_TOKEN"], env["META_IG_USER_ID"], env["OMNIROUTE_API_KEY"]), ("EAAnuovo", "99", "sk-nuova"))
        self.assertEqual(env["TELEGRAM_BOT_TOKEN"], TOKEN)  # le altre righe restano
        if os.name != "nt":
            self.assertEqual(os.stat(os.path.join(self.acc, "alfa", "account.env")).st_mode & 0o777, 0o600)

    def test_token_rifiutato_non_viene_salvato(self):
        self.make_account()
        p2 = panel.Panel(PW, self.acc, self.data, ENV, checks={**CHECKS, "ig": ig_rifiuta})
        srv = panel.serve(p2, "127.0.0.1", 0)
        try:
            c = Client(srv.server_address[1])
            c.login()
            _, body, _ = c.post("/account/alfa/secrets", {"ig_token": "EAAcattivo", "ig_user_id": "17"})
            self.assertIn("non accetta", body)
            self.assertEqual(config.parse_env_file(os.path.join(self.acc, "alfa", "account.env"))["META_IG_TOKEN"], IGTOK)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_proprietari_validati(self):
        self.make_account()
        self.c.login()
        _, body, _ = self.c.post("/account/alfa/owners", {"owners": "abc"})
        self.assertIn("numerici", body)
        self.c.post("/account/alfa/owners", {"owners": "1111111, 2222222"})
        self.assertEqual(config.parse_env_file(os.path.join(self.acc, "alfa", "account.env"))["ALLOWED_TELEGRAM_USER_ID"], "1111111,2222222")

    def test_rimozione_non_cancella_i_dati(self):
        self.make_account()
        os.makedirs(os.path.join(self.data, "alfa"))
        open(os.path.join(self.data, "alfa", "manager.sqlite"), "w").close()
        self.c.login()
        _, body, _ = self.c.post("/account/alfa/remove", {})
        self.assertIn("Spunta", body)
        self.assertTrue(os.path.isdir(os.path.join(self.acc, "alfa")))
        self.c.post("/account/alfa/remove", {"conferma": "si"})
        self.assertEqual(config.account_names(self.acc), [])
        self.assertTrue(os.path.exists(os.path.join(self.data, "alfa", "manager.sqlite")))

    def test_nome_account_con_percorso_ostile(self):
        self.c.login()
        for bad in ("../../etc", "%2e%2e", "A", "x"):
            self.assertEqual(self.c.req("GET", f"/account/{bad}")[0], 404)
            self.assertEqual(self.c.post(f"/account/{bad}/remove", {"conferma": "si"})[0], 404)

    # ---- creazione guidata ----
    def test_creazione_guidata_completa(self):
        self.c.login()

        def w(form):
            return self.c.post("/accounts/new", form)[1]
        self.assertIn("passo 2/5", w({"step": "start", "go": "1", "nome": "Giulia Music", "proprietario": "Giulia", "descrizione": "cantautrice"}))
        self.assertIn("non accetta", w({"step": "token", "go": "1", "token": "sbagliato"}))
        self.assertIn("Chi può usarlo", w({"step": "token", "go": "1", "token": TOKEN}))
        self.assertIn("Sei tu?", w({"step": "owner", "check": "1"}))
        self.assertIn("passo 3/5", w({"step": "owner_ok", "yes": "1"}))
        self.assertIn("passo 4/5", w({"step": "ai", "go": "1", "modo": "comune"}))
        self.assertIn("passo 5/5", w({"step": "ig", "go": "1", "ig_token": IGTOK, "ig_user_id": "17841400000000000"}))
        self.assertIn("Riepilogo", w({"step": "kb", "go": "1", "repo": "git@github.com:giulia/archivio.git"}))
        body = w({"step": "fine", "go": "1"})
        self.assertIn("Account creato", body)
        self.assertIn("ssh-ed25519 AAAA pub", body)
        for secret in (TOKEN, IGTOK):
            self.assertNotIn(secret, body)
        cfg, = config.load_accounts(ENV, self.acc, self.data)
        self.assertEqual((cfg.slug, cfg.telegram_token, cfg.allowed_user_id, cfg.ig_token), ("giulia-music", TOKEN, 4242424242, IGTOK))
        self.assertEqual(cfg.kb_repo, "git@github.com:giulia/archivio.git")
        d = json.loads(leggi(os.path.join(self.acc, "giulia-music", "profile.json")))
        self.assertIn("cantautrice", d["identita"])
        self.assertEqual(d["utenti"], {"4242424242": "Giulia"})

    def test_creazione_id_a_mano_e_nome_gia_usato(self):
        self.make_account("alfa")
        self.c.login()

        def w(form):
            return self.c.post("/accounts/new", form)[1]
        self.assertIn("già usato", w({"step": "start", "go": "1", "nome": "alfa"}))
        w({"step": "start", "go": "1", "nome": "Beta"})
        w({"step": "token", "go": "1", "token": TOKEN})
        self.assertIn("numero", w({"step": "owner", "manual": "1", "manual_id": "abc"}))
        self.assertIn("passo 3/5", w({"step": "owner", "manual": "1", "manual_id": "99887766"}))

    def test_avvio_da_ambiente(self):
        self.assertIsNone(panel.start_from_env(None, {}))
        self.assertIsNone(panel.start_from_env(None, {"PANEL_PASSWORD": "corta"}))  # password troppo corta: non parte


class UpdateEnvTests(unittest.TestCase):
    def test_conserva_commenti_e_ordine(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "account.env")
            with open(p, "w") as f:
                f.write("# nota\nA=1\nB=2\n")
            panel.update_env(p, {"B": "9", "C": "3"}, remove=["A"])
            self.assertEqual(leggi(p), "# nota\nB=9\nC=3\n")


if __name__ == "__main__":
    unittest.main()
