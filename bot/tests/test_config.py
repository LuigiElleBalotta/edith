import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config  # noqa: E402

ENV = {"OMNIROUTE_BASE_URL": "http://ai/v1/", "OMNIROUTE_API_KEY": "chiave-comune"}


def _acc(root, name, text):
    d = os.path.join(root, name)
    os.makedirs(d)
    with open(os.path.join(d, "account.env"), "w", encoding="utf-8") as f:
        f.write(text)
    return d


class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.acc = os.path.join(self.tmp.name, "accounts")
        self.data = os.path.join(self.tmp.name, "data")
        os.makedirs(self.acc)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, env=None):
        return config.load_accounts({**ENV, **(env or {})}, self.acc, self.data)

    def test_due_account_separati(self):
        _acc(self.acc, "alfa", "TELEGRAM_BOT_TOKEN=111:AAA\nALLOWED_TELEGRAM_USER_ID=1\nMETA_IG_TOKEN=tok-alfa\nMETA_IG_USER_ID=10\n")
        _acc(self.acc, "beta", "# commento\nTELEGRAM_BOT_TOKEN='222:BBB'\nALLOWED_TELEGRAM_USER_ID=2, 3\nOMNIROUTE_API_KEY=chiave-beta\n")
        a, b = self.load()
        self.assertEqual((a.slug, b.slug), ("alfa", "beta"))
        self.assertEqual(a.data_dir, os.path.join(self.data, "alfa"))
        self.assertNotEqual(a.data_dir, b.data_dir)                       # dati separati
        self.assertEqual((a.telegram_token, b.telegram_token), ("111:AAA", "222:BBB"))
        self.assertEqual(a.ai_api_key, "chiave-comune")                   # la chiave comune vale se l'account non ne ha una sua
        self.assertEqual(b.ai_api_key, "chiave-beta")                     # chiave propria: può avere modelli limitati
        self.assertEqual(a.ai_base_url, "http://ai/v1")
        self.assertEqual((a.ig_token, a.ig_user_id), ("tok-alfa", "10"))
        self.assertEqual(b.ig_token, "")                                  # niente Instagram: nessuna perdita tra account
        self.assertEqual(b.allowed_user_ids, (2, 3))
        self.assertEqual(b.allowed_user_id, 2)
        self.assertEqual(a.profile_dir, os.path.join(self.acc, "alfa"))

    def test_chiave_archivio_trovata_da_sola(self):
        d = _acc(self.acc, "alfa", "TELEGRAM_BOT_TOKEN=1:A\nALLOWED_TELEGRAM_USER_ID=1\nKB_REPO=git@github.com:x/y.git\n")
        open(os.path.join(d, "kbkey"), "w").close()
        (a,) = self.load()
        self.assertEqual(a.kb_key, os.path.join(d, "kbkey"))
        self.assertEqual(a.kb_repo, "git@github.com:x/y.git")

    def test_nomi_non_validi_ignorati(self):
        _acc(self.acc, "ok-1", "TELEGRAM_BOT_TOKEN=1:A\nALLOWED_TELEGRAM_USER_ID=1\n")
        _acc(self.acc, "Maiuscolo", "TELEGRAM_BOT_TOKEN=1:A\nALLOWED_TELEGRAM_USER_ID=1\n")
        self.assertEqual([c.slug for c in self.load()], ["ok-1"])

    def test_modalita_semplice_un_account_nell_ambiente(self):
        env = {"TELEGRAM_BOT_TOKEN": "1:A", "ALLOWED_TELEGRAM_USER_ID": "7", "DATA_DIR": "/dati"}
        (a,) = self.load(env)
        self.assertEqual((a.slug, a.data_dir, a.allowed_user_id), ("default", "/dati", 7))

    def test_nessun_account(self):
        self.assertEqual(self.load(), [])

    def test_account_incompleto_da_errore_chiaro(self):
        _acc(self.acc, "alfa", "TELEGRAM_BOT_TOKEN=1:A\n")  # manca il proprietario
        with self.assertRaises(RuntimeError) as cm:
            self.load()
        self.assertIn("ALLOWED_TELEGRAM_USER_ID", str(cm.exception))
        self.assertNotIn("1:A", str(cm.exception))  # nessun segreto nei messaggi


if __name__ == "__main__":
    unittest.main()
