# CLAUDE.md — istruzioni per lavorare su EDITH

EDITH è un assistente **Telegram self-hosted** che aiuta a gestire profili social (artisti, band, creator, piccole attività). Un contenitore Docker, più account; ognuno ha il suo bot, i suoi dati, la sua personalità. Legge Instagram **solo in sola lettura**, prepara bozze e **aspetta sempre l'approvazione** di una persona.

Chi lo usa parla italiano e spesso **non è un esperto**. Scrivi, spiega e rispondi in **italiano semplice**, senza gergo, passi piccoli.

## Regole che non si piegano
1. **Mai scrittura verso l'esterno senza approvazione.** Pubblicare, commentare, scrivere messaggi, candidarsi, comprare, firmare: vietato. Una funzione così entra solo dietro approvazione a bottoni (`approvals.py`), `guard.py` e un test che lo dimostra. Gli strumenti fissi sono in sola lettura; in più ci sono le **estensioni dichiarative approvate** (`extensions.py`): leggono da domini approvati, tengono dati propri e avvisano il proprietario, mai di più. Il bot non può approvare niente da solo.
2. **Instagram solo con le API ufficiali di Meta, in sola lettura.** Niente scraping, API private, cookie o password estratti dal browser, aggiramento di MFA o CAPTCHA.
3. **Mai segreti nel repository, nei log, nei documenti, nei commit, nella memoria dell'assistente.** Token, chiavi e password stanno solo in `.env` e `accounts/<nome>/account.env` (permessi `600`, mai su Git). Prima di ogni push: `python scripts/check_secrets.py`.
4. **Mai dati personali di persone reali nel repository** (nomi, ID Telegram, email, indirizzi, domini privati): né nei file né nella storia dei commit. Gli esempi sono inventati. È un repository pubblico.
5. **Mai inventare.** Il manager distingue fatto verificato / detto dal proprietario / ipotesi. Una modifica che rende più facile inventare non entra.
6. **Solo il proprietario** (gli ID in `ALLOWED_TELEGRAM_USER_ID`) può usare un bot.
7. **Niente operazioni distruttive.** I dati non si cancellano (si «mettono da parte»). Cancella solo ciò che è davvero inutile e dopo aver guardato cosa è.
8. **Il pannello web non ha accesso a Docker**, di proposito (sarebbe l'accesso root al server). `update` si fa dal terminale.

## Mappa del codice
```
bot/app/
  main.py            orchestratore: un thread per account, rilevamento account nuovi ogni 30 s, Control (riavvio)
  config.py          carica .env e gli account (load_accounts), una Config per account
  accounts.py        procedura guidata (add/list/check/remove), scrittura di account.env e profile.json
  agent.py, ai.py    conversazione con l'IA (servizio compatibile OpenAI), contesto persistente
  tools.py           strumenti usabili in conversazione, tutti in sola lettura
  tg.py              client Telegram (solo libreria standard)
  db.py              memoria persistente (SQLite), per account
  scheduler.py       lavori programmati: piano editoriale, promemoria contatti, report
  approvals.py       il manager propone, il proprietario decide con un tocco
  guard.py           blocco: non tocca mai contenuti personali o non classificati
  instagram.py, import_account.py, audit_instagram.py, analytics.py   Graph API in sola lettura
  kb.py              archivio di conoscenza (repository Git dell'account)
  profile.py         personalità e regole dell'account (profile.json)
  panel.py           pannello web (solo libreria standard, nessun JavaScript)
  panel_ext.py       pagine del pannello per estensioni, approvazioni, lezioni, catalogo (il pannello disegna dal manifest)
  esperti.py         esperti = ruoli di consulenza di terzi (bot/esperti, MIT): una chiamata all'IA senza strumenti, impronta ricontrollata, token oscurati
  extensions.py      estensioni dichiarative: validazione, archivio fuori dal contenitore, passi, timer, approvazioni, catalogo
  logbuf.py          registro in memoria con segreti oscurati, per la pagina «Stato e registro»
  static/panel.css   stile del pannello (Tailwind già compilato, versionato)
bot/ui/              configurazione per rigenerare panel.css
bot/esperti/         35 ruoli da agency-agents (MIT) + INDICE.json con impronte: `python scripts/importa_esperti.py`; leggi i file nuovi PRIMA di committare
bot/catalogo/        estensioni già pronte + INDICE.json (impronte): `python scripts/aggiorna_catalogo.py` dopo ogni modifica
bot/tests/           test (unittest, nessuna rete)
scripts/check_secrets.py   controllo segreti, usato anche dalla CI
docs/                guide per utenti e per chi aiuta
```

## Comandi
```bash
cd bot && python -I -m unittest discover -s tests     # test (alcuni usano un server locale: usa PYTHONPATH=. se serve)
python scripts/check_secrets.py                       # nessun segreto nei file
bash -n setup.sh && bash -n manager                   # controllo script
# stile del pannello (solo se cambi le classi in panel.py): vedi bot/ui/README.md
```

## Convenzioni
- **Solo libreria standard** di Python, salvo ottime ragioni: il contenitore resta piccolo (circa 20 MB di RAM per account). Python 3.13 nel contenitore: non usare funzioni più nuove.
- **Il codice non nomina persone o progetti specifici.** L'identità viene da `profile.json` (`proprietario`, `identita`, `regole_extra`, `ambito`…). Il prompt di sistema usa segnaposto.
- **Il pannello:** niente JavaScript, niente risorse esterne; CSP `default-src 'none'; style-src 'self'`. Ogni modulo ha il codice anti-CSRF; i segreti si scrivono ma non si mostrano mai. Le classi Tailwind sono stringhe intere in `panel.py` (non costruirle con pezzi concatenati, altrimenti non finiscono nel CSS).
- **Messaggi per le persone in italiano semplice.** Ogni campo del pannello ha una riga di aiuto con un esempio.
- **Esperti:** sono testi di terzi: restano senza strumenti e senza dati dell'account, con le regole di EDITH prima del ruolo; non si modificano a mano (l'impronta lo scopre); non importare agenti che pubblicano o fanno scraping.
- **Estensioni:** niente codice libero, niente passi che scrivono verso l'esterno; ogni testo del manifest in pagina passa da `html.escape`; nuove classi Tailwind in `panel_ext.py` → rigenera il CSS. Un nuovo tipo di passo ha validatore, difese e test.
- **Test per ogni cosa che tocca sicurezza o dati.** Le chiamate esterne si simulano.
- **Commit:** messaggi chiari; usa un'identità noreply, mai l'email di lavoro di qualcuno.

