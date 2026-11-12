"""Attività programmate. Solo lettura + messaggio al proprietario: nessuna azione verso l'esterno.

- report settimanale (lunedì 08:30, ora italiana): numeri dell'account, contenuti musicali più recenti, suggerimenti;
- ricerca opportunità (mercoledì 09:00): concorsi/bandi/festival, solo con fonte verificata.
I messaggi arrivano in silenzio (senza suono). Con /pausa non parte niente.
"""
import datetime as dt

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Rome")
except Exception:  # senza database dei fusi orari: ora UTC (meglio di niente, e lo dico nel log)
    TZ = dt.timezone.utc

MAX_TENTATIVI = 3

JOBS = {
    "report_settimanale": {
        "weekday": 0, "hour": 8, "minute": 30,
        "prompt": (
            "Prepara il REPORT SETTIMANALE per il proprietario (lunedì). Usa gli strumenti: prima instagram_statistiche_account (giorni=7), "
            "poi instagram_statistiche_reel (quanti=8) per i contenuti musicali più recenti. "
            "Scrivi: 1) numeri della settimana in 4-5 righe, con ogni termine tecnico spiegato; 2) cosa ha funzionato e cosa no, "
            "distinguendo fatto misurato da tua ipotesi; 3) UNA o DUE cose da fare questa settimana, concrete e piccole. "
            "Fai anche UN grafico utile (es. copertura giorno per giorno, oppure le visualizzazioni dei reel a confronto) con lo strumento grafico, "
            "e commenta il senso senza ripetere ogni numero. "
            "Massimo circa 1500 caratteri, niente elenchi lunghi, niente invenzioni. Non pubblicare nulla: proponi e basta."),
    },
    "ricerca_opportunita": {
        "weekday": 2, "hour": 9, "minute": 0,
        "prompt": (
            "Fai la RICERCA SETTIMANALE di opportunità per il proprietario: concorsi, contest, festival o bandi italiani per artisti emergenti "
            "con iscrizioni APERTE oggi. Usa web_cerca e poi web_leggi/web_browser sulle pagine ufficiali. "
            "Tieni solo ciò che verifichi su una fonte con scadenza leggibile; per ogni voce valida salvala con opportunita_salva "
            "(solo se ha link e data di verifica). Controlla se accetta il tipo di contenuti del proprietario (cover o inediti: guarda i fatti noti) e i costi. "
            "Scrivi un messaggio breve (massimo circa 1500 caratteri): le novità (max 3), scadenza, costi, link, e cosa non hai potuto verificare. "
            "Se non trovi niente di nuovo dillo in una riga. Non iscriverti e non scrivere a nessuno."),
    },
    # Lavoro interno: il manager decide da solo cosa gli manca e mette le domande in coda (le invia l'agenda).
    "revisione_lacune": {
        "weekday": 4, "hour": 17, "minute": 0, "deliver": False,
        "prompt": (
            "REVISIONE INTERNA (Il proprietario non vedrà questo testo). Guarda cosa ti manca per far funzionare bene il piano e gli obiettivi del proprietario "
            "(quelli scritti nelle regole dell'account e nei fatti noti): leggi ped_leggi, archivio_riepilogo e i FATTI già noti. "
            "Se manca un'informazione che SOLO il proprietario può darti (dettagli di brani o progetti che vuole mostrare, "
            "disponibilità per collaborazioni, se i contenuti incerti sono musicali), metti in coda al massimo 2 domande con chiedi_al_proprietario: "
            "brevi, una cosa sola, facili da rispondere dal telefono. Non rifare domande già in coda o già fatte. Se non manca nulla, non chiedere nulla. "
            "Rispondi solo «ok»."),
    },
    # Impara dall'uso: ogni domenica rilegge le lezioni e può proporre UNA o DUE regole per sé (sempre da approvare)
    "revisione_lezioni": {
        "weekday": 6, "hour": 18, "minute": 0, "deliver": False,
        "prompt": (
            "REVISIONE DELLE LEZIONI (lavoro interno, il proprietario non vedrà questo testo, ma vedrà le proposte con i bottoni). "
            "Chiama lezioni_leggi(stato=da_riproporre). Guarda anche le conversazioni recenti: se ti ha corretto o ha mostrato una preferenza ripetuta, "
            "salvala con lezione_salva (testo breve, con cosa l'ha fatta nascere). Poi scegli al massimo 2 lezioni che valgono la pena e per ognuna usa regola_proponi "
            "(azione aggiungi o sostituisci, collegando la lezione). Non proporre lezioni rifiutate da poco o scartate per sempre: lo strumento te lo dirà. "
            "Se non c'è niente di utile, non proporre niente. Rispondi solo «ok»."),
    },
    # Archivio di conoscenza: studio quotidiano delle novità (solo se l'account ne ha uno)
    "studio_kb": {
        "weekday": None, "hour": 6, "minute": 30, "deliver": False, "cond": "kb_attivo",
        "prompt": (
            "STUDIO DELL'ARCHIVIO (lavoro interno, il proprietario non vedrà questo testo). Chiama kb_novita. "
            "Se ci sono file nuovi o cambiati, leggili (kb_leggi) e aggiorna le TUE conoscenze: salva con appunto_salva le cose importanti "
            "(regole nuove, decisioni, lezioni dai dati) e, se una decisione del proprietario è scritta lì, con fatto_salva. "
            "Se l'ultimo commit dell'archivio ha più di 14 giorni, chiedi UNA volta con chiedi_al_proprietario se l'archivio va aggiornato o se qualcosa si è rotto. "
            "Non modificare nulla senza kb_proponi_modifica. Rispondi solo «ok»."),
    },
    # Promemoria contatti: ogni lunedì decide a chi scrivere nei giorni successivi (poi i promemoria arrivano da soli)
    "pianifica_contatti": {
        "weekday": 0, "hour": 9, "minute": 30, "cond": "contatti_da_pianificare",
        "prompt": (
            "PIANIFICA I CONTATTI della settimana. Leggi contatti_leggi(stato=da_valutare) e contatti_da_fare. Se c'è un archivio (kb_cerca / kb_leggi), "
            "consulta le regole su QUANDO e COME scrivere a ogni tipo di contatto (edizioni, periodi, canali, cosa non dire). "
            "Scegli al massimo 5 contatti a cui è il momento giusto scrivere nei prossimi 10 giorni e per ognuno usa contatto_aggiorna con "
            "stato=da_scrivere e prossima_azione_il=data. Spargi le date: massimo 1-2 al giorno, mai nel weekend se le regole dicono diversamente. "
            "Scrivi poi un messaggio breve al proprietario: a chi lo ricorderai e quando, in 4-6 righe. Non scrivere a nessuno tu."),
    },
    # Il piano si rinnova da solo prima di finire: arriva al proprietario come proposta da approvare.
    "rinnovo_ped": {
        "weekday": None, "hour": 10, "minute": 0, "reason": True, "cond": "ped_in_scadenza",
        "prompt": "__PED__",
    },
}


