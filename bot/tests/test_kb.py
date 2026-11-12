import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import approvals
from app.agent import Agent
from app.db import Db
from app.kb import KbError, KnowledgeBase
from app.tools import Tools


class ArchivioInternoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = KnowledgeBase(os.path.join(self.tmp.name, "archivio"), local=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_configurato_senza_git_e_sync_vede_i_cambiamenti(self):
        self.assertTrue(self.kb.configured)
        r0 = self.kb.sync()
        self.assertEqual(r0["file_cambiati"], [])
        self.kb.write_local("note/a.md", "uno")
        r1 = self.kb.sync()
        self.assertEqual(r1["file_cambiati"], ["note/a.md"])
        self.assertNotEqual(r1["commit"], r0["commit"])
        self.assertEqual(self.kb.sync()["file_cambiati"], [])  # niente di nuovo dopo
        self.assertEqual(self.kb.head(), self.kb.sync()["commit"])

    def test_scrittura_con_versioni_e_percorsi_vietati(self):
        self.kb.write_local("a.md", "uno")
        self.kb.write_local("a.md", "due")
        self.assertEqual(self.kb.read("a.md"), "due")
        ver = os.listdir(os.path.join(self.kb.root, ".versioni"))
        self.assertEqual(len(ver), 1)
        self.assertEqual(open(os.path.join(self.kb.root, ".versioni", ver[0]), encoding="utf-8").read(), "uno")
        for brutto in ("../x.md", "secrets/k.md", ".versioni/a.md", ".stato/s.md", "a.exe"):
            with self.assertRaises(KbError):
                self.kb.write_local(brutto, "x")
        self.assertEqual([f["percorso"] for f in self.kb.files()], ["a.md"])  # .versioni e .stato non si vedono
        self.assertEqual(self.kb.search("uno"), [])  # nemmeno nella ricerca

    def test_apply_dopo_approvazione_scrive_in_locale(self):
        self.assertEqual(self.kb.apply("b.md", "ciao", "motivo"), "archivio interno")
        self.assertEqual(self.kb.read("b.md"), "ciao")

    def test_indirizzi_repository_validi(self):
        from app.kb import valid_repo
        self.assertTrue(valid_repo("git@github.com:utente/archivio.git"))
        self.assertTrue(valid_repo("ssh://git@host.it:2222/utente/r.git"))
        for brutto in ("", "-oProxyCommand=x", "--upload-pack=x", "https://x/y.git", "/tmp/r", "git@x:y.git x", "git@x:../y", "file:///x"):
            self.assertFalse(valid_repo(brutto), brutto)


class Cfg:
    model_normal, model_reason, model_light = "N", "R", "L"
    history_messages = 10


def git(*a, cwd):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", *a], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


LEADS = ("username,full_name,categoria,sottocategoria,zona,priorita,is_follower,is_following,mutual,nota,profile_url,contatti\n"
         "locale_a,Locale A,locale,pub,Viadana,1,0,0,0,\"nota A\",https://www.instagram.com/locale_a/,tel 333\n"
         "locale_b,Locale B,evento,sagra,Mantova,2,0,0,0,nota B,https://www.instagram.com/locale_b/,\n")
LOG = ("username,data_invio,canale,tipo_messaggio,esito,risposta_note,followup_previsto\n"
       "locale_a,2026-10-07,dm_instagram,primo,inviato,x,\n")


class KbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.bare = os.path.join(t, "origin.git")
        work = os.path.join(t, "work")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.bare], check=True)
        os.makedirs(work)
        git("init", "-q", "-b", "main", cwd=work)
        for rel, txt in (("README.md", "# Archivio\nRegola: mai pubblicare senza approvazione\n"), ("data/leads_booking.csv", LEADS),
                         ("data/outreach_log.csv", LOG), ("secrets/instagram.md", "PASSWORD-SEGRETA"), ("core/regole.md", "Tono: diretto\n"),
                         ("ops/gateway/gateway.py", "x = 1\n"), (".env", "TOKEN=abc")):
            os.makedirs(os.path.dirname(os.path.join(work, rel)) or work, exist_ok=True)
            open(os.path.join(work, rel), "w", encoding="utf-8").write(txt)
        git("add", "-A", cwd=work)
        git("commit", "-q", "-m", "iniziale", cwd=work)
        git("remote", "add", "origin", self.bare, cwd=work)
        git("push", "-q", "origin", "main", cwd=work)
        self.work = work
        self.kb = KnowledgeBase(os.path.join(t, "data", "kb"), repo=self.bare, write_branch="manager")
        self.db = Db(os.path.join(t, "db"))

    def tearDown(self):
        self.db._c.close()
        self.tmp.cleanup()

    def test_sync_lettura_e_segreti_mai_visibili(self):
        r = self.kb.sync()
        self.assertTrue(r["commit"])
        nomi = [e["nome"] for e in self.kb.listdir("")]
        self.assertIn("README.md", nomi)
        for vietato in ("secrets/", ".git/", ".env"):
            self.assertNotIn(vietato, nomi)
        for rel in ("secrets/instagram.md", ".env", "../fuori.txt", "/etc/passwd", "ops/gateway/gateway.py", ".git/config"):
            with self.assertRaises(KbError):
                self.kb.read(rel)
        self.assertEqual(self.kb.search("PASSWORD-SEGRETA"), [])  # la ricerca non entra nei segreti
        self.assertEqual(self.kb.search("mai pubblicare")[0]["file"], "README.md")
        # novità: un nuovo commit sul remoto compare come file cambiati
        open(os.path.join(self.work, "core/nuovo.md"), "w", encoding="utf-8").write("ciao\n")
        open(os.path.join(self.work, "secrets/altro.md"), "w", encoding="utf-8").write("x\n")
        git("add", "-A", cwd=self.work); git("commit", "-q", "-m", "n", cwd=self.work); git("push", "-q", "origin", "main", cwd=self.work)
        r2 = self.kb.sync()
        self.assertEqual(r2["file_cambiati"], ["core/nuovo.md"])  # i riservati non vengono nemmeno nominati

    def test_modifica_solo_dopo_approvazione_su_ramo_separato(self):
        self.kb.sync()
        t = Tools(self.db, kb=self.kb)
        out = t.run("kb_proponi_modifica", {"percorso": "core/regole.md", "motivo": "nuova regola",
                                            "testo_da_sostituire": "Tono: diretto", "nuovo_testo": "Tono: diretto e caldo"})
        self.assertIn("NON è ancora cambiato", out)
        aid = t.take_proposals()[0]
        self.assertEqual(open(os.path.join(self.kb.root, "core/regole.md"), encoding="utf-8").read(), "Tono: diretto\n")  # non scritto
        self.assertEqual(git("ls-remote", "--heads", self.bare, "manager", cwd=self.work), "")                           # non pubblicato
        approvals.HOOKS["modifica_kb"] = lambda db, a: "Salvato " + self.kb.apply(a["extra"]["percorso"], a["extra"]["contenuto"], "msg")
        st, msg = approvals.decide(self.db, aid, "ok")
        self.assertEqual(st, "approvata")
        self.assertIn("manager@", msg)
        self.assertIn("manager", git("ls-remote", "--heads", self.bare, cwd=self.work))
        self.assertNotIn("manager", git("branch", "--show-current", cwd=self.kb.root) or "")  # torna sul ramo di lettura
        self.assertIn("caldo", git("show", "manager:core/regole.md", cwd=self.kb.root))
        # main resta intatto
        self.assertEqual(git("show", "origin/main:core/regole.md", cwd=self.kb.root), "Tono: diretto")
        # rifiutata = niente scritto; percorsi vietati e testo ambiguo = errore
        t.run("kb_proponi_modifica", {"percorso": "core/regole.md", "motivo": "x", "contenuto": "altro"})
        approvals.decide(self.db, t.take_proposals()[0], "no")
        self.assertIn("Errore", t.run("kb_proponi_modifica", {"percorso": "secrets/instagram.md", "motivo": "x", "contenuto": "ciao"}))
        self.assertIn("Errore", t.run("kb_proponi_modifica", {"percorso": "ops/gateway/gateway.py", "motivo": "x", "contenuto": "y = 2"}))
        self.assertIn("Errore", t.run("kb_proponi_modifica", {"percorso": "core/regole.md", "motivo": "x", "testo_da_sostituire": "non c'è", "nuovo_testo": "y"}))

    def test_importa_lead_e_storico_invii(self):
        self.kb.sync()
        t = Tools(self.db, kb=self.kb)
        r = json.loads(t.run("kb_importa_lead", {}))
        self.assertEqual((r["contatti_nuovi"], r["gia_contattati_registrati"]), (2, 1))
        a = self.db.contacts_list("Locale A")[0]
        self.assertEqual((a["stato"], a["ultimo_contatto"], a["prossima_azione_il"], a["messaggi_inviati"]),
                         ("in_attesa_risposta", "2026-10-07", "2026-10-21", 1))
        self.assertEqual(self.db.contacts_list("Locale B")[0]["stato"], "da_valutare")
        r2 = json.loads(t.run("kb_importa_lead", {}))  # ripetibile
        self.assertEqual((r2["contatti_nuovi"], r2["gia_contattati_registrati"]), (0, 0))
        self.assertEqual(self.db.contacts_list("Locale A")[0]["messaggi_inviati"], 1)

    def test_strumenti_kb_solo_se_configurato_e_profilo(self):
        self.assertEqual(Tools(self.db).run("kb_novita", {}), "Strumento non disponibile.")
        nomi = [s["function"]["name"] for s in Tools(self.db, kb=self.kb).specs]
        self.assertIn("kb_leggi", nomi)
        spenti = [s["function"]["name"] for s in Tools(self.db, kb=self.kb, disabled=["kb_leggi", "web_cerca"]).specs]
        self.assertNotIn("kb_leggi", spenti)
        self.assertNotIn("web_cerca", spenti)
        self.assertEqual(Tools(self.db, kb=KnowledgeBase(self.tmp.name + "/x", repo="")).run("kb_novita", {}), "Errore: archivio non configurato per questo account")

    def test_voce_edith_predefinita_neutra_e_personalizzata(self):
        d = os.path.dirname(self.db.path)
        mk = lambda: Agent(None, Cfg(), self.db, Tools(self.db)).system()
        s = mk()
        self.assertIn("E.D.I.T.H.", s)  # senza altro: parla come lei
        self.assertIn("Regole ferree", s)
        self.assertLess(s.index("Regole ferree"), s.index("La tua VOCE"))  # lo stile viene DOPO le regole: non le scavalca
        self.assertIn("valgono più del personaggio", s)
        json.dump({"voce": "neutra"}, open(os.path.join(d, "profile.json"), "w", encoding="utf-8"))
        self.assertNotIn("La tua VOCE", mk())
        json.dump({"voce": "personalizzata", "voce_testo": "Parla con calma, da buon amico."}, open(os.path.join(d, "profile.json"), "w", encoding="utf-8"))
        s = mk()
        self.assertIn("Parla con calma, da buon amico.", s)
        self.assertNotIn("E.D.I.T.H.", s)
        json.dump({"voce": "personalizzata", "voce_testo": ""}, open(os.path.join(d, "profile.json"), "w", encoding="utf-8"))
        self.assertNotIn("La tua VOCE", mk())  # personalizzata ma vuota: nessuno stile inventato
        json.dump({"voce": "boh"}, open(os.path.join(d, "profile.json"), "w", encoding="utf-8"))
        self.assertIn("E.D.I.T.H.", mk())  # valore sconosciuto: si torna al predefinito

    def test_profilo_identita_regole_e_lavori(self):
        from app import profile as prof
        from app.scheduler import JOBS, jobs_for
        d = os.path.dirname(self.db.path)
        self.assertEqual(prof.load(d)["identita"], "")  # senza file: comportamento storico
        base = Agent(None, Cfg(), self.db, Tools(self.db)).system()
        self.assertIn("manager social digitale", base)  # prompt generico: nessun nome fisso
        json.dump({"identita": "Sei il manager della band Test. Parli in italiano.", "regole_extra": ["Mai cachet nei primi messaggi."],
                   "lavori_spenti": ["ricerca_opportunita"], "lavori": {"agg": {"weekday": 0, "hour": 9, "minute": 0, "prompt": "p"}}},
                  open(os.path.join(d, "profile.json"), "w", encoding="utf-8"))
        s = Agent(None, Cfg(), self.db, Tools(self.db)).system()
        self.assertIn("band Test", s)
        self.assertNotIn("manager social digitale per", s)  # l'identità del profilo sostituisce la presentazione
        self.assertIn("Regole ferree", s)             # le regole ferree restano sempre
        self.assertIn("Mai cachet nei primi messaggi.", s)
        jobs = jobs_for(prof.load(d))
        self.assertNotIn("ricerca_opportunita", jobs)
        self.assertIn("agg", jobs)
        self.assertIn("ricerca_opportunita", JOBS)    # i valori di base non cambiano
        self.assertEqual(prof.load(os.path.join(d, "nonesiste"))["lavori_spenti"], [])
        open(os.path.join(d, "profile.json"), "w").write("{rotto")
        self.assertEqual(prof.load(d)["regole_extra"], [])

    def test_lavori_dell_archivio_partono_solo_dove_servono(self):
        import datetime as dt
        from app.scheduler import CONDS
        now = dt.datetime(2026, 11, 16, 9, 30)
        self.assertFalse(CONDS["kb_attivo"](self.db, now))
        self.db.set("kb:attivo", "1")
        self.assertTrue(CONDS["kb_attivo"](self.db, now))
        self.assertFalse(CONDS["contatti_da_pianificare"](self.db, now))
        self.db.contact_add("X", "locale", "https://x.it")
        self.assertTrue(CONDS["contatti_da_pianificare"](self.db, now))

    def test_piu_proprietari(self):
        import datetime as dt
        from app.main import is_allowed, owner_ids
        from app.scheduler import apply_contact_action, run_contact_reminders

        class C1:
            allowed_user_id = 7
        class C2:
            allowed_user_id = 7
            allowed_user_ids = (7, 8)
        self.assertEqual(owner_ids(C1), (7,))
        self.assertEqual(owner_ids(C2), (7, 8))
        self.assertTrue(is_allowed(8, owner_ids(C2)))
        self.assertFalse(is_allowed(9, owner_ids(C2)))
        self.assertTrue(is_allowed(7, 7))

        class Tg:
            dest = []
            def send(self, chat, text, silent=False, **k):
                Tg.dest.append(chat)
        cid = self.db.contact_add("Locale", "locale", "https://l.it", status="da_scrivere", next_followup="2026-11-10")
        ids = run_contact_reminders(self.db, Tg(), [7, 8], dt.datetime(2026, 11, 12, 11, 0))
        self.assertEqual((ids, Tg.dest), ([cid], [7, 8]))  # lo ricevono entrambi
        oggi = dt.date(2026, 11, 12)
        self.assertIn("Segnato", apply_contact_action(self.db, cid, "ok", oggi))
        self.assertIn("nessun doppione", apply_contact_action(self.db, cid, "ok", oggi))  # il secondo tocco non raddoppia
        self.assertEqual(self.db.contact_get(cid)["messaggi_inviati"], 1)



class GruppoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(self.tmp.name)

        class Cfg2:
            allowed_user_id = 1
            allowed_user_ids = (1,)
        self.cfg = Cfg2

        class Tg:
            sent = []
            def send(s, chat, text, **k):
                Tg.sent.append((chat, text)); Tg.kw = k
            def typing(s, chat): pass
            def call(s, *a, **k): return {}
        Tg.sent = []
        self.tg = Tg()

        class Ag:
            profile = {"utenti": {"1": "Marco"}}
            tools = None
            seen = []
            def reply(s, text):
                Ag.seen.append(text); return "risposta"
        Ag.seen = []
        self.ag = Ag()
        self.Tg, self.Ag = Tg, Ag

    def tearDown(self):
        self.db._c.close()
        self.tmp.cleanup()

    def msg(self, uid, text, chat=-100, typ="supergroup", reply=None, name="X"):
        m = {"from": {"id": uid, "first_name": name}, "chat": {"id": chat, "type": typ}, "text": text}
        if reply:
            m["reply_to_message"] = {"from": reply}
        return {"update_id": 1, "message": m}

    def registra(self):
        from app.main import process
        self.db.set("bot_username", "mio_bot")
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/gruppo", name="Marco"))
        self.Tg.sent.clear()
        self.Ag.seen.clear()

    def test_gruppo_risponde_a_tutto_ma_non_quando_parlano_tra_loro(self):
        from app.main import process
        self.registra()
        # messaggio normale di un abilitato: risponde nel gruppo, senza bisogno della menzione
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "che idee hai per sabato?", name="Marco"))
        self.assertEqual(self.Ag.seen, ["[Marco] che idee hai per sabato?"])
        self.assertEqual(self.Tg.sent[-1][0], -100)
        # risposta a un messaggio di un'altra persona senza nominare il bot: parlano tra loro, silenzio
        n = len(self.Tg.sent)
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "sono d'accordo", reply={"id": 7, "is_bot": False, "first_name": "Francesca"}, name="Marco"))
        self.assertEqual(len(self.Tg.sent), n)
        # ma se nomina il bot, o risponde a un messaggio del bot, risponde
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "@mio_bot tu che ne pensi?", reply={"id": 7, "is_bot": False, "first_name": "F"}, name="Marco"))
        self.assertEqual(self.Ag.seen[-1], "[Marco] tu che ne pensi?")
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "e quindi?", reply={"id": 9, "is_bot": True, "username": "mio_bot"}, name="Marco"))
        self.assertEqual(self.Ag.seen[-1], "[Marco] e quindi?")
        # un estraneo non ottiene risposta
        n = len(self.Tg.sent)
        process(self.tg, self.db, self.ag, self.cfg, self.msg(99, "ciao bot"))
        self.assertEqual(len(self.Tg.sent), n)

    def test_gruppo_modalita_solo_menzioni(self):
        from app.main import process
        self.registra()
        json.dump({"gruppo_modalita": "menzioni"}, open(os.path.join(self.tmp.name, "profile.json"), "w", encoding="utf-8"))
        n = len(self.Tg.sent)
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "ciao a tutti", name="Marco"))
        self.assertEqual((len(self.Tg.sent), self.Ag.seen), (n, []))  # senza menzione: silenzio
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "@mio_bot ciao", name="Marco"))
        self.assertEqual(self.Ag.seen, ["[Marco] ciao"])
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/stato", name="Marco"))  # i comandi rispondono sempre
        self.assertIn("Sistema", self.Tg.sent[-1][1])
        # un comando per un altro bot non è per noi
        n = len(self.Tg.sent)
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/stato@altro_bot", name="Marco"))
        self.assertEqual(len(self.Tg.sent), n)

    def test_scrivere_in_privato_risponde_in_privato_anche_con_il_gruppo(self):
        from app.main import destinations, process
        self.registra()
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "ciao in privato", chat=1, typ="private", name="Marco"))
        self.assertEqual(self.Tg.sent[-1][0], 1)  # la risposta resta nella chat privata
        self.assertEqual(destinations(self.cfg, self.db), [-100])  # i messaggi automatici restano SOLO nel gruppo

    def test_avviso_privacy_una_sola_volta_e_stato(self):
        from app.main import group_visibility, handle_command
        self.registra()

        class T2(self.Tg):
            vede = False
            admin = False

            def call(s, metodo, **k):
                if metodo == "getMe":
                    return {"id": 5, "username": "mio_bot", "can_read_all_group_messages": T2.vede}
                if metodo == "getChatMember":
                    return {"status": "administrator" if T2.admin else "member"}
                return {}
        tg = T2()
        self.assertFalse(group_visibility(tg, self.db))
        self.assertEqual(len(self.Tg.sent), 1)
        self.assertIn("BotFather", self.Tg.sent[0][1])
        self.assertEqual(self.Tg.sent[0][0], -100)
        self.assertFalse(group_visibility(tg, self.db))
        self.assertEqual(len(self.Tg.sent), 1)  # niente ripetizioni
        self.assertIn("vedo solo", handle_command("/stato", self.db))
        T2.admin = True  # se lo nominano amministratore, vede tutto
        self.assertTrue(group_visibility(tg, self.db))
        self.assertIn("vedo tutti", handle_command("/stato", self.db))
        T2.admin, T2.vede = False, False
        group_visibility(tg, self.db)
        self.assertEqual(len(self.Tg.sent), 2)  # se torna a non vedere, avvisa di nuovo

    def test_gruppo_condiviso_abilita_e_menzione(self):
        from app.main import destinations, group_chat, owner_ids, process
        self.db.set("bot_username", "mio_bot")
        # prima del /gruppo il gruppo è ignorato; un estraneo è ignorato sempre
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "ciao"))
        process(self.tg, self.db, self.ag, self.cfg, self.msg(99, "/gruppo"))
        self.assertEqual((self.Tg.sent, group_chat(self.db)), ([], None))
        # un proprietario registra il gruppo: da ora i messaggi automatici vanno lì
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/gruppo@mio_bot", name="Marco"))
        self.assertEqual((group_chat(self.db), destinations(self.cfg, self.db)), (-100, [-100]))
        # menzione tolta dal testo, nome di chi parla aggiunto; la risposta torna nel gruppo
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "@mio_bot come va?", name="Marco"))
        self.assertEqual(self.Ag.seen, ["[Marco] come va?"])
        self.assertEqual(self.Tg.sent[-1][0], -100)
        # un altro gruppo non registrato è ignorato anche se scrive un proprietario
        n = len(self.Tg.sent)
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "ciao", chat=-555))
        self.assertEqual(len(self.Tg.sent), n)
        # Marta (id 2) non è abilitata finché un proprietario non risponde al suo messaggio con /abilita
        process(self.tg, self.db, self.ag, self.cfg, self.msg(2, "@mio_bot ciao", name="Marta"))
        self.assertEqual(len(self.Ag.seen), 1)
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/abilita", reply={"id": 2, "first_name": "Marta"}))
        self.assertIn("Marta può usarmi", self.Tg.sent[-1][1])
        self.assertEqual(owner_ids(self.cfg, self.db), (1, 2))
        process(self.tg, self.db, self.ag, self.cfg, self.msg(2, "@mio_bot ciao", name="Marta"))
        self.assertEqual(self.Ag.seen[-1], "[Marta] ciao")
        # /abilita senza risposta, su un bot, o su un proprietario fisso: spiega o rifiuta
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/abilita"))
        self.assertIn("rispondi a un suo messaggio", self.Tg.sent[-1][1])
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/abilita", reply={"id": 7, "is_bot": True}))
        self.assertIn("rispondi a un suo messaggio", self.Tg.sent[-1][1])
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/disabilita", reply={"id": 1, "first_name": "Marco"}))
        self.assertIn("proprietari fissati", self.Tg.sent[-1][1])
        # /disabilita toglie Marta
        process(self.tg, self.db, self.ag, self.cfg, self.msg(1, "/disabilita", reply={"id": 2, "first_name": "Marta"}))
        self.assertEqual(owner_ids(self.cfg, self.db), (1,))

    def test_start_personalizzato_dal_profilo(self):
        import json as _j
        from app.main import handle_command
        self.assertTrue(handle_command("/start", self.db).startswith("Ciao! Sono E.D.I.T.H."))  # predefinito: lo stile di E.D.I.T.H.
        _j.dump({"voce": "neutra"}, open(os.path.join(self.tmp.name, "profile.json"), "w", encoding="utf-8"))
        self.assertTrue(handle_command("/start", self.db).startswith("Ciao! Sono il tuo manager social"))  # voce neutra: tono semplice
        _j.dump({"benvenuto": "Ciao band! Sono il manager social della Band Test."}, open(os.path.join(self.tmp.name, "profile.json"), "w", encoding="utf-8"))
        self.assertTrue(handle_command("/start", self.db).startswith("Ciao band!"))


    def test_tasti_rapidi_e_contatti(self):
        import json as _j
        from app.main import contatti_text, handle_command, process, quick_keyboard
        kb = quick_keyboard(self.db)
        self.assertTrue(kb["is_persistent"] and kb["resize_keyboard"])
        self.assertIn({"text": "/calendario"}, kb["keyboard"][0])
        _j.dump({"tastiera": [["/contatti", "/agenda"], ["niente-slash", "testo"], ["/aiuto"]]},
                open(os.path.join(self.tmp.name, "profile.json"), "w", encoding="utf-8"))
        kb = quick_keyboard(self.db)
        self.assertEqual([[b["text"] for b in r] for r in kb["keyboard"]], [["/contatti", "/agenda"], ["/aiuto"]])  # solo comandi veri
        # /contatti: scaduti, in programma, in attesa
        self.db.contact_add("Locale Uno", "locale", "https://1.it", status="da_scrivere", next_followup="2000-01-01")
        self.db.contact_add("Locale Due", "locale", "https://2.it", status="da_scrivere", next_followup="2999-01-05")
        t = contatti_text(self.db)
        self.assertIn("Locale Uno (primo messaggio)", t)
        self.assertIn("Locale Due", t)
        self.assertEqual(handle_command("/contatti@mio_bot", self.db), t)
        # /start e /menu mostrano i tasti; gli altri comandi no
        process(self.tg, self.db, self.ag, self.cfg, {"update_id": 1, "message": {"from": {"id": 1}, "chat": {"id": 1, "type": "private"}, "text": "/menu"}})
        self.assertIn("keyboard", self.Tg.kw["reply_markup"])
        process(self.tg, self.db, self.ag, self.cfg, {"update_id": 2, "message": {"from": {"id": 1}, "chat": {"id": 1, "type": "private"}, "text": "/contatti"}})
        self.assertIsNone(self.Tg.kw.get("reply_markup"))


if __name__ == "__main__":
    unittest.main()


class AmbitoTests(unittest.TestCase):
    def test_ambito_del_profilo_arriva_al_classificatore(self):
        from app import classify_content as cc
        self.assertIn("cover, canto", cc.istruzione({}))                         # senza profilo: musica
        s = cc.istruzione({"ambito": "ricette, ristorante, eventi in sala"})
        self.assertIn("ricette, ristorante, eventi in sala", s)
        self.assertNotIn("cover, canto", s)
        self.assertNotIn("{ambito}", s)
