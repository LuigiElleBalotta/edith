import http.client
import json
import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import accounts, config, panel  # noqa: E402

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


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.acc, self.data = os.path.join(self.tmp.name, "accounts"), os.path.join(self.tmp.name, "data")
        os.makedirs(self.acc)
        self.p = panel.Panel(PW, self.acc, self.data, ENV, checks=CHECKS)
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