def ped_in_scadenza(db, now: dt.datetime) -> bool:
    """Vero se c'è già stato un piano, finisce entro 7 giorni e non c'è già una proposta di piano in attesa."""
    rows = db.ped_list()
    if not rows:
        return False  # il primo piano si fa solo con /piano: è una scelta del proprietario, non un automatismo
    last = max(r["day"] for r in rows)
    if (dt.date.fromisoformat(last) - now.date()).days > 7:
        return False
    pend = db._x("SELECT 1 FROM approvals WHERE status='in_attesa' AND payload LIKE '%Piano 30 giorni%' LIMIT 1").fetchone()
    return pend is None


def kb_attivo(db, now) -> bool:
    return db.get("kb:attivo", "") == "1"


def contatti_da_pianificare(db, now) -> bool:
    """Ci sono contatti da valutare e meno di 5 già programmati nei prossimi giorni."""
    da_valutare = db._x("SELECT COUNT(*) FROM contacts WHERE status='da_valutare'").fetchone()[0]
    programmati = db._x("SELECT COUNT(*) FROM contacts WHERE status='da_scrivere' AND next_followup>=?", (now.date().isoformat(),)).fetchone()[0]
    return da_valutare > 0 and programmati < 5


CONDS = {"ped_in_scadenza": ped_in_scadenza, "kb_attivo": kb_attivo, "contatti_da_pianificare": contatti_da_pianificare}


