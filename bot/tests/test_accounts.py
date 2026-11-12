import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import accounts, config  # noqa: E402
from app.accounts import WizardError  # noqa: E402

TOKEN = "123456:AAH-segretissimo-token"
AIKEY = "sk-chiave-ia-segreta"
IGTOK = "EAAtokenInstagramSegreto"


class FakeIO(accounts.IO):
    def __init__(self, answers, secrets, yes):
        self.a, self.s, self.y, self.out = list(answers), list(secrets), list(yes), []

    def ask(self, q, default=""):
        v = self.a.pop(0)
        return v or default

    def secret(self, q):
        return self.s.pop(0)

    def yes(self, q, default=False):
        return self.y.pop(0)

    def say(self, text=""):
        self.out.append(text)


def fake_tg(tok):
    if tok != TOKEN:
        raise WizardError("Telegram non accetta questo codice.")
    return "mio_bot"


CHECKS = {"telegram": fake_tg,
          "owner": lambda tok, say=print: {"id": 4242424242, "nome": "Giulia", "username": "giulia"},
          "ai": lambda base, key: "3 modelli disponibili",
          "ig": lambda tok, uid: "@giulia_music (120 follower)",
          "key": lambda path: (open(path, "w").write("PRIVATA") and None) or "ssh-ed25519 AAAA pubblica"}


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.acc = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def run_add(self, answers, secrets, yes, env=None):
        io = FakeIO(answers, secrets, yes)
        slug = accounts.add(io, {"ACCOUNTS_DIR": self.acc, **(env or {})}, self.acc, CHECKS)
        return slug, io

    def test_creazione_completa(self):
        # domande: nome, nome breve, proprietario, descrizione, indirizzo IA, id instagram, repo
        slug, io = self.run_add(
            ["Giulia Music", "", "Giulia", "cantautrice pop di Milano", "https://ai.example.it/v1", "17841400000000000", "git@github.com:giulia/archivio.git"],
            [TOKEN, AIKEY, IGTOK],
            [True, True, True, True])  # aspetta messaggio, sono io, collego IG, ho un archivio
        self.assertEqual(slug, "giulia-music")
        cfg, = config.load_accounts({"OMNIROUTE_BASE_URL": "x"}, self.acc, "/d")
        self.assertEqual((cfg.telegram_token, cfg.allowed_user_id, cfg.ai_api_key), (TOKEN, 4242424242, AIKEY))
        self.assertEqual((cfg.ig_token, cfg.ig_user_id, cfg.kb_repo), (IGTOK, "17841400000000000", "git@github.com:giulia/archivio.git"))
        self.assertEqual(cfg.ai_base_url, "https://ai.example.it/v1")
        d = os.path.join(self.acc, slug)
        prof = json.load(open(os.path.join(d, "profile.json"), encoding="utf-8"))
        self.assertEqual(prof["proprietario"], "Giulia")
        self.assertIn("cantautrice pop di Milano", prof["identita"])
        self.assertEqual(prof["utenti"], {"4242424242": "Giulia"})
        self.assertEqual(prof["kb"]["write_branch"], "manager")
        self.assertEqual(open(os.path.join(d, "kbkey")).read(), "PRIVATA")
        if os.name != "nt":
            self.assertEqual(os.stat(os.path.join(d, "account.env")).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.join(d, "kbkey")).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.exists(os.path.join(self.acc, ".kbkey-giulia-music")))  # nessun file temporaneo
        text = "\n".join(io.out)
        for secret in (TOKEN, AIKEY, IGTOK, "PRIVATA"):
            self.assertNotIn(secret, text)                                  # nessun segreto a schermo
        self.assertIn("ssh-ed25519 AAAA pubblica", text)                    # solo la parte pubblica della chiave

    def test_minimo_senza_instagram_e_archivio(self):
        slug, io = self.run_add(["Band", "", "Marco", "", "https://ai.example.it/v1"], [TOKEN, AIKEY], [True, True, False, False])
        cfg, = config.load_accounts({"OMNIROUTE_BASE_URL": "x"}, self.acc, "/d")
        self.assertEqual((cfg.ig_token, cfg.kb_repo), ("", ""))
        self.assertFalse(os.path.exists(os.path.join(self.acc, slug, "kbkey")))
        prof = json.load(open(os.path.join(self.acc, slug, "profile.json"), encoding="utf-8"))
        self.assertEqual(prof["identita"], "")  # senza descrizione resta il prompt generico

    def test_chiave_comune_del_server(self):
        env = {"OMNIROUTE_BASE_URL": "https://ai.srv/v1", "OMNIROUTE_API_KEY": "comune"}
        slug, io = self.run_add(["Band", "", "Marco", ""], [TOKEN], [True, True, False, False, False], env)  # chiave propria? no
        text = open(os.path.join(self.acc, slug, "account.env"), encoding="utf-8").read()
        self.assertNotIn("OMNIROUTE_API_KEY", text)  # usa quella comune del server

    def test_codice_bot_sbagliato_si_richiede(self):
        slug, io = self.run_add(["Band", "", "Marco", "", "https://ai.example.it/v1"], ["sbagliato", TOKEN, AIKEY], [True, True, False, False])
        self.assertTrue(any("non accetta" in l for l in io.out))
        self.assertTrue(os.path.isdir(os.path.join(self.acc, slug)))

    def test_id_a_mano_se_non_arriva_il_messaggio(self):
        slug, io = self.run_add(["Band", "", "Marco", "", "99887766", "https://ai.example.it/v1"], [TOKEN, AIKEY], [False, False, False])
        cfg, = config.load_accounts({"OMNIROUTE_BASE_URL": "x"}, self.acc, "/d")
        self.assertEqual(cfg.allowed_user_id, 99887766)

    def test_nome_gia_usato(self):
        self.run_add(["Band", "", "Marco", "", "https://ai.example.it/v1"], [TOKEN, AIKEY], [True, True, False, False])
        with self.assertRaises(WizardError):
            self.run_add(["Band", "", "Marco", ""], [], [])

    def test_slugify_e_rimozione(self):
        self.assertEqual(accounts.slugify("Gli Band Test!"), "gli-band-test")
        slug, io = self.run_add(["Band", "", "Marco", "", "https://ai.example.it/v1"], [TOKEN, AIKEY], [True, True, False, False])
        out = []
        self.assertEqual(accounts.cmd_remove(slug, {"ACCOUNTS_DIR": self.acc}, out.append), 0)
        self.assertEqual(config.account_names(self.acc), [])                  # non viene più caricato
        self.assertTrue(any(n.startswith(f".{slug}.rimosso-") for n in os.listdir(self.acc)))  # ma nulla è cancellato

    def test_list_non_mostra_segreti(self):
        self.run_add(["Band", "", "Marco", "", "https://ai.example.it/v1"], [TOKEN, AIKEY], [True, True, False, False])
        out = []
        accounts.cmd_list({"OMNIROUTE_BASE_URL": "x", "ACCOUNTS_DIR": self.acc}, out.append)
        self.assertIn("band", "\n".join(out))
        self.assertNotIn(TOKEN, "\n".join(out))


if __name__ == "__main__":
    unittest.main()
