import io
import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent import Agent
from app.ai import AiError
from app.db import Db
from app.instagram import IgError
from app.tools import Tools, ToolError, check_public_url, fetch_public, html_to_text


def ris(ip):
    return lambda host, port, proto=0: [(2, 1, 6, "", (ip, port))]


class Cfg:
    model_normal, model_reason, model_light = "N", "R", "L"
    history_messages = 10


class FakeIg:
    def media(self, i):
        return {"id": i, "like_count": 7}

    def comments(self, i, n=8):
        return [{"text": "bravo"}]

    def insights(self, i):
        raise IgError("Instagram HTTP 400: (#10) Application does not have permission")


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.db = Db(self.d.name)

    def tearDown(self):
        self.db._c.close()
        self.d.cleanup()

    def test_sblocco_contenuto_solo_con_parole_del_proprietario(self):
        self.db.add_content("instagram", "da_classificare", "instagram_api", caption="Nuovo reel",
                            original_url="https://www.instagram.com/reel/AAA/", notes="instagram_id=111")
        t = Tools(self.db, FakeIg())
        r = "https://www.instagram.com/reel/AAA/"
        # senza frase: rifiutato
        self.assertIn("Errore", t.run("archivio_classifica", {"riferimento": r, "stato": "pubblicato"}))
        # frase inventata (non detta da Marco): rifiutato
        self.db.add_message("user", "ciao come va")
        self.assertIn("Errore", t.run("archivio_classifica", {"riferimento": r, "stato": "pubblicato", "frase_del_proprietario": "è musicale"}))
        self.assertEqual(self.db.content_summary(), {"da_classificare": 1})
        # frase vera: sbloccato e tracciato
        self.db.add_message("user", "Sì, quei due reel sono musicali!")
        out = t.run("archivio_classifica", {"riferimento": r, "stato": "pubblicato", "canzone": "End of Beginning",
                                            "frase_del_proprietario": "quei due reel sono musicali"})
        self.assertNotIn("Errore", out)
        self.assertEqual(self.db.content_summary(), {"pubblicato": 1})
        # rendere personale è sempre permesso, senza frase
        self.assertNotIn("Errore", t.run("archivio_classifica", {"riferimento": r, "stato": "personale_non_gestito"}))
        self.assertEqual(self.db.content_summary(), {"personale_non_gestito": 1})
        # e da personale a musicale serve di nuovo la conferma
        self.assertIn("Errore", t.run("archivio_classifica", {"riferimento": r, "stato": "pubblicato"}))

    def test_strumenti_di_lavoro_manager(self):
        t = Tools(self.db, FakeIg())
        self.assertIn("salvato", t.run("appunto_salva", {"tag": "lezione", "testo": "I reel di sera rendono di più (4/11 vs 6/11)"}))
        nid = json.loads(t.run("appunti_leggi", {"tag": "lezione"}))[0]["id"]
        t.run("appunto_aggiorna", {"id": nid, "stato": "archiviato"})
        self.assertEqual(t.run("appunti_leggi", {}), "Nessun appunto.")
        t.run("opportunita_salva", {"nome": "Contest X", "link_fonte": "https://x.it/bando", "scadenza": "2026-12-20"})
        oid = json.loads(t.run("opportunita_leggi", {}))[0]["id"]
        self.assertIn("Errore", t.run("opportunita_aggiorna", {"id": oid, "stato": "inviata"}))  # serve Marco
        self.assertEqual(t.run("opportunita_aggiorna", {"id": oid, "stato": "consigliata", "scadenza": "2026-12-22"}), "Opportunità aggiornata.")
        self.assertEqual(json.loads(t.run("opportunita_leggi", {"stato": "consigliata"}))[0]["scadenza"], "2026-12-22")
        self.assertIn("salvato", t.run("contatto_salva", {"nome": "Teatro Y", "link_fonte": "https://teatro.it", "tipo": "locale"}))
        self.assertEqual(t.run("contatto_salva", {"nome": "Teatro Y", "link_fonte": "https://teatro.it"}), "Già in archivio.")
        self.assertIn("Errore", t.run("contatto_aggiorna", {"id": 1, "stato": "contattato"}))
        self.assertIn("Errore", t.run("contatto_salva", {"nome": "Z", "link_fonte": "javascript:x"}))
        self.assertIn("ora italiana", t.run("data_ora", {}))

    def test_ped_fatti_bozze_e_monitor(self):
        class IgM(FakeIg):
            def discover(self, u, n=12):
                if u == "privato":
                    raise IgError("account non professionale")
                return {"followers_count": 1000, "media_count": 50,
                        "media": [{"mi_piace": 50, "commenti": 2}, {"mi_piace": 70, "commenti": 4}]}
        t = Tools(self.db, IgM())
        t.run("ped_salva", {"piano": "P", "voci": [{"data": "2026-11-20", "titolo": "Cover A"}]})
        pid = json.loads(t.run("ped_leggi", {}))[0]["id"]
        self.assertIn("aggiornata", t.run("ped_aggiorna", {"id": pid, "data": "2026-11-22", "stato": "rimandato", "motivo": "maltempo"}))
        self.assertEqual(json.loads(t.run("ped_leggi", {}))[0]["day"], "2026-11-22")
        self.assertIn("Errore", t.run("ped_aggiorna", {"id": pid, "stato": "pubblicato"}))
        self.assertIn("Errore", t.run("ped_aggiorna", {"id": pid, "data": "22/11"}))
        self.db.add_fact("Ha 30 anni")
        fid = json.loads(t.run("fatti_leggi", {}))[0]["id"]
        self.assertIn("Errore", t.run("fatto_elimina", {"id": fid, "frase_del_proprietario": "ho 31 anni"}))
        self.db.add_message("user", "no, ho 31 anni")
        self.assertIn("eliminato", t.run("fatto_elimina", {"id": fid, "frase_del_proprietario": "ho 31 anni"}))
        self.assertEqual(t.run("fatti_leggi", {}), "Nessun fatto salvato.")
        from app import approvals
        approvals.create(self.db, "idea_contenuto", "Idea", "Duetto con Marco")
        self.assertEqual(json.loads(t.run("bozze_leggi", {"stato": "in_attesa"}))[0]["testo"], "Duetto con Marco")
        # monitor
        self.assertIn("aggiunto", t.run("instagram_monitor_aggiungi", {"username": "@Artista.Simile", "nota": "simile"}))
        self.assertIn("Errore", t.run("instagram_monitor_aggiungi", {"username": "privato"}))
        self.assertIn("Errore", t.run("instagram_monitor_aggiungi", {"username": "no spazi!"}))
        conf = json.loads(t.run("instagram_monitor_confronta", {}))
        self.assertEqual(conf["confronto"][0]["media_mi_piace"], 60.0)
        self.assertEqual(conf["confronto"][0]["mi_piace_ogni_100_follower"], 6.0)
        self.assertEqual(json.loads(t.run("instagram_monitor_lista", {}))[0]["rilevamenti"][0]["follower"], 1000)
        self.assertEqual(t.run("instagram_monitor_rimuovi", {"username": "artista.simile"}), "Tolto dalla lista.")
        # senza Instagram collegato gli strumenti monitor non esistono
        self.assertEqual(Tools(self.db).run("instagram_monitor_lista", {}), "Strumento non disponibile.")

    def test_promemoria_contatti_e_followup(self):
        import datetime as dt
        from app.scheduler import apply_contact_action, run_contact_reminders

        class Tg:
            inviati = []

            def send(self, chat, text, silent=False, **k):
                Tg.inviati.append((text, k.get("reply_markup")))
        tg = Tg()
        t = Tools(self.db)
        oggi = dt.date(2026, 11, 12)
        for i in range(5):
            t.run("contatto_salva", {"nome": f"Locale {i}", "link_fonte": f"https://l{i}.it", "prima_scrittura": "2026-11-10",
                                     "priorita": 1 + i % 2, "canale": "dm_instagram", "handle": f"@l{i}"})
        t.run("contatto_salva", {"nome": "Futuro", "link_fonte": "https://f.it", "prima_scrittura": "2026-12-01"})
        t.run("contatto_salva", {"nome": "Senza data", "link_fonte": "https://s.it"})
        self.assertEqual(len(json.loads(t.run("contatti_da_fare", {}))), 5)
        notte = dt.datetime(2026, 11, 12, 7, 0)
        self.assertEqual(run_contact_reminders(self.db, tg, 7, notte), [])            # di notte non scrivo
        ids = run_contact_reminders(self.db, tg, 7, dt.datetime(2026, 11, 12, 10, 30))
        self.assertEqual(len(ids), 3)                                                  # massimo 3 al giorno
        self.assertEqual(run_contact_reminders(self.db, tg, 7, dt.datetime(2026, 11, 12, 15, 0)), [])  # una volta al giorno
        self.assertIn("ct:%d:ok" % ids[0], json.dumps(Tg.inviati[0][1]))
        self.assertIn("Primo messaggio", Tg.inviati[0][0])
        self.assertIn("PROMEMORIA CONTATTI", Agent(None, Cfg(), self.db, t).state_block())
        # bottoni: fatto -> in attesa e follow-up a 14 giorni; domani; escludi
        apply_contact_action(self.db, ids[0], "ok", oggi)
        c = self.db.contact_get(ids[0])
        self.assertEqual((c["stato"], c["prossima_azione_il"], c["messaggi_inviati"]), ("in_attesa_risposta", "2026-11-26", 1))
        apply_contact_action(self.db, ids[1], "d1", oggi)
        self.assertEqual(self.db.contact_get(ids[1])["prossima_azione_il"], "2026-11-13")
        apply_contact_action(self.db, ids[2], "no", oggi)
        self.assertEqual(self.db.contact_get(ids[2])["stato"], "escluso")
        # il giorno dopo: i due non toccati + quello rimandato; il follow-up compare solo il 26/11
        due = [c["id"] for c in self.db.contacts_due("2026-11-13")]
        self.assertNotIn(ids[0], due); self.assertNotIn(ids[2], due); self.assertIn(ids[1], due)
        self.assertIn(ids[0], [c["id"] for c in self.db.contacts_due("2026-11-26")])
        self.assertEqual(Tg.inviati[-1][0][:0], "")
        # il bot può registrare l'invio solo con parole vere di Marco
        quarto = self.db.contacts_list("Locale 3")[0]["id"]
        self.assertIn("Errore", t.run("contatto_registra_invio", {"id": quarto, "frase_del_proprietario": "ho scritto a Locale 3"}))
        self.db.add_message("user", "Ho scritto a Locale 3 ieri sera")
        self.assertIn("Follow-up fra 14", t.run("contatto_registra_invio", {"id": quarto, "frase_del_proprietario": "ho scritto a Locale 3"}))
        self.assertIn("Errore", t.run("contatto_salva", {"nome": "X", "link_fonte": "https://x.it", "prima_scrittura": "domani"}))

    def test_blocca_indirizzi_interni(self):
        for ip in ("127.0.0.1", "10.0.0.5", "172.18.0.2", "169.254.169.254", "192.168.1.1"):
            with self.assertRaises(ToolError):
                check_public_url("http://esempio.it/x", ris(ip))
        for url in ("file:///etc/passwd", "ftp://a.it", "http://u:p@a.it", ""):
            with self.assertRaises(ToolError):
                check_public_url(url, ris("93.184.216.34"))
        self.assertEqual(check_public_url("https://esempio.it/a", ris("93.184.216.34")), "https://esempio.it/a")

    def test_redirect_verso_rete_interna_bloccato(self):
        def opener(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 302, "x", {"Location": "http://interno/"}, io.BytesIO(b""))
        calls = []

        def resolver(host, port, proto=0):
            calls.append(host)
            return [(2, 1, 6, "", ("10.0.0.9" if host == "interno" else "93.184.216.34", port))]
        with self.assertRaises(ToolError):
            fetch_public("http://pubblico.it/", opener=opener, resolver=resolver)
        self.assertEqual(calls, ["pubblico.it", "interno"])

    def test_testo_senza_script(self):
        t = html_to_text("<html><head><title>Ciao</title></head><body><script>evil()</script><p>Concorso</p></body></html>")
        self.assertIn("Concorso", t)
        self.assertNotIn("evil", t)
        self.assertIn("Titolo: Ciao", t)

    def test_archivio_non_mostra_testo_personale(self):
        self.db.add_content("instagram", "personale_non_gestito", "instagram_api", caption="il mio segreto",
                            original_url="https://i/1", metrics_json=json.dumps({"likes": 3}))
        self.db.add_content("instagram", "pubblicato", "instagram_api", caption="cover Powerless", song="Powerless",
                            original_url="https://i/2", metrics_json=json.dumps({"likes": 60}))
        out = Tools(self.db).run("archivio_cerca", {"ordina_per_mi_piace": True})
        self.assertNotIn("segreto", out)
        self.assertIn("Powerless", out)
        self.assertLess(out.index("Powerless"), out.index("personale_non_gestito"))

    def test_instagram_post_riporta_blocco_statistiche(self):
        self.db.add_content("instagram", "pubblicato", "instagram_api", original_url="https://www.instagram.com/reel/AB/",
                            notes="instagram_id=555")
        t = Tools(self.db, FakeIg())
        out = json.loads(t.run("instagram_post", {"riferimento": "https://www.instagram.com/reel/AB"}))
        self.assertEqual(out["post"]["like_count"], 7)
        self.assertIn("permission", out["statistiche_errore"])
        self.assertIn("Non posso", t.run("instagram_post", {"riferimento": "https://www.instagram.com/reel/ZZ/"}))
        # contenuti personali / da classificare: bloccati anche in lettura
        self.db.add_content("instagram", "personale_non_gestito", "instagram_api", original_url="https://www.instagram.com/p/PRIV/",
                            notes="instagram_id=777")
        self.assertIn("Non posso", t.run("instagram_post", {"riferimento": "777"}))
        self.assertIn("Non posso", t.run("instagram_post", {"riferimento": "https://www.instagram.com/p/PRIV"}))

    def test_statistiche_reel_solo_musica(self):
        class Ig2(FakeIg):
            chiamati = []

            def insights(self, i):
                Ig2.chiamati.append(i)
                return {"data": [{"name": "views", "values": [{"value": 99}]}]}

            def account_insights(self, d=28):
                return {"giorni": d, "views": 5}
        self.db.add_content("instagram", "pubblicato", "instagram_api", original_url="https://i/m/", song="X",
                            notes="instagram_id=111", metrics_json=json.dumps({"likes": 4}))
        self.db.add_content("instagram", "personale_non_gestito", "instagram_api", original_url="https://i/p/",
                            notes="instagram_id=222")
        self.db.add_content("instagram", "da_classificare", "instagram_api", original_url="https://i/d/",
                            notes="instagram_id=333")
        t = Tools(self.db, Ig2())
        out = json.loads(t.run("instagram_statistiche_reel", {"quanti": 15}))
        self.assertEqual([o["views"] for o in out], [99])
        self.assertEqual(Ig2.chiamati, ["111"])  # personali e incerti mai interrogati
        self.assertEqual(json.loads(t.run("instagram_statistiche_account", {"giorni": 7}))["giorni"], 7)

    def test_strumenti_non_esposti_senza_collegamenti(self):
        nomi = [s["function"]["name"] for s in Tools(self.db).specs]
        self.assertNotIn("instagram_post", nomi)
        self.assertNotIn("web_browser", nomi)
        self.assertIn("web_leggi", nomi)
        self.assertEqual(Tools(self.db).run("web_browser", {"url": "http://a.it"}), "Strumento non disponibile.")

    def test_ciclo_strumenti_e_ripiego(self):
        class Ai1:
            n = 0

            def chat_tools(self, model, msgs, tools, max_tokens=1500):
                Ai1.n += 1
                if Ai1.n == 1:
                    return {"content": None, "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "archivio_riepilogo", "arguments": "{}"}}]}
                ruolo_tool = [m for m in msgs if m["role"] == "tool"]
                return {"content": "Hai " + ruolo_tool[0]["content"]}

            def chat(self, model, msgs, max_tokens=1200):
                return "semplice"
        self.db.add_content("instagram", "pubblicato", "instagram_api")
        a = Agent(Ai1(), Cfg, self.db, Tools(self.db))
        self.assertIn("pubblicato", a.reply("quanti contenuti?"))
        # stato reale nel prompt di sistema
        self.assertIn("pubblicato", a.state_block())

        class AiSenzaStrumenti(Ai1):
            def chat_tools(self, *a, **k):
                raise AiError("no tools")
        b = Agent(AiSenzaStrumenti(), Cfg, self.db, Tools(self.db))
        self.assertEqual(b.reply("ciao"), "semplice")

    def test_ricerca_web_e_profilo_pubblico(self):
        pagina = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fesempio.it%2Fbando&rut=x">Bando <b>2027</b></a>'
                  '<a class="result__snippet" href="x">Iscrizioni aperte</a>'
                  '<a class="result__a" href="/relativo">ignorato</a>')
        t = Tools(self.db, FakeIg(), fetch=lambda url, **k: pagina)
        r = json.loads(t.run("web_cerca", {"domanda": "bando musica"}))
        self.assertEqual(r[0]["link"], "https://esempio.it/bando")
        self.assertEqual(r[0]["titolo"], "Bando 2027")
        self.assertEqual(len(r), 1)

        class Ig3(FakeIg):
            def discover(self, u, n=12):
                return {"username": u}
        out = json.loads(Tools(self.db, Ig3()).run("instagram_profilo_pubblico", {"username": "@Artista"}))
        self.assertEqual(out["username"], "@Artista")

    def test_ricerca_omniroute(self):
        from app.tools import omniroute_search
        visti = []

        def apri(req, timeout=0):
            visti.append((req.full_url, req.get_header("Authorization")))
            return io.BytesIO(json.dumps({"results": [{"title": "Bando", "url": "https://e.it/b", "content": "iscrizioni"},
                                                      {"title": "senza link"}]}).encode())
        fn = omniroute_search("http://omniroute:20128/v1", "K", opener=apri)
        r = json.loads(Tools(self.db, search=fn).run("web_cerca", {"domanda": "bando"}))
        self.assertEqual(r, [{"titolo": "Bando", "link": "https://e.it/b", "anteprima": "iscrizioni"}])
        self.assertEqual(visti[0][0], "http://omniroute:20128/v1/search")

        def giu(req, timeout=0):
            raise OSError("x")
        with self.assertRaises(ToolError):
            omniroute_search("http://x/v1", "K", opener=giu)("q")

    def test_discover_rifiuta_nomi_strani(self):
        from app.instagram import Instagram
        with self.assertRaises(IgError):
            Instagram("t", "1", opener=lambda *a, **k: None).discover("a)}&access_token=x")

    def test_scheduler(self):
        import datetime as dt
        from app.scheduler import JOBS, is_due, period_key, run_due_jobs
        job = JOBS["report_settimanale"]  # lunedì 08:30
        lun = dt.datetime(2026, 11, 2, 8, 29)   # lunedì
        self.assertFalse(is_due(job, lun, ""))
        lun2 = dt.datetime(2026, 11, 2, 8, 30)
        self.assertTrue(is_due(job, lun2, ""))
        self.assertFalse(is_due(job, lun2, period_key(job, lun2)))      # già fatto
        mar = dt.datetime(2026, 11, 3, 7, 0)
        self.assertTrue(is_due(job, mar, ""))                            # recupero il giorno dopo
        self.assertFalse(is_due(job, mar, "2026-11-02"))

        class Ag:
            n = 0

            cfg = Cfg()

            def run_task(self, p, model=None, remember=True):
                Ag.n += 1
                if Ag.n == 1:
                    raise RuntimeError("giù")
                return "ok"

        class Tg:
            inviati = []

            def send(self, chat, text, silent=False):
                Tg.inviati.append((chat, text, silent))
        ven = dt.datetime(2026, 11, 6, 10, 0)  # venerdì: report (lun) e ricerca (mer) scaduti
        ag, tg = Ag(), Tg()
        self.assertEqual(run_due_jobs(self.db, ag, tg, 7, ven), ["ricerca_opportunita"])  # il primo fallisce
        self.assertEqual(run_due_jobs(self.db, ag, tg, 7, ven), ["report_settimanale"])
        self.assertEqual(run_due_jobs(self.db, ag, tg, 7, ven), [])                         # niente doppioni
        self.assertTrue(all(s for _, _, s in Tg.inviati))                                   # sempre in silenzio
        self.db.set("paused", "1")
        self.assertEqual(run_due_jobs(self.db, ag, tg, 7, dt.datetime(2026, 11, 9, 9, 0)), [])  # pausa

    def test_agenda_domande_promemoria_e_rinnovo(self):
        import datetime as dt
        from app.scheduler import run_agenda, run_due_jobs, run_due_tasks, ped_in_scadenza
        from app import approvals

        class Tg:
            inviati = []

            def send(self, chat, text, silent=False, **k):
                Tg.inviati.append((text, silent))
        tg = Tg()
        from unittest import mock

        def ra(now):  # il tempo 'reale' del test segue la data simulata: il test non dipende dal giorno in cui gira
            with mock.patch("time.time", return_value=now.timestamp()):
                return run_agenda(self.db, tg, 7, now)
        t = Tools(self.db)
        # domande: dedupe, coda massima, invio solo di giorno, una al giorno
        self.assertIn("in coda", t.run("chiedi_al_proprietario", {"domanda": "Come si chiama l'inedito?", "perche": "dietro le quinte"}))
        self.assertIn("Non messa", t.run("chiedi_al_proprietario", {"domanda": "come si chiama l'inedito?", "perche": "x"}))
        t.run("chiedi_al_proprietario", {"domanda": "Che esercizi fai?", "perche": "carosello"})
        notte = dt.datetime(2026, 11, 3, 7, 0)
        self.assertEqual(ra(notte), [])                       # di notte non scrivo
        g = dt.datetime(2026, 11, 3, 11, 0)
        self.assertEqual(ra(g), ["domanda"])
        self.assertEqual(ra(g.replace(hour=12)), [])          # finché non risponde, niente altre domande
        q = self.db.question_get("posta")
        self.assertIn("domanda aperta", Agent(None, Cfg(), self.db, t).state_block().lower())
        self.assertIn("Domanda chiusa", t.run("domanda_chiudi", {"id": q["id"], "risposta": "si chiama X"}))
        t.run("fatto_salva", {"testo": "L'inedito si chiama X"})
        self.assertIn("L'inedito si chiama X", self.db.facts_list())
        self.assertEqual(ra(g.replace(hour=13)), [])          # pausa di 20 ore tra due domande
        self.assertEqual(ra(g + dt.timedelta(days=1)), ["domanda"])
        # sollecito unico dopo 36 ore, poi scadenza a 7 giorni
        self.assertEqual(ra(g + dt.timedelta(days=3)), ["sollecito"])
        self.assertEqual(ra(g + dt.timedelta(days=3, hours=1)), [])
        ra(g + dt.timedelta(days=9))
        self.assertIsNone(self.db.question_get("posta"))
        # attività future: solo date future
        self.assertIn("Errore", t.run("programma_attivita", {"quando": "2020-01-01", "istruzione": "x"}))
        fut = (dt.datetime.now() + dt.timedelta(days=2)).strftime("%Y-%m-%d")
        self.assertIn("programmata", t.run("programma_attivita", {"quando": fut, "istruzione": "ricontrolla i concorsi"}))

        class Ag:
            cfg = Cfg()
            visti = []

            def run_task(self, p, model=None, remember=True):
                Ag.visti.append((p, model, remember))
                return "fatto"
        tg.inviati.clear()
        dopo = dt.datetime.now() + dt.timedelta(days=3)
        self.assertEqual(len(run_due_tasks(self.db, Ag(), tg, 7, dopo)), 1)
        self.assertEqual(run_due_tasks(self.db, Ag(), tg, 7, dopo), [])               # una volta sola
        # promemoria serale e voci passate
        dom = dt.date(2026, 11, 4)
        self.db.ped_replace("PED 2026-11", [{"day": dom.isoformat(), "title": "Cover Numb", "song": "Numb", "artist": "Linkin Park"},
                                           {"day": "2026-11-10", "title": "Altro"}])
        aid = approvals.create(self.db, "idea_contenuto", "Piano 30 giorni", "testo")
        approvals.decide(self.db, aid, "ok")                                          # approvo: il calendario si aggiorna da solo
        self.assertEqual({r["status"] for r in self.db.ped_list()}, {"approvato"})
        self.assertEqual(run_agenda(self.db, tg, 7, dt.datetime(2026, 11, 3, 18, 30)), ["promemoria"])
        self.assertIn("Cover Numb", tg.inviati[-1][0])
        run_agenda(self.db, tg, 7, dt.datetime(2026, 11, 5, 9, 0))
        self.assertEqual(self.db.ped_list(None, "2026-11-04", "2026-11-04")[0]["status"], "trascorso")
        # rinnovo piano: solo se il piano esiste, finisce entro 7 giorni e non c'è già una proposta
        self.assertTrue(ped_in_scadenza(self.db, dt.datetime(2026, 11, 6, 10, 0)))
        self.assertFalse(ped_in_scadenza(self.db, dt.datetime(2026, 10, 1, 10, 0)))
        a2 = approvals.create(self.db, "idea_contenuto", "Piano 30 giorni", "altro")
        self.assertFalse(ped_in_scadenza(self.db, dt.datetime(2026, 11, 6, 10, 0)))
        approvals.decide(self.db, a2, "no")
        Ag.visti.clear()
        self.assertEqual(run_due_jobs(self.db, Ag(), tg, 7, dt.datetime(2026, 11, 6, 10, 5)),
                         ["report_settimanale", "ricerca_opportunita", "rinnovo_ped"])
        p, model, rem = [v for v in Ag.visti if v[1] == "R"][0]
        self.assertIn("2026-11-11", p)                                                # riparte dal giorno dopo l'ultimo
        # revisione interna: non entra nella chat
        Ag.visti.clear()
        run_due_jobs(self.db, Ag(), tg, 7, dt.datetime(2026, 11, 6, 17, 5))
        self.assertTrue(any(not r for _, _, r in Ag.visti))

    def test_markdown_telegram(self):
        from app.fmt import md_to_html
        t = md_to_html("# Titolo\n**grassetto** e *corsivo* e `codice` <b>x</b> a_b_c\n- uno\n* due\n"
                       "| A | B |\n|---|---|\n| x | 1 |\n\n| Nome molto lungo qui | Altra colonna lunga | Terza colonna lunga |\n|---|---|---|\n| a | b | c |\n"
                       "[sito](https://e.it/x?a=1&b=2)\n```\nprint(1<2)\n```")
        self.assertIn("<b>Titolo</b>", t)
        self.assertIn("<b>grassetto</b> e <i>corsivo</i> e <code>codice</code>", t)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", t)      # HTML del testo neutralizzato
        self.assertIn("a_b_c", t)                      # underscore dentro parole intatti
        self.assertIn("• uno", t)
        self.assertIn("• due", t)
        self.assertIn("<pre>A | B", t)                 # tabella stretta: a larghezza fissa
        self.assertIn("• <b>a</b>", t)                 # tabella larga: righe
        self.assertIn('<a href="https://e.it/x?a=1&amp;b=2">sito</a>', t)
        self.assertIn("print(1&lt;2)", t)
        self.assertNotIn("```", t)

    def test_invio_ripiega_su_testo_semplice(self):
        from app.tg import Tg, TgError
        chiamate = []

        class T2(Tg):
            def call(self, method, timeout=40, **p):
                chiamate.append(p)
                if p.get("parse_mode") == "HTML":
                    raise TgError("Telegram HTTP 400 su sendMessage")
                return {}
        T2("tok").send(1, "**ciao**")
        self.assertEqual(chiamate[0]["parse_mode"], "HTML")
        self.assertEqual(chiamate[1]["text"], "**ciao**")
        self.assertNotIn("parse_mode", chiamate[1])

    def test_risposta_troncata_viene_continuata(self):
        class Ai4:
            n = 0

            def chat_tools(self, model, msgs, tools, max_tokens=3000):
                Ai4.n += 1
                if Ai4.n == 1:
                    return {"content": "Prima parte", "_finish": "length"}
                return {"content": "seconda parte.", "_finish": "stop"}
        out = Agent(Ai4(), Cfg, self.db, Tools(self.db)).reply("ciao")
        self.assertEqual(out, "Prima parte seconda parte.")

    def test_grafici(self):
        import xml.dom.minidom as md
        from app.charts import ChartError, fmt, render_svg
        base = {"titolo": "Reel <b>& co</b>", "etichette": ["Somewhere I Belong", "Blackbird", "È delicato"],
                "serie": [{"nome": "Visualizzazioni", "valori": [605, 203, 326]}]}
        for tipo in ("barre", "barre_orizzontali", "linea"):
            svg = render_svg({**base, "tipo": tipo})
            md.parseString(svg)                       # SVG ben formato
            self.assertIn("Reel &lt;b&gt;&amp; co", svg)  # testo neutralizzato
            self.assertNotIn("<b>", svg)
        multi = render_svg({"tipo": "linea", "titolo": "t", "etichette": ["a", "b"],
                            "serie": [{"nome": "x", "valori": [1, 2]}, {"nome": "y", "valori": [3, 4]}]})
        md.parseString(multi)
        self.assertEqual(fmt(12101), "12.101")
        self.assertEqual(fmt(0.65), "0,65")
        for brutto in ({"tipo": "torta", "etichette": ["a"], "serie": [{"valori": [1]}]},
                       {"tipo": "barre", "etichette": ["a", "b"], "serie": [{"valori": [1]}]},
                       {"tipo": "barre", "etichette": ["a"], "serie": [{"valori": ["x"]}]},
                       {"tipo": "barre", "etichette": ["a"], "serie": [{"valori": [-1]}]},
                       {"tipo": "barre", "etichette": [], "serie": []}):
            with self.assertRaises(ChartError):
                render_svg(brutto)

    def test_strumento_grafico(self):
        visti = []
        t = Tools(self.db, browser_url="http://b:3000", browser_token="T",
                  to_png=lambda svg, u, k: visti.append(svg) or b"\x89PNGfinto")
        out = t.run("grafico", {"tipo": "barre", "titolo": "Prova", "etichette": ["a", "b"],
                                "serie": [{"nome": "n", "valori": [1, 2]}]})
        self.assertIn("Grafico creato", out)
        imgs = t.take_images()
        self.assertEqual(len(imgs), 1)
        self.assertEqual(t.take_images(), [])
        self.assertTrue(t.run("grafico", {"tipo": "barre", "titolo": "x", "etichette": ["a"],
                                          "serie": [{"valori": ["no"]}]}).startswith("Errore nei dati"))
        self.assertNotIn("grafico", [s["function"]["name"] for s in Tools(self.db).specs])  # senza browser non c'è

    def test_importazione_account(self):
        import datetime as dt
        from app import analytics as an
        from app.import_account import Importer

        class IgF:
            user_id, base = "1", "http://b"
            visti = []

            def get(self, path):
                IgF.visti.append(path)
                if path.startswith("1/insights?metric=reach&period=day&since"):
                    if len(IgF.visti) > 4:
                        return {"data": [{"values": []}]}
                    return {"data": [{"values": [{"value": 10, "end_time": "2026-11-02T08:00:00+0000"},
                                                 {"value": 20, "end_time": "2026-11-03T08:00:00+0000"}]}]}
                if "follower_count" in path:
                    return {"data": [{"values": [{"value": 2, "end_time": "2026-11-02T08:00:00+0000"}]}]}
                if "breakdown=" in path and "follower_demographics" in path:
                    return {"data": [{"total_value": {"breakdowns": [{"results": [
                        {"dimension_values": ["25-34"], "value": 30}, {"dimension_values": ["18-24"], "value": 10}]}]}}]}
                if "/insights?metric=" in path and "total_value" in path:
                    return {"data": [{"total_value": {"value": 7}}]}
                if path.startswith("999/insights"):
                    if "ig_reels" in path:
                        from app.instagram import IgError
                        raise IgError("Instagram HTTP 400: metrica non supportata")
                    return {"data": [{"name": "reach", "values": [{"value": 5}]}, {"name": "views", "values": [{"value": 9}]}]}
                if "/insights?metric=" in path:
                    return {"data": [{"name": "reach", "values": [{"value": 100}]}, {"name": "views", "values": [{"value": 300}]},
                                     {"name": "ig_reels_avg_watch_time", "values": [{"value": 4000}]}]}
                if "/comments" in path:
                    return {"data": [{"id": "c1", "text": "bravo", "timestamp": "2026-11-01T10:00:00+0000", "like_count": 2}]}
                if "/stories" in path:
                    return {"data": []}
                if "username" in path:
                    return {"id": "1", "username": "x", "followers_count": 5}
                return {"data": []}

            def _get(self, url):
                return {"data": [{"id": "t1", "caption": "tag", "timestamp": "2026-10-01T10:00:00+0000", "permalink": "https://i/t"}]}

        self.db.add_content("instagram", "pubblicato", "instagram_api", song="A", original_artist="Art", media_type="REELS",
                            original_url="https://i/1", published_at="2026-10-30T18:00:00+0000", notes="instagram_id=111",
                            metrics_json=json.dumps({"comments": 1}))
        self.db.add_content("instagram", "pubblicato", "instagram_api", song="B", media_type="IMAGE",
                            original_url="https://i/9", published_at="2026-10-20T08:00:00+0000", notes="instagram_id=999")
        self.db.add_content("instagram", "personale_non_gestito", "instagram_api", original_url="https://i/2",
                            notes="instagram_id=222", metrics_json=json.dumps({"comments": 5}))
        self.db.add_content("instagram", "da_classificare", "instagram_api", original_url="https://i/3", notes="instagram_id=333")
        res = Importer(self.db, IgF(), pause=0).run(rapido=True)
        self.assertEqual(res["importati"]["contenuti_con_statistiche"], 2)
        self.assertEqual(res["importati"]["commenti"], 1)
        self.assertEqual(res["importati"]["tag"], 1)
        self.assertTrue(res["importati"]["totali_settimanali"] > 10)
        # PRIVACY: mai chiamate per contenuti personali o da classificare
        self.assertFalse([p for p in IgF.visti if p.startswith(("222/", "333/"))])
        # reel: ripiego automatico sul set base quando le metriche reel non sono ammesse
        self.assertTrue(any(p.startswith("999/insights") and "ig_reels" not in p for p in IgF.visti))
        # nessun nome di persona salvato nei commenti
        self.assertEqual([r[0] for r in self.db._x("SELECT name FROM pragma_table_info('ig_comments')").fetchall()],
                         ["comment_id", "content_id", "ts", "text", "likes"])
        # seconda corsa: niente richiami inutili per chi ha già un'istantanea di oggi
        IgF.visti.clear()
        Importer(self.db, IgF(), pause=0).run(rapido=True)
        self.assertFalse([p for p in IgF.visti if p.startswith(("111/insights", "999/insights"))])
        # letture
        self.assertEqual(an.series(self.db, "reach", 30)["dati"][0]["valore"], 10)
        self.assertEqual(an.audience(self.db)["age"]["voci"][0], {"valore": "25-34", "follower": 30, "percento": 75.0})
        self.assertEqual(an.ranking(self.db, "views", 5)["dati"][0]["canzone"], "A")
        self.assertEqual(an.ranking(self.db, "views", 5)["contenuti_con_dati"], 2)
        self.assertEqual(an.weeks(self.db, "views", 3)["dati"][0]["valore"], 7)
        self.assertIn("errore", an.ranking(self.db, "drop table"))
        bt = an.best_times(self.db)
        self.assertEqual(bt["contenuti_analizzati"], 2)
        self.assertFalse(bt["per_giorno"][0]["attendibile"])  # campione troppo piccolo: dichiarato
        t = Tools(self.db)
        self.assertIn("ultimo_import", t.run("storico_account", {"cosa": "riepilogo"}))
        self.assertIn("Voce non valida", t.run("storico_account", {"cosa": "boh"}))
        self.assertIn("storico_account", [s["function"]["name"] for s in t.specs])

    def test_blocco_e_approvazioni(self):
        from app import approvals
        from app.guard import Blocked, require_manageable
        from app.main import handle_callback
        self.db.add_content("instagram", "pubblicato", "instagram_api", original_url="https://www.instagram.com/reel/OK/", notes="instagram_id=1")
        self.db.add_content("instagram", "personale_non_gestito", "instagram_api", original_url="https://www.instagram.com/p/P/", notes="instagram_id=2")
        self.db.add_content("instagram", "da_classificare", "instagram_api", original_url="https://www.instagram.com/p/D/", notes="instagram_id=3")
        self.assertTrue(require_manageable(self.db, "https://www.instagram.com/reel/OK"))
        for ref in ("2", "3", "https://www.instagram.com/p/P/", "https://www.instagram.com/p/D", "999", ""):
            with self.assertRaises(Blocked):
                require_manageable(self.db, ref)
        t = Tools(self.db)
        # risposta a un commento su contenuto personale: rifiutata prima ancora di arrivare a Marco
        self.assertIn("non lo tocco", t.run("proponi_bozza", {"tipo": "bozza_risposta_commento", "titolo": "x", "testo": "grazie",
                                                               "link_contenuto": "https://www.instagram.com/p/P/"}))
        self.assertIn("Errore", t.run("proponi_bozza", {"tipo": "bozza_risposta_commento", "titolo": "x", "testo": "grazie"}))
        self.assertEqual(t.proposals, [])
        out = t.run("proponi_bozza", {"tipo": "bozza_post", "titolo": "Idea", "testo": "Nuova cover!"})
        self.assertIn("Bozza #", out)
        aid = t.take_proposals()[0]
        self.assertEqual(self.db._x("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0], "in_attesa")
        self.assertIn("Approva", str(approvals.keyboard(aid)))

        class Cfgx:
            allowed_user_id = 42

        class TgF:
            chiamate, inviati = [], []

            def call(self, m, **p):
                TgF.chiamate.append((m, p))

            def send(self, chat, text, **k):
                TgF.inviati.append(text)
        cq = {"id": "q", "from": {"id": 42}, "data": f"ap:{aid}:ok", "message": {"chat": {"id": 42}, "message_id": 5}}
        handle_callback(TgF(), self.db, Cfgx, cq)
        self.assertEqual(self.db._x("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0], "approvata")
        self.assertIn("Non l'ho pubblicata", TgF.inviati[-1])
        handle_callback(TgF(), self.db, Cfgx, cq)                       # seconda pressione: non cambia nulla
        self.assertIn("già", TgF.inviati[-1])
        n = len(TgF.chiamate)
        handle_callback(TgF(), self.db, Cfgx, {**cq, "from": {"id": 7}})  # estraneo: ignorato in silenzio
        self.assertEqual(len(TgF.chiamate), n)
        self.assertEqual(self.db._x("SELECT status FROM approvals WHERE id=?", (aid,)).fetchone()[0], "approvata")
        handle_callback(TgF(), self.db, Cfgx, {**cq, "data": "ap:abc:ok"})  # dati strani: nessun danno

    def test_lavori_lunghi_hanno_piu_passaggi(self):
        class AiL:
            n = 0

            def chat_tools(self, model, msgs, tools, max_tokens=3000):
                AiL.n += 1
                if AiL.n <= 10:  # 10 giri di strumenti: oltre il limite normale (6)
                    return {"content": None, "tool_calls": [{"id": f"c{AiL.n}", "type": "function",
                            "function": {"name": "archivio_riepilogo", "arguments": "{}"}}]}
                return {"content": "finito"}

            def chat(self, model, msgs, max_tokens=1200):
                return "forzato"
        a = Agent(AiL(), Cfg, self.db, Tools(self.db))
        self.assertEqual(a.run_task("lavoro lungo"), "finito")
        AiL.n = 0
        self.assertEqual(Agent(AiL(), Cfg, self.db, Tools(self.db)).reply("chat normale"), "forzato")  # limite 6 in chat

    def test_ped_e_fatti(self):
        import datetime as dt
        from app.main import handle_command
        from app.scheduler import ped_prompt
        self.assertIn("vuoto", handle_command("/calendario", self.db))
        t = Tools(self.db)
        oggi = dt.date.today()
        v = [{"data": (oggi + dt.timedelta(days=1)).isoformat(), "formato": "reel", "tipo": "cover", "titolo": "Cover X",
              "canzone": "Numb", "artista": "Linkin Park", "motivazione": "dati"},
             {"data": (oggi + dt.timedelta(days=3)).isoformat(), "formato": "post", "titolo": "Presentazione"}]
        self.assertIn("Salvate 2", t.run("ped_salva", {"piano": "PED test", "voci": v}))
        self.assertIn("Salvate 1", t.run("ped_salva", {"piano": "PED test", "voci": v[:1]}))  # sostituisce le proposte
        self.assertEqual(len(self.db.ped_list("PED test")), 1)
        self.assertIn("Errore", t.run("ped_salva", {"piano": "x", "voci": [{"data": "domani", "titolo": "y"}]}))
        t.run("ped_salva", {"piano": "PED test", "aggiungi": True, "voci": [v[1]]})   # settimana successiva: si aggiunge
        self.assertEqual(len(self.db.ped_list("PED test")), 2)
        self.assertIn("troppo lunghi", t.run("ped_salva", '{"piano": "x", "voci": [{"data": "2026-11-0'))  # JSON tagliato
        cal = handle_command("/calendario", self.db)
        self.assertIn("Cover X", cal)
        self.assertIn("Numb - Linkin Park", cal)
        self.assertIn("Cover X", t.run("ped_leggi", {}))
        # fatti dichiarati: senza doppioni, e finiscono nel contesto del manager
        self.db.add_fact("Marco ha 30 anni")
        self.db.add_fact("Marco ha 30 anni")
        self.assertEqual(self.db.facts_list(), ["Marco ha 30 anni"])
        self.assertIn("Marco ha 30 anni", Agent(None, Cfg, self.db, t).state_block())
        p = ped_prompt(oggi)
        self.assertIn((oggi + dt.timedelta(days=30)).isoformat(), p)
        self.assertIn("ped_salva", p)

    def test_import_giornaliero_dovuto(self):
        import datetime as dt
        from app.main import import_is_due
        self.assertTrue(import_is_due(self.db))
        self.db.set("import:ultimo", dt.datetime.now().isoformat(timespec="seconds"))
        self.assertFalse(import_is_due(self.db))
        self.assertTrue(import_is_due(self.db, dt.datetime.now() + dt.timedelta(hours=23)))

    def test_opportunita_salva(self):
        t = Tools(self.db)
        t.run("opportunita_salva", {"nome": "Contest X", "link_fonte": "https://x.it/b", "scadenza": "2027-05-05"})
        self.assertEqual(self.db.opportunities_summary(), {"da_valutare": 1})
        self.assertIn("Già", t.run("opportunita_salva", {"nome": "X", "link_fonte": "https://x.it/b"}))
        self.assertTrue(t.run("opportunita_salva", {"nome": "Y", "link_fonte": "nonunlink"}).startswith("Errore"))

    def test_strumento_sconosciuto_o_args_rotti(self):
        t = Tools(self.db)
        self.assertEqual(t.run("rm_rf", {}), "Strumento non disponibile.")
        self.assertTrue(t.run("archivio_cerca", "{non json").startswith("Errore"))


if __name__ == "__main__":
    unittest.main()