def jobs_for(profile: dict) -> dict:
    """Lavori attivi per un account: quelli di base meno quelli spenti, più quelli propri del profilo."""
    jobs = {n: j for n, j in JOBS.items() if n not in set(profile.get("lavori_spenti") or [])}
    for n, j in (profile.get("lavori") or {}).items():
        if isinstance(j, dict) and j.get("prompt"):
            jobs[n] = j
    return jobs


def ped_prompt(today: dt.date, start: dt.date = None) -> str:
    start = start or today + dt.timedelta(days=1)
    end = start + dt.timedelta(days=29)
    return (
        f"Costruisci il PIANO EDITORIALE DIGITALE (PED) di 30 giorni per il proprietario, dal {start.isoformat()} al {end.isoformat()}. "
        "Il proprietario si concentra sul creare: tutto il resto lo fai tu. "
        "PRIMA raccogli i dati con gli strumenti: storico_account (giorni_migliori, artisti, classifica, pubblico, scomposizione, settimane), "
        "archivio_cerca (contenuti già fatti, per non ripetere e per riproporre i migliori), ped_leggi, e le opportunità salvate (/opportunita). "
        "Tieni conto dei FATTI DETTI DAL PROPRIETARIO e delle regole dell'account qui sopra (obiettivi e priorità, cadenza possibile, "
        "cosa non è una priorità ora). "
        "REGOLE: solo contenuti musicali e professionali, mai personali; cadenza realistica per chi lavora da solo (nel dubbio circa 3 uscite a settimana, non di più); "
        "pubblica nei giorni e nelle fasce che i dati indicano (con la cautela dei campioni piccoli); alterna contenuti ad alta resa (quelli che nei dati vanno meglio) "
        "con contenuti utili agli obiettivi dichiarati, SENZA inventare dettagli che non conosci, e almeno un contenuto per salvataggi/condivisioni "
        "se i dati mostrano che sono il punto debole. Per i concorsi usa solo quelli verificati in archivio, con la loro scadenza. "
        "Non inventare mai fatti, collaborazioni o risultati, e non attribuire al proprietario modalità che non risultano dai dati o dai fatti "
        "(per esempio luoghi, strumenti, attrezzatura): se serve, scrivilo come domanda da fargli. "
        "Se riproponi un contenuto GIÀ pubblicato, chiamalo 'riproposta' e scrivi quando è uscito. Per ogni voce scrivi la motivazione basata sui dati e distingui fatto da ipotesi. "
        "Poi salva con ped_salva (piano 'PED " + start.strftime("%Y-%m") + "') UNA SETTIMANA PER VOLTA "
        "(prima chiamata aggiungi=false, le successive aggiungi=true; motivazioni brevi, max 150 caratteri), "
        "fai UN grafico con il numero di uscite per settimana (o per tipo), e proponi al proprietario l'approvazione del piano con proponi_bozza "
        "(tipo idea_contenuto, titolo 'Piano 30 giorni', testo = riassunto breve delle settimane e dei 3 obiettivi misurabili che userai per valutarlo). "
        "Nel messaggio finale: massimo 1500 caratteri, riassunto per settimana, cosa deve fare il proprietario (registrare cosa e quando) e cosa faccio io. "
        "Non pubblicare nulla.")


def period_key(job: dict, now: dt.datetime) -> str:
    """Identifica la 'settimana di competenza' (data del giorno programmato)."""
    if job.get("weekday") is None:  # lavoro giornaliero
        return now.date().isoformat()
    d = now.date() - dt.timedelta(days=(now.weekday() - job["weekday"]) % 7)
    return d.isoformat()


def is_due(job: dict, now: dt.datetime, done_key: str) -> bool:
    """Vero se il giorno/ora programmato è passato in questo periodo (settimana o giorno) e non è già stato fatto."""
    if period_key(job, now) == done_key:
        return False
    if job.get("weekday") is None:
        return (now.hour, now.minute) >= (job["hour"], job["minute"])
    return (now.weekday(), now.hour, now.minute) >= (job["weekday"], job["hour"], job["minute"]) or now.weekday() > job["weekday"]


