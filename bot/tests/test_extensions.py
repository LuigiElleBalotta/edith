import copy
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import approvals, extensions as ext, profile as prof  # noqa: E402
from app.db import Db  # noqa: E402
from app.tools import Tools  # noqa: E402

CAT = os.path.join(os.path.dirname(__file__), "..", "catalogo")


def cat(name):
    with open(os.path.join(CAT, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


class FakeTg:
    def __init__(self):
        self.sent = []

    def send(self, chat, text, silent=False, reply_markup=None):
        self.sent.append((chat, text))


def public(host, port, proto=0):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Db(os.path.join(self.tmp.name, "data", "acc"))
        self.db.slug = "acc"
        self.db.ext_root = os.path.join(self.tmp.name, "ext")
        self.store = ext.store_for(self.db)
        self.fetches = []

        def fetch(url, domini, headers=None):
            self.fetches.append((url, headers))
            return "application/json", json.dumps({"daily": {"temperature_2m_max": [21.5], "precipitation_sum": [0.2]}})
        self.rt = ext.Runtime(self.store, self.db, ask=lambda i, d="": "RISPOSTA", secrets=lambda e, k: "SEGRETO" if k == "chiave" else "", fetch=fetch)
        self.tools = Tools(self.db, ext=self.rt)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def install(self, name):
        m = cat(name)
        self.store.propose(m)
        self.store.approve(m["id"])
        return m


class ValidatorTests(Base):
    def test_i_tre_esempi_del_catalogo_sono_validi(self):
        for n in ("ricettario", "timer_cottura", "meteo"):
            ext.validate_manifest(cat(n))

    def bad(self, mutate, frag):
        m = copy.deepcopy(cat("meteo"))
        mutate(m)
        with self.assertRaises(ext.ExtError) as cm:
            ext.validate_manifest(m)
        self.assertIn(frag, str(cm.exception))

    def test_manifest_sbagliati_si_rifiutano_con_frase_chiara(self):
        self.bad(lambda m: m.update(roba=1), "sconosciute")
        self.bad(lambda m: m.update(id="Meteo!"), "id")
        self.bad(lambda m: m["domini"].clear(), "domini")
        self.bad(lambda m: m.update(effetti=[]), "effetti")
        self.bad(lambda m: m["strumenti"][0]["passi"][0].update(url="http://api.open-meteo.com/x"), "https://")
        self.bad(lambda m: m["strumenti"][0]["passi"][0].update(url="https://{citta_lat}.open-meteo.com/x"), "senza variabili")
        self.bad(lambda m: m["strumenti"][0]["passi"][0].update(url="https://evil.example.org/x"), "domini")
        self.bad(lambda m: m["strumenti"][0]["passi"][0].update(url="https://api.open-meteo.com/{boh}"), "{boh}")
        self.bad(lambda m: m["strumenti"][0]["passi"][0].update(intestazioni={"X-Key": "{segreto:chiave}"}), "segreto")
        self.bad(lambda m: m["strumenti"][0]["passi"].append({"tipo": "post_esterno", "url": "x"}), "passo non valido")
        self.bad(lambda m: m["strumenti"][0]["passi"][0].update(metodo="POST"), "sconosciute")
        self.bad(lambda m: m["strumenti"][0].update(parametri=[{"chiave": "x", "tipo": "testo"}]) or m["programma"].update(strumento="meteo_oggi"), "parametri")
        self.bad(lambda m: m["programma"].update(ora="9"), "ora")

    def test_effetti_devono_comprendere_quelli_usati(self):
        m = cat("timer_cottura")
        m["effetti"] = []
        with self.assertRaises(ext.ExtError):
            ext.validate_manifest(m)

    def test_riassunto_mostra_siti_e_limiti(self):
        r = ext.riassunto(cat("meteo"))
        self.assertIn("api.open-meteo.com", r)
        self.assertIn("NON può", r)

    def test_riassunto_evidenzia_cosa_cambia(self):
        nuovo = cat("meteo")
        nuovo["domini"].append("altro.example.org")
        nuovo["strumenti"][0]["passi"].append({"tipo": "leggi_pagina", "url": "https://altro.example.org/x"})
        r = ext.riassunto(nuovo, cat("meteo"))
        self.assertIn("Nuovi siti: altro.example.org", r)

    def test_catalogo_ha_indice_aggiornato(self):
        voci = ext.catalog_list()
        self.assertEqual({v["id"] for v in voci}, {"ricettario", "timer_cottura", "meteo"})
        self.assertTrue(all(v["verificata"] for v in voci), "lancia: python scripts/aggiorna_catalogo.py")


class StoreTests(Base):
    def test_proposta_non_e_attiva_finche_non_approvata(self):
        m = cat("ricettario")
        self.store.propose(m)
        self.assertIsNone(self.store.manifest("ricettario"))
        self.assertEqual(self.rt.specs(), [])
        self.assertEqual(self.store.approve("ricettario"), 1)
        self.assertTrue(self.store.state("ricettario")["attiva"])
        self.assertIsNone(self.store.pending("ricettario"))
        self.assertEqual(len(self.rt.specs()), 3)

    def test_approvare_senza_proposta_non_si_puo(self):
        with self.assertRaises(ext.ExtError):
            self.store.approve("meteo")

    def test_versioni_e_ritorno_indietro_e_spegni(self):
        self.install("meteo")
        m2 = cat("meteo")
        m2["nome"] = "Meteo 2"
        self.store.propose(m2)
        self.assertEqual(self.store.approve("meteo"), 2)
        self.assertEqual(self.store.manifest("meteo")["nome"], "Meteo 2")
        self.assertEqual(self.store.rollback("meteo"), 1)
        self.assertEqual(self.store.manifest("meteo")["nome"], "Meteo")
        with self.assertRaises(ext.ExtError):
            self.store.rollback("meteo")
        self.store.set_active("meteo", False)
        self.assertEqual(self.rt.specs(), [])

    def test_percorsi_ostili_non_passano(self):
        for bad in ("../x", "a/b", "", "X", "a" * 40):
            with self.assertRaises(ext.ExtError):
                self.store.manifest(bad)
        with self.assertRaises(ext.ExtError):
            ext.ExtStore(self.db.ext_root, "../fuori")

    def test_le_estensioni_stanno_fuori_dal_database_e_sono_per_account(self):
        self.install("ricettario")
        self.assertTrue(os.path.exists(os.path.join(self.db.ext_root, "acc", "ricettario", "dati.sqlite")))
        altro = ext.ExtStore(self.db.ext_root, "altro")
        self.assertEqual(altro.ids(), [])

    def test_righe_crud_e_tipi(self):
        self.install("ricettario")
        rid = self.store.row_add("ricettario", "ricette", {"titolo": "Carbonara", "ingredienti": "uova\nguanciale", "porzioni": "2,5"})
        r = self.store.row_get("ricettario", "ricette", rid)
        self.assertEqual((r["titolo"], r["ingredienti"], r["porzioni"]), ("Carbonara", ["uova", "guanciale"], 2.5))
        self.assertTrue(self.store.row_update("ricettario", "ricette", rid, {"ingredienti": "uova\nguanciale\npepe"}))
        self.assertEqual(self.store.row_get("ricettario", "ricette", rid)["titolo"], "Carbonara")  # il resto non cambia
        rows, tot = self.store.rows("ricettario", "ricette", search="pepe")
        self.assertEqual((len(rows), tot), (1, 1))
        with self.assertRaises(ext.ExtError):
            self.store.row_add("ricettario", "ricette", {"porzioni": "tante", "titolo": "x"})
        with self.assertRaises(ext.ExtError):
            self.store.row_add("ricettario", "ricette", {})  # titolo obbligatorio
        with self.assertRaises(ext.ExtError):
            self.store.row_update("ricettario", "ricette", rid, {"titolo": ""})
        self.assertTrue(self.store.row_delete("ricettario", "ricette", rid))
        self.assertIsNone(self.store.row_get("ricettario", "ricette", rid))

    def test_impostazioni_i_segreti_non_si_salvano_nel_database(self):
        m = cat("meteo")
        m["impostazioni"].append({"chiave": "chiave", "tipo": "segreto", "etichetta": "Chiave"})
        self.store.propose(m)
        self.store.approve("meteo")
        sec = self.store.save_settings("meteo", {"citta_lat": "45,5", "citta_lon": "9.2", "chiave": "abc123"})
        self.assertEqual(sec, {"EXT_METEO_CHIAVE": "abc123"})
        self.assertEqual(self.store.settings("meteo"), {"citta_lat": 45.5, "citta_lon": 9.2})
        with open(os.path.join(self.db.ext_root, "acc", "meteo", "dati.sqlite"), "rb") as f:
            self.assertNotIn(b"abc123", f.read())
        with self.assertRaises(ext.ExtError):
            self.store.save_settings("meteo", {"citta_lat": "nord"})


class RuntimeTests(Base):
    def test_ricettario_salva_cerca_aggiorna(self):
        self.install("ricettario")
        names = {s["function"]["name"] for s in self.tools.specs}
        self.assertIn("x_ricettario_ricetta_salva", names)
        self.assertIn("Salvato", self.tools.run("x_ricettario_ricetta_salva", {"titolo": "Tiramisù", "ingredienti": ["mascarpone", "caffè"]}))
        self.assertIn("Tiramisù", self.tools.run("x_ricettario_ricetta_cerca", {"testo": "mascarpone"}))
        self.assertEqual(self.tools.run("x_ricettario_ricetta_cerca", {"testo": "pizza"}), "(nessun risultato)")
        rows, _ = self.store.rows("ricettario", "ricette")
        self.assertIn("aggiornata", self.tools.run("x_ricettario_ricetta_aggiorna", {"id": rows[0]["id"], "porzioni": 6}))
        self.assertEqual(self.store.row_get("ricettario", "ricette", rows[0]["id"])["porzioni"], 6)
        self.assertTrue(self.tools.run("x_ricettario_ricetta_salva", {}).startswith("Errore"))  # titolo obbligatorio

    def test_timer_scatta_solo_quando_scade_e_una_volta(self):
        self.install("timer_cottura")
        out = self.tools.run("x_timer_cottura_timer_avvia", {"minuti": 9, "cosa": "Scola la pasta"})
        self.assertIn("Timer #1", out)
        tg = FakeTg()
        self.assertEqual(ext.run_timers(self.db, tg, 77, now=time.time() + 60), [])
        self.assertEqual(ext.run_timers(self.db, tg, 77, now=time.time() + 10 * 60), [1])
        self.assertEqual(tg.sent, [(77, "⏰ Scola la pasta: tempo scaduto")])
        self.assertEqual(ext.run_timers(self.db, tg, 77, now=time.time() + 3600), [])  # già fatto
        self.assertTrue(self.tools.run("x_timer_cottura_timer_avvia", {"minuti": -5, "cosa": "x"}).startswith("Errore"))

    def test_timer_non_riesce_a_inviare_si_riprova_poi_si_ferma(self):
        self.install("timer_cottura")
        self.tools.run("x_timer_cottura_timer_avvia", {"minuti": 1, "cosa": "x"})

        class Rotto:
            def send(self, *a, **k):
                raise OSError("rete")
        for _ in range(7):
            ext.run_timers(self.db, Rotto(), 1, now=time.time() + 600)
        self.assertEqual(self.db._x("SELECT status FROM ext_timers").fetchone()[0], "fallito")

    def test_meteo_estrae_e_usa_solo_il_dominio_dichiarato(self):
        self.install("meteo")
        out = self.tools.run("x_meteo_meteo_oggi", {})
        self.assertIn("daily.temperature_2m_max.0: 21.5", out)
        self.assertIn("latitude=41.9", self.fetches[0][0])

    def test_segreto_va_solo_nelle_intestazioni(self):
        m = cat("meteo")
        m["impostazioni"].append({"chiave": "chiave", "tipo": "segreto"})
        m["strumenti"][0]["passi"][0]["intestazioni"] = {"X-Api-Key": "{segreto:chiave}"}
        self.store.propose(m)
        self.store.approve("meteo")
        self.tools.run("x_meteo_meteo_oggi", {})
        self.assertEqual(self.fetches[0][1], {"X-Api-Key": "SEGRETO"})
        self.assertNotIn("SEGRETO", self.fetches[0][0])

    def test_leggi_dati_e_chiedi_al_modello(self):
        m = {"id": "riassunto", "nome": "Riassunto", "effetti": [], "strumenti": [{"nome": "fatti_sintesi", "descrizione": "Riassume i fatti.", "parametri": [],
             "passi": [{"tipo": "leggi_dati", "nome": "fatti"}, {"tipo": "chiedi_al_modello", "istruzione": "Riassumi."}]}]}
        self.store.propose(m)
        self.store.approve("riassunto")
        self.db.add_fact("Suona la chitarra")
        self.assertIn("RISPOSTA", self.tools.run("x_riassunto_fatti_sintesi", {}))

    def test_spenta_o_inesistente_non_si_esegue(self):
        self.install("timer_cottura")
        self.store.set_active("timer_cottura", False)
        self.assertEqual(self.tools.run("x_timer_cottura_timer_avvia", {"minuti": 1, "cosa": "x"}), "Strumento non disponibile.")
        self.assertEqual(self.tools.run("x_boh_boh", {}), "Strumento non disponibile.")

    def test_programma_parte_una_volta_al_giorno(self):
        import datetime as dt
        self.install("meteo")
        tg = FakeTg()
        presto = dt.datetime(2026, 11, 12, 6, 0)
        tardi = dt.datetime(2026, 11, 12, 8, 0)
        self.assertEqual(ext.run_schedules(self.db, tg, 5, self.rt, now=presto), [])
        self.assertEqual(ext.run_schedules(self.db, tg, 5, self.rt, now=tardi), ["meteo"])
        self.assertEqual(ext.run_schedules(self.db, tg, 5, self.rt, now=tardi), [])
        self.assertIn("Meteo", tg.sent[0][1])


class RetePrudenteTests(unittest.TestCase):
    def opener_con(self, risposte):
        it = iter(risposte)

        def opener(req, timeout=0):
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r
        return opener

    def test_redirect_fuori_dai_domini_e_bloccato(self):
        import email.message
        hdrs = email.message.Message()
        hdrs["Location"] = "https://evil.example.org/x"
        err = urllib.error.HTTPError("https://api.example.org/a", 302, "x", hdrs, None)
        with self.assertRaises(ext.ExtError) as cm:
            ext.fetch_allowed("https://api.example.org/a", ["api.example.org"], opener=self.opener_con([err]), resolver=public)
        self.assertIn("non è tra i siti approvati", str(cm.exception))

    def test_indirizzo_non_pubblico_e_bloccato(self):
        with self.assertRaises(ext.ExtError):
            ext.fetch_allowed("https://api.example.org/a", ["api.example.org"], opener=self.opener_con([]),
                              resolver=lambda h, p, proto=0: [(2, 1, 6, "", ("127.0.0.1", 0))])

    def test_dominio_non_dichiarato_e_bloccato(self):
        with self.assertRaises(ext.ExtError):
            ext.fetch_allowed("https://altro.example.org/a", ["api.example.org"], opener=self.opener_con([]), resolver=public)


class ApprovazioniTests(Base):
    def test_proposta_approvata_si_attiva_e_il_bot_la_vede(self):
        aid = ext.propose(self.db, cat("timer_cottura"))
        a = approvals.get(self.db, aid)
        self.assertEqual(a["kind"], "nuova_estensione")
        self.assertIn("Timer di cottura", a["testo"])
        self.assertIsNone(self.store.manifest("timer_cottura"))
        with self.assertRaises(ext.ExtError):
            ext.propose(self.db, cat("timer_cottura"))  # già in attesa
        st, msg = approvals.decide(self.db, aid, "ok")
        self.assertEqual(st, "approvata")
        self.assertIn("attiva", msg)
        self.assertTrue(self.store.state("timer_cottura")["attiva"])

    def test_rifiutata_non_si_attiva_e_si_puo_riproporre(self):
        aid = ext.propose(self.db, cat("meteo"))
        approvals.decide(self.db, aid, "no")
        self.assertIsNone(self.store.pending("meteo"))
        self.assertIsNone(self.store.manifest("meteo"))
        ext.propose(self.db, cat("meteo"))  # può riprovarci

    def test_non_riproporre_piu_e_definitivo(self):
        aid = ext.propose(self.db, cat("meteo"))
        st, msg = approvals.decide(self.db, aid, "mai")
        self.assertEqual(st, "mai_piu")
        with self.assertRaises(ext.ExtError) as cm:
            ext.propose(self.db, cat("meteo"))
        self.assertIn("NON riproporre", str(cm.exception))

    def test_modifica_mostra_cosa_cambia_e_resta_la_vecchia_versione_finche_non_approvata(self):
        self.install("meteo")
        nuovo = cat("meteo")
        nuovo["nome"] = "Meteo più"
        aid = ext.propose(self.db, nuovo)
        self.assertEqual(approvals.get(self.db, aid)["kind"], "modifica_estensione")
        self.assertEqual(self.store.manifest("meteo")["nome"], "Meteo")
        approvals.decide(self.db, aid, "ok")
        self.assertEqual(self.store.manifest("meteo")["nome"], "Meteo più")

    def test_il_bot_non_puo_approvarsi_da_solo(self):
        r = self.tools.run("estensione_proponi", {"manifest": json.dumps(cat("meteo"))})
        self.assertIn("NON è attiva", r)
        self.assertIsNone(self.store.manifest("meteo"))
        self.assertEqual(len(self.tools.take_proposals()), 1)

    def test_manifest_non_valido_dal_bot_torna_come_errore_chiaro(self):
        self.assertTrue(self.tools.run("estensione_proponi", {"manifest": "{non json"}).startswith("Errore"))
        m = cat("meteo")
        m["domini"] = []
        self.assertIn("domini", self.tools.run("estensione_proponi", {"manifest": json.dumps(m)}))
        self.assertEqual(self.tools.take_proposals(), [])

    def test_bottone_non_riproporre_solo_dove_serve(self):
        k = approvals.keyboard(5, "nuova_estensione")["inline_keyboard"]
        self.assertEqual(k[1][0]["callback_data"], "ap:5:mai")
        self.assertEqual(len(approvals.keyboard(5, "bozza_post")["inline_keyboard"]), 1)
        aid = approvals.create(self.db, "bozza_post", "t", "testo")
        self.assertEqual(approvals.decide(self.db, aid, "mai")[0], None)

    def test_catalogo_installa_solo_se_l_impronta_coincide(self):
        aid = ext.catalog_install(self.db, "ricettario")
        self.assertIn("dal catalogo", approvals.get(self.db, aid)["testo"])
        with tempfile.TemporaryDirectory() as d:
            for n in os.listdir(CAT):
                with open(os.path.join(CAT, n), "rb") as src, open(os.path.join(d, n), "wb") as dst:
                    dst.write(src.read())
            with open(os.path.join(d, "meteo.json"), "a", encoding="utf-8") as f:
                f.write(" ")  # file cambiato a mano
            with self.assertRaises(ext.ExtError):
                ext.catalog_install(self.db, "meteo", directory=d)
        with self.assertRaises(ext.ExtError):
            ext.catalog_install(self.db, "inesistente")


class LezioniTests(Base):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.db.profile_dir, "profile.json"), "w", encoding="utf-8") as f:
            json.dump({"proprietario": "Marta", "regole_extra": ["Rispondi breve."], "kb": {"repo": "x"}}, f)

    def regole(self):
        return prof.load(self.db.profile_dir)["regole_extra"]

    def test_lezione_duplicata_conta_le_ripetizioni(self):
        a = self.db.lesson_add("Non usare più di 3 hashtag", "ha rifiutato due post")
        b = self.db.lesson_add("non usare più di 3 hashtag!", "")
        self.assertEqual((a[0], b[0], b[2]), (a[0], a[0], False))
        self.assertEqual(self.db.lesson_get(a[0])["ripetizioni"], 2)

    def test_regola_proposta_cambia_il_profilo_solo_dopo_il_si(self):
        lid = self.db.lesson_add("Preferisce testi corti", "")[0]
        out = self.tools.run("regola_proponi", {"azione": "aggiungi", "regola": "Scrivi didascalie sotto i 150 caratteri.", "lezione_id": lid})
        self.assertIn("Proposta", out)
        self.assertEqual(self.regole(), ["Rispondi breve."])
        aid = self.tools.take_proposals()[0]
        self.assertIn("AGGIUNGO", approvals.get(self.db, aid)["testo"])
        self.assertEqual(self.db.lesson_get(lid)["stato"], "proposta")
        st, msg = approvals.decide(self.db, aid, "ok")
        self.assertEqual(st, "approvata")
        self.assertEqual(self.regole(), ["Rispondi breve.", "Scrivi didascalie sotto i 150 caratteri."])
        self.assertEqual(prof.load(self.db.profile_dir)["kb"], {"repo": "x"})  # il resto non si tocca
        self.assertEqual(self.db.lesson_get(lid)["stato"], "adottata")

    def test_rifiutata_si_riproporra_dopo_i_giorni_del_profilo(self):
        lid = self.db.lesson_add("Preferisce testi corti", "")[0]
        self.tools.run("regola_proponi", {"azione": "aggiungi", "regola": "Scrivi didascalie corte.", "lezione_id": lid})
        approvals.decide(self.db, self.tools.take_proposals()[0], "no")
        lez = self.db.lesson_get(lid)
        self.assertEqual(lez["stato"], "rifiutata")
        self.assertGreater(lez["riproponi_dopo"], time.time() + 13 * 86400)
        self.assertIn("rifiutata da poco", self.tools.run("regola_proponi", {"azione": "aggiungi", "regola": "Scrivi didascalie corte.", "lezione_id": lid}))
        self.assertEqual(self.db.lessons_list("da_riproporre"), [])
        self.db._x("UPDATE lezioni SET riproponi_dopo=? WHERE id=?", (time.time() - 1, lid))
        self.assertEqual([l["id"] for l in self.db.lessons_list("da_riproporre")], [lid])
        self.assertIn("Proposta", self.tools.run("regola_proponi", {"azione": "aggiungi", "regola": "Scrivi didascalie corte.", "lezione_id": lid}))

    def test_non_riproporre_piu_ferma_per_sempre(self):
        lid = self.db.lesson_add("Preferisce testi corti", "")[0]
        self.tools.run("regola_proponi", {"azione": "aggiungi", "regola": "Scrivi didascalie corte.", "lezione_id": lid})
        st, _ = approvals.decide(self.db, self.tools.take_proposals()[0], "mai")
        self.assertEqual(st, "mai_piu")
        self.assertEqual(self.db.lesson_get(lid)["stato"], "mai_piu")
        self.db._x("UPDATE lezioni SET riproponi_dopo=1 WHERE id=?", (lid,))
        self.assertIn("non riproporre", self.tools.run("regola_proponi", {"azione": "aggiungi", "regola": "Scrivi didascalie corte.", "lezione_id": lid}))
        self.assertIn("non riproporre", self.tools.run("lezione_salva", {"testo": "Preferisce testi corti!"}))
        self.assertEqual(self.db.lessons_list(), [])

    def test_sostituisci_e_rimuovi_e_regola_inesistente(self):
        self.tools.run("regola_proponi", {"azione": "sostituisci", "regola": "Rispondi in due righe.", "sostituisce": "Rispondi breve."})
        approvals.decide(self.db, self.tools.take_proposals()[0], "ok")
        self.assertEqual(self.regole(), ["Rispondi in due righe."])
        self.tools.run("regola_proponi", {"azione": "rimuovi", "sostituisce": "Rispondi in due righe."})
        approvals.decide(self.db, self.tools.take_proposals()[0], "ok")
        self.assertEqual(self.regole(), [])
        self.assertIn("non c'è", self.tools.run("regola_proponi", {"azione": "rimuovi", "sostituisce": "boh"}))
        self.assertIn("non valida", self.tools.run("regola_proponi", {"azione": "cancella_tutto"}))

    def test_apply_rule_non_tocca_altri_campi_e_non_duplica(self):
        self.assertEqual(prof.apply_rule(self.db.profile_dir, "aggiungi", "rispondi breve."), "La regola c'era già.")
        with self.assertRaises(ValueError):
            prof.apply_rule(self.db.profile_dir, "boh", "x")


if __name__ == "__main__":
    unittest.main()
