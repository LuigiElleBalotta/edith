import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent import Agent
from app.ai import AiError
from app.db import Db
from app.main import handle_command, is_allowed, safe_name
from app.tg import split_text


class Cfg:
    model_normal, model_reason, model_light = "N", "R", "L"
    history_messages = 10


class FakeAi:
    def __init__(self, fail_models=()):
        self.fail, self.calls = set(fail_models), []

    def chat(self, model, messages, max_tokens=1200):
        self.calls.append(model)
        if model in self.fail:
            raise AiError("x")
        return f"ok-{model}"


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.db = Db(self.d.name)

    def tearDown(self):
        self.db._c.close()
        self.d.cleanup()

    def test_allowlist(self):
        self.assertTrue(is_allowed(1, 1))
        self.assertFalse(is_allowed(2, 1))
        self.assertFalse(is_allowed(None, 1))

    def test_persistenza_riavvio(self):
        self.db.add_message("user", "ciao")
        self.db.set("tg_offset", "42")
        self.db._c.close()
        db2 = Db(self.d.name)
        self.assertEqual(db2.history(5)[0]["content"], "ciao")
        self.assertEqual(db2.get("tg_offset"), "42")
        self.db = db2

    def test_pausa_riprendi(self):
        self.assertFalse(self.db.paused())
        handle_command("/pausa", self.db)
        self.assertTrue(self.db.paused())
        handle_command("/riprendi", self.db)
        self.assertFalse(self.db.paused())

    def test_scelta_modello_e_ripiego(self):
        ai = FakeAi(fail_models={"R"})
        a = Agent(ai, Cfg, self.db)
        self.assertEqual(a.reply("ciao"), "ok-N")
        out = a.reply("fammi una strategia per il mese")  # sceglie R, fallisce, ripiega su N
        self.assertEqual(out, "ok-N")
        self.assertEqual(ai.calls, ["N", "R", "N"])

    def test_lavori_di_fondo_usano_modello_leggero(self):
        ai = FakeAi()
        a = Agent(ai, Cfg, self.db)
        self.assertEqual(a.background("riassumi", "testo"), "ok-L")
        self.assertEqual(ai.calls, ["L"])
        # non finisce nella conversazione col proprietario
        self.assertEqual(self.db.history(10), [])

    def test_errore_ia_totale(self):
        a = Agent(FakeAi(fail_models={"N", "R"}), Cfg, self.db)
        self.assertIn("non riesco", a.reply("ciao"))

    def test_foto_riconosciuta(self):
        from app.main import pick_media
        msg = {"photo": [{"file_id": "a", "file_unique_id": "u", "file_size": 10},
                         {"file_id": "b", "file_unique_id": "u", "file_size": 999}]}
        obj, name = pick_media(msg)
        self.assertEqual(obj["file_id"], "b")
        self.assertTrue(name.endswith(".jpg"))
        self.assertEqual(pick_media({"text": "x"}), (None, None))

    def test_pulizia_file_vecchi(self):
        from app.main import cleanup_media

        class C2:
            data_dir = self.d.name
            retention_days = 7
        folder = os.path.join(self.d.name, "media")
        os.makedirs(folder)
        vecchio, nuovo = os.path.join(folder, "vecchio.jpg"), os.path.join(folder, "nuovo.jpg")
        for p in (vecchio, nuovo):
            open(p, "wb").write(b"x")
        self.db.add_media(name="vecchio", path=vecchio, status="salvato", size=1)
        self.db.add_media(name="nuovo", path=nuovo, status="salvato", size=1)
        # il primo risulta di 10 giorni fa
        self.db._x("UPDATE media SET ts=ts-864000 WHERE name='vecchio'")
        self.assertEqual(cleanup_media(self.db, C2), 1)
        self.assertFalse(os.path.exists(vecchio))
        self.assertTrue(os.path.exists(nuovo))
        self.assertEqual(cleanup_media(self.db, C2), 0)  # nulla di nuovo da eliminare

    def test_archivio_contenuti(self):
        self.assertEqual(self.db.content_summary(), {})
        self.db.add_content("instagram", "pubblicato", "dichiarato_dal_proprietario", song="X", original_artist="Y")
        self.db.add_content("instagram", "da_rilanciare", "dichiarato_dal_proprietario")
        self.assertEqual(self.db.content_summary(), {"pubblicato": 1, "da_rilanciare": 1})
        with self.assertRaises(ValueError):
            self.db.add_content("instagram", "inventato", "x")
        self.assertIn("Contenuti in archivio", handle_command("/contenuti", self.db))

    def test_opportunita_richiedono_fonte(self):
        with self.assertRaises(ValueError):
            self.db.add_opportunity("Talent X", "", "2026-11-01")
        self.assertIn("Non ho ancora", handle_command("/opportunita", self.db))
        self.db.add_opportunity("Talent X", "https://esempio.it/bando", "2026-11-01", deadline="2027-01-10")
        self.assertEqual(self.db.opportunities_summary(), {"da_valutare": 1})
        self.assertIn("da valutare: 1", handle_command("/opportunita", self.db))

    def test_import_instagram_senza_doppioni_e_senza_token_negli_errori(self):
        import io
        import json as _json
        import urllib.error
        from app.audit_instagram import import_media
        from app.instagram import IgError, Instagram

        pagine = [
            {"data": [{"id": "1", "permalink": "https://i/1", "timestamp": "2026-11-01T18:00:00+0000",
                       "media_product_type": "REELS", "caption": "cover", "like_count": 5, "comments_count": 1}],
             "paging": {"next": "https://graph.facebook.com/next"}},
            {"data": [{"id": "2", "permalink": "https://i/2", "timestamp": "2026-10-01T10:00:00+0000",
                       "media_type": "IMAGE"}]},
        ]
        chiamate = []

        def apri(req, timeout=0):
            chiamate.append(req.full_url)
            assert "EAATOKEN" not in req.full_url  # il token va solo nell'intestazione
            return io.BytesIO(_json.dumps(pagine[len(chiamate) - 1]).encode())

        ig = Instagram("EAATOKEN", "123", opener=apri)
        self.assertEqual(import_media(self.db, ig), {"nuovi": 2, "gia_presenti": 0})
        chiamate.clear()
        self.assertEqual(import_media(self.db, Instagram("EAATOKEN", "123", opener=apri)),
                         {"nuovi": 0, "gia_presenti": 2})
        self.assertEqual(self.db.content_summary(), {"da_classificare": 2})

        def fallisce(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 400, "x", {}, io.BytesIO(
                b'{"error":{"message":"Invalid token EAATOKEN"}}'))
        with self.assertRaises(IgError) as cm:
            Instagram("EAATOKEN", "123", opener=fallisce).profile()
        self.assertNotIn("EAATOKEN", str(cm.exception))

    def test_classificazione_provvisoria(self):
        from app.classify_content import classify_batch, parse_answer

        class Cfg2(Cfg):
            pass

        ids = [self.db.add_content("instagram", "da_classificare", "instagram_api", caption=c,
                                   original_url=f"https://i/{n}", media_type="REELS")
               for n, c in enumerate(["cover Linkin Park", "il mio cane Nala", "boh", "ancora boh"])]
        risposta = ('Ecco: [{"id": %d, "categoria": "musica", "canzone": "Powerless", "artista_originale": "Linkin Park"},'
                    '{"id": %d, "categoria": "personale"},{"id": %d, "categoria": "incerto"},'
                    '{"id": 99999, "categoria": "musica"}]') % (ids[0], ids[1], ids[2])

        class AiFisso:
            def chat(self, model, messages, max_tokens=900):
                return risposta
        a = Agent(AiFisso(), Cfg2, self.db)
        seen = set()
        self.assertEqual(classify_batch(self.db, a, batch_size=10, seen=seen), 2)
        s = self.db.content_summary()
        self.assertEqual(s, {"pubblicato": 1, "personale_non_gestito": 1, "da_classificare": 2})
        # l'ipotesi è marcata come tale, l'id inventato è ignorato
        nota = self.db._x("SELECT notes,song FROM content_items WHERE id=?", (ids[0],)).fetchone()
        self.assertIn("ipotesi_IA", nota[0])
        self.assertEqual(nota[1], "Powerless")
        # un secondo giro non riprova gli stessi
        self.assertEqual(classify_batch(self.db, a, batch_size=10, seen=seen), 0)
        self.assertEqual(parse_answer("niente json"), [])

    def test_classificazione_automatica_di_tutti_i_pendenti(self):
        from app.classify_content import classify_pending
        ids = [self.db.add_content("instagram", "da_classificare", "instagram_api", caption=c,
                                   original_url=f"https://i/{n}", media_type="REELS")
               for n, c in enumerate(["End of Beginning", "il mio cane", "boh"])]
        chiamate = []

        class AiFisso:
            def chat(self, model, messages, max_tokens=900):
                chiamate.append(1)
                return ('[{"id": %d, "categoria": "musica", "canzone": "End of Beginning"},'
                        '{"id": %d, "categoria": "personale"},{"id": %d, "categoria": "incerto"}]') % tuple(ids)
        a = Agent(AiFisso(), Cfg, self.db)
        out = classify_pending(self.db, a)
        self.assertEqual(out, {"musicali": 1, "personali": 1, "incerti": 1})
        self.assertEqual(len(chiamate), 1)  # l'incerto non fa ripetere all'infinito
        self.assertIn("musicali", self.db.get("classif:ultimo"))
        self.assertEqual(classify_pending(self.db, a)["incerti"], 1)  # al giro dopo riprova gli incerti (e resta bloccato)
        self.assertEqual(self.db.content_summary()["da_classificare"], 1)
        # IA giù: riportato, nulla sbloccato
        class AiGiu:
            def chat(self, *a, **k):
                from app.ai import AiError
                raise AiError("giù")
        self.assertIn("errore", classify_pending(self.db, Agent(AiGiu(), Cfg, self.db)))
        self.assertEqual(classify_pending(Db(tempfile.mkdtemp()), a), {})  # niente da fare: nessuna chiamata

    def test_lavoro_di_fondo_ripiega_su_haiku(self):
        from app.ai import AiError
        usati = []

        class AiCombo:
            def chat(self, model, messages, max_tokens=900):
                usati.append(model)
                if model == "L":
                    raise AiError("TimeoutError")
                return "ok"
        a = Agent(AiCombo(), Cfg, self.db)
        self.assertEqual(a.background("x", "y"), "ok")
        self.assertEqual(usati, ["L", "cc/claude-haiku-5-5"])

        class AiGiu:
            def chat(self, *a, **k):
                raise AiError("giù")
        with self.assertRaises(AiError):
            Agent(AiGiu(), Cfg, self.db).background("x", "y")

    def test_backup_database_e_rotazione(self):
        import sqlite3
        from app.main import backup_db

        class C3:
            data_dir = self.d.name
        self.db.add_message("user", "da salvare")
        # simulo 9 copie vecchie: ne devono restare 7 in totale dopo il nuovo backup
        folder = os.path.join(self.d.name, "backups")
        os.makedirs(folder)
        for i in range(9):
            open(os.path.join(folder, f"manager-2020010{i}-000000.sqlite"), "wb").close()
        dest = backup_db(self.db, C3)
        self.assertEqual(len([f for f in os.listdir(folder) if f.startswith("manager-")]), 7)
        c = sqlite3.connect(dest)
        self.assertEqual(c.execute("select content from messages").fetchone()[0], "da salvare")
        c.close()

    def test_split_e_nome(self):
        parts = split_text("a\n" * 5000)
        self.assertTrue(all(len(p) <= 3800 for p in parts))
        self.assertEqual(safe_name("../../etc/passwd"), ".._.._etc_passwd")


if __name__ == "__main__":
    unittest.main()