def deliver(tg, chat_id: int, agent, text: str, silent: bool = False):
    """Prima le immagini create durante la risposta, poi il testo. Se un'immagine non parte, il testo parte lo stesso."""
    tools = getattr(agent, "tools", None)
    for png, cap in (tools.take_images() if tools else []):
        try:
            tg.send_photo(chat_id, png, cap, silent=silent)
        except Exception:
            pass
    tg.send(chat_id, text, silent=silent)
    from . import approvals
    for aid in (tools.take_proposals() if tools else []):  # bozze da approvare, con i bottoni
        a = approvals.get(agent.db, aid)
        if a:
            tg.send(chat_id, approvals.message(a), silent=silent, reply_markup=approvals.keyboard(aid, a["kind"]))


def run_due_jobs(db, agent, tg, owner_id: int, now: dt.datetime = None, jobs: dict = None) -> list:
    """Esegue i lavori scaduti. Ritorna i nomi eseguiti con successo. Chiamata dal ciclo principale (~ogni minuto)."""
    if db.paused():
        return []
    now = now or dt.datetime.now(TZ)
    done = []
    for name, job in (JOBS if jobs is None else jobs).items():
        if not is_due(job, now, db.get(f"job:{name}:done", "")):
            continue
        cond = CONDS.get(job.get("cond"))
        if cond and not cond(db, now):  # niente da fare oggi: non è un fallimento, ricontrollo al prossimo giro
            continue
        key = period_key(job, now)
        tent_key = f"job:{name}:tent:{key}"
        n = int(db.get(tent_key, "0") or 0)
        if n >= MAX_TENTATIVI:  # basta: non insistere, e lo segno
            db.set(f"job:{name}:done", key)
            db.audit("sistema", "job_rinunciato", name)
            continue
        db.set(tent_key, str(n + 1))
        try:
            prompt = job["prompt"]
            if prompt == "__PED__":  # il nuovo piano parte dal giorno dopo l'ultimo del precedente
                last = dt.date.fromisoformat(max(r["day"] for r in db.ped_list()))
                prompt = ped_prompt(now.date(), start=max(last, now.date()) + dt.timedelta(days=1))
            model = agent.cfg.model_reason if job.get("reason") else None
            visible = job.get("deliver", True)
            text = agent.run_task(prompt, model=model, remember=visible)
            if visible:
                deliver(tg, owner_id, agent, text, silent=True)
            db.set(f"job:{name}:done", key)
            db.audit("sistema", "job_ok", name)
            done.append(name)
        except Exception as e:
            db.audit("sistema", "job_errore", f"{name}: {type(e).__name__}")
    return done


def run_due_tasks(db, agent, tg, owner_id: int, now: dt.datetime = None) -> list:
    """Attività una tantum programmate dal manager stesso (strumento programma_attivita). Max 3 tentativi."""
    if db.paused():
        return []
    now = (now or dt.datetime.now(TZ)).replace(tzinfo=None)
    done = []
    for t in db.tasks_pending():
        if dt.datetime.fromisoformat(t["due"]) > now:
            continue
        if t["attempts"] >= MAX_TENTATIVI:
            db.task_set(t["id"], "fallita")
            db.audit("sistema", "attivita_rinunciata", f"#{t['id']}")
            continue
        db.task_set(t["id"], "in_attesa", attempts=t["attempts"] + 1)
        try:
            text = agent.run_task("(Attività che avevi programmato tu) " + t["instruction"])
            deliver(tg, owner_id, agent, text, silent=True)
            db.task_set(t["id"], "fatta")
            db.audit("sistema", "attivita_ok", f"#{t['id']}")
            done.append(t["id"])
        except Exception as e:
            db.audit("sistema", "attivita_errore", f"#{t['id']}: {type(e).__name__}")
    return done