## Guidare un utente nel setup
Se stai aiutando una persona a installare o configurare EDITH, leggi **[docs/GUIDARE-L-UTENTE.md](docs/GUIDARE-L-UTENTE.md)** prima di cominciare. In breve:
- l'utente fa **lui** gli accessi (password, MFA, condizioni); tu non digiti mai password per lui e non gliele chiedi in chat;
- se incolla un segreto in chat, lo usi solo nel `.env` sul server, non lo scrivi altrove, e gli suggerisci con calma di cambiarlo;
- prima di **scrivere** in una finestra del browser fai uno screenshot e controlla dove sei;
- dopo ogni passo verifichi (`./manager check`, `curl`, screenshot): non dici «fatto» senza aver controllato;
- ogni azione che esce dal suo computer (repository pubblico, DNS, app Meta, deploy automatico) la **proponi e aspetti il sì**.

Il passo-passo completo è in [docs/SETUP.md](docs/SETUP.md); Instagram/Meta in [docs/INSTAGRAM.md](docs/INSTAGRAM.md).

## Prima di pubblicare o fare release
1. Test e `check_secrets.py` passano.
2. Cerca nomi, ID, email, domini privati **nei file e nella storia** (`git log -p | grep -iE "..."`): un dato in un commit vecchio resta pubblico per sempre.
3. Aggiorna `CHANGELOG.md` (e i documenti toccati).
4. La CI (`.github/workflows/ci.yml`) deve essere verde; l'immagine si costruisce da sola (`docker.yml`). Il deploy automatico (`deploy.yml`) è spento finché il proprietario non lo attiva.