# --- agenda: messaggi senza IA (veloci, gratis, prevedibili) ---
FASCIA_DOMANDE = (10, 20)  # le domande partono solo di giorno (ora italiana)
PAUSA_DOMANDE_ORE = 20  # al massimo una domanda ogni 20 ore: non devo sembrare un interrogatorio
SOLLECITO_ORE = 36
SCADENZA_DOMANDA_GIORNI = 7
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def run_agenda(db, tg, owner_id: int, now: dt.datetime = None) -> list:
    """Invia le domande in coda e i promemoria. Ritorna le etichette inviate (per i test)."""
    if db.paused():
        return []
    now = now or dt.datetime.now(TZ)
    ts = now.timestamp()
    sent = []
    # 0) le voci approvate con data passata diventano 'trascorso': il calendario si tiene in ordine da solo
    db.ped_set_status("approvato", "trascorso", before_day=now.date().isoformat())
    # 1) domanda aperta: un solo sollecito dopo 36 ore, poi rinuncia dopo 7 giorni
    q = db.question_get("posta")
    if q:
        age_h = (ts - (q["asked_ts"] or ts)) / 3600
        if age_h > SCADENZA_DOMANDA_GIORNI * 24:
            db.question_set(q["id"], "senza_risposta")
            db.audit("sistema", "domanda_scaduta", f"#{q['id']}")
        elif age_h > SOLLECITO_ORE and not q["reminded"] and FASCIA_DOMANDE[0] <= now.hour < FASCIA_DOMANDE[1]:
            tg.send(owner_id, f"Ti ricordo la domanda di prima, quando hai un attimo:\n\n{q['text']}\n\n(Se non lo sai, scrivi «non so».)", silent=True)
            db.question_set(q["id"], "posta", reminded=True)
            sent.append("sollecito")
    # 2) nuova domanda: solo se non ce n'è una aperta, in fascia diurna, e con la pausa minima
    elif FASCIA_DOMANDE[0] <= now.hour < FASCIA_DOMANDE[1]:
        last = float(db.get("agenda:ultima_domanda", "0") or 0)
        nxt = db.question_get("in_coda")
        if nxt and ts - last > PAUSA_DOMANDE_ORE * 3600:
            why = f"\n\n(Mi serve per: {nxt['why']})" if nxt["why"] else ""
            tg.send(owner_id, f"Ho una domanda per te:\n\n{nxt['text']}{why}\n\nRispondimi quando vuoi, anche in due parole.")
            db.question_set(nxt["id"], "posta", asked=True)
            db.set("agenda:ultima_domanda", str(ts))
            db.audit("sistema", "domanda_inviata", f"#{nxt['id']}")
            sent.append("domanda")
    # 3) promemoria serale: cosa c'è da registrare/pubblicare domani (una volta al giorno, alle 18)
    if now.hour >= 18 and db.get("agenda:promemoria", "") != now.date().isoformat():
        db.set("agenda:promemoria", now.date().isoformat())
        dom = now.date() + dt.timedelta(days=1)
        voci = [v for v in db.ped_list(None, dom.isoformat(), dom.isoformat()) if v["status"] != "scartato"]
        if voci:
            righe = [f"- {v['title']}" + (f" ({v['song']} - {v['artist']})" if v.get("song") and v.get("artist") else "")
                     for v in voci]
            tg.send(owner_id, f"Domani, {GIORNI[dom.weekday()]}, nel piano c'è:\n" + "\n".join(righe) +
                    "\n\nSe è un video da registrare, mandamelo qui quando è pronto e me ne occupo io. Se non puoi, dimmelo e sposto la data.",
                    silent=True)
            sent.append("promemoria")
    # 4) proposte in attesa da più di un giorno: un richiamo ogni 48 ore al massimo, alle 11
    if now.hour >= 11 and ts - float(db.get("agenda:richiamo_approvazioni", "0") or 0) > 48 * 3600:
        vecchie = db._x("SELECT COUNT(*) FROM approvals WHERE status='in_attesa' AND CAST(ts AS REAL) < ?",
                        (ts - 24 * 3600,)).fetchone()[0]
        if vecchie:
            db.set("agenda:richiamo_approvazioni", str(ts))
            tg.send(owner_id, f"Hai {vecchie} proposte in attesa da più di un giorno: cerca i messaggi con i bottoni "
                    "Approva / Rifiuta / Cambia. Basta un tocco, e il piano va avanti.", silent=True)
            sent.append("richiamo")
    return sent


MAX_PROMEMORIA_CONTATTI = 3  # al giorno: devono essere utili, non una valanga
FASCIA_CONTATTI = (10, 19)


def contact_keyboard(cid: int) -> dict:
    return {"inline_keyboard": [[{"text": "✅ Fatto", "callback_data": f"ct:{cid}:ok"},
                                 {"text": "⏰ Domani", "callback_data": f"ct:{cid}:d1"},
                                 {"text": "📅 Tra 1 settimana", "callback_data": f"ct:{cid}:w1"}],
                                [{"text": "🚫 Escludi", "callback_data": f"ct:{cid}:no"}]]}


def contact_message(c: dict) -> str:
    n = c.get("messaggi_inviati") or 0
    azione = "Primo messaggio" if not n else f"Follow-up (hai già scritto {n} {'volta' if n == 1 else 'volte'}, ultima il {c.get('ultimo_contatto') or '?'})"
    righe = [f"📨 Da fare oggi: **{c['nome']}**" + (f" ({c['tipo']})" if c.get("tipo") else ""), azione]
    if c.get("canale") or c.get("handle"):
        righe.append("Dove: " + " · ".join(x for x in (c.get("canale"), c.get("handle")) if x))
    if c.get("fonte"):
        righe.append(f"Fonte: {c['fonte']}")
    if c.get("note"):
        righe.append(f"Note: {c['note']}")
    righe.append("\nScrivimi «bozza» e ti preparo il testo. Quando l'hai mandato, tocca Fatto.")
    return "\n".join(righe)


def run_contact_reminders(db, tg, owner_id, now: dt.datetime = None) -> list:
    """Ogni giorno (di giorno) ricorda al massimo 3 contatti da scrivere o da sollecitare, con i bottoni per chiudere
    la cosa con un tocco. Non invia nulla a nessuno: scrive il proprietario. Ritorna gli id ricordati."""
    import json
    if db.paused():
        return []
    now = now or dt.datetime.now(TZ)
    if not FASCIA_CONTATTI[0] <= now.hour < FASCIA_CONTATTI[1]:
        return []
    today = now.date().isoformat()
    if db.get("contatti:giorno", "") == today:
        return []
    db.set("contatti:giorno", today)
    due = [c for c in db.contacts_due(today) if c.get("ultimo_contatto") != today][:MAX_PROMEMORIA_CONTATTI]
    ids = []
    owners = list(owner_id) if isinstance(owner_id, (list, tuple, set)) else [owner_id]
    for c in due:
        for oid in owners:  # più proprietari (es. due membri della band): lo ricevono tutti, il primo che tocca "Fatto" chiude la cosa
            tg.send(oid, contact_message(c), silent=True, reply_markup=contact_keyboard(c["id"]))
        db.contact_reminded(c["id"], today)
        ids.append(c["id"])
    db.set("contatti:oggi", json.dumps({"giorno": today, "ids": ids}))
    if ids:
        db.audit("sistema", "promemoria_contatti", ",".join(map(str, ids)))
    return ids


def apply_contact_action(db, cid: int, action: str, today: dt.date = None) -> str:
    """Azione dei bottoni (decisione esplicita del proprietario con un tocco). Ritorna il testo di conferma."""
    today = today or dt.datetime.now(TZ).date()
    c = db.contact_get(cid)
    if not c:
        return "Non trovo questo contatto."
    if action == "ok":
        if c.get("ultimo_contatto") == today.isoformat():
            return f"{c['nome']} era già stato segnato oggi: nessun doppione."
        db.contact_sent(cid, today.isoformat(), 14)
        db.audit("proprietario", "contatto_segnato_inviato", f"#{cid}")
        return f"Segnato: hai scritto a {c['nome']}. Ti ricordo il follow-up tra 14 giorni."
    if action in ("d1", "w1"):
        nxt = today + dt.timedelta(days=1 if action == "d1" else 7)
        db.contact_update(cid, next_followup=nxt.isoformat())
        return f"Ok, {c['nome']} te lo ricordo il {nxt.strftime('%d/%m')}."
    if action == "no":
        db.contact_update(cid, status="escluso")
        db.audit("proprietario", "contatto_escluso", f"#{cid}")
        return f"Ok, {c['nome']} escluso: non te lo ricordo più."
    return "Azione non riconosciuta."

