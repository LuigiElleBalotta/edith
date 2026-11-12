# EDITH

**Un assistente digitale su Telegram che ti aiuta a gestire i profili social e a tenere in ordine il lavoro**: per artisti, band, creator, piccole attività. Un solo contenitore Docker gestisce più account: ognuno ha il suo bot Telegram, la sua personalità, i suoi dati e i suoi segreti.

> *English, in short:* a self-hosted Telegram assistant (Italian-speaking) that studies your Instagram account through the official Meta API (read-only), builds an editorial plan, keeps a pipeline of people to contact, researches opportunities and sends weekly reports. It **never posts, comments, sends messages or applies on its own**: it prepares drafts and waits for your approval. One container, many accounts, each with its own personality.

## Cosa fa
- **Parla con te su Telegram** in italiano semplice, ricorda tutto (anche dopo un riavvio) e funziona con il PC spento.
- **Studia il tuo Instagram** con le API ufficiali di Meta, in sola lettura: post, statistiche, pubblico, commenti. Importa da solo ogni giorno.
- **Fa il piano editoriale** (30 giorni), lo rinnova prima che finisca e lo propone con i bottoni Approva / Rifiuta / Cambia.
- **Ricorda di scrivere ai contatti** (locali, festival, organizzatori, clienti, partner): fino a 3 promemoria al giorno con i bottoni Fatto / Domani / Escludi, e prepara la bozza del messaggio.
- **Cerca opportunità** (concorsi, bandi, festival) con fonte e data, e manda un **report settimanale**.
- **Segue artisti simili e concorrenti** (profili pubblici professionali) e li confronta nel tempo, con grafici.
- **Usa un archivio di conoscenza** (un tuo repository Git) come memoria di lungo periodo: lo legge e propone modifiche, che si salvano solo dopo la tua approvazione.
- **Funziona in gruppo** (una band, due soci): ognuno abilitato, tutti vedono cosa fa il manager.

## Per quali account
I primi usi sono **musicali** (artisti e band): il piano editoriale, la ricerca di concorsi e festival e la classificazione dei contenuti nascono da lì. Per altri ambiti la personalità, le regole e **cosa conta come pertinente** si decidono nel profilo dell'account (`identita`, `regole_extra`, `ambito`: vedi [docs/ACCOUNTS.md](docs/ACCOUNTS.md)). Nell'archivio restano alcuni nomi storici (stati come `personale_non_gestito`): non cambiano il funzionamento.

## Cosa NON fa, mai
Non pubblica, non commenta, non scrive messaggi, non si candida, non compra e non firma niente da solo. Prepara bozze e **aspetta il tuo OK**. Instagram solo tramite API ufficiali: niente scraping, niente password, niente trucchi. Dettagli in [SECURITY.md](SECURITY.md).

## Installazione (5 minuti)
Servono: un server o PC sempre acceso con [Docker](https://docs.docker.com/engine/install/), e un servizio IA compatibile OpenAI (es. [OmniRoute](https://github.com/diegosouzapw/OmniRoute), o un provider con endpoint `/v1`).

```bash
git clone https://github.com/LuigiElleBalotta/edith.git
cd edith
./setup.sh
```

`setup.sh` prepara le cartelle, chiede indirizzo e chiave del servizio IA, avvia il contenitore e **ti guida a creare il primo account**: ti fa creare il bot su Telegram, capisce da solo chi sei (basta scrivergli «ciao»), verifica ogni dato prima di salvare e ti spiega come collegare Instagram.

Per aggiungere altri account, in qualsiasi momento (parte da solo, senza riavviare):

```bash
./manager add        # nuovo account
./manager list       # cosa c'è e cosa è collegato
./manager check      # prova Telegram, IA e Instagram di ogni account
./manager logs       # cosa sta succedendo
./manager update     # scarica la nuova versione
./manager remove nome  # mette da parte l'account (i dati non si cancellano)
```

## Documentazione
- [docs/SETUP.md](docs/SETUP.md): **la guida completa, dall'inizio alla fine** (server, servizio IA, bot, Instagram, pannello in HTTPS, aggiornamenti, problemi comuni).
- [docs/GUIDARE-L-UTENTE.md](docs/GUIDARE-L-UTENTE.md): per chi aiuta qualcuno a installarlo (anche un assistente IA): come condurlo, cosa fa chi e cosa non va mai fatto.
- [docs/PIANO-STRUMENTI.md](docs/PIANO-STRUMENTI.md): **proposta in corso**: un assistente che impara e si costruisce da solo gli strumenti e le pagine del pannello, sempre con la tua approvazione.
- [CLAUDE.md](CLAUDE.md): regole e mappa del codice per assistenti IA e per chi sviluppa.
- [docs/ACCOUNTS.md](docs/ACCOUNTS.md): più account, personalità (`profile.json`), gruppo condiviso, archivio di conoscenza, promemoria contatti.
- [docs/PANEL.md](docs/PANEL.md): il pannello web di configurazione (solo da localhost, con password).
- [docs/INSTAGRAM.md](docs/INSTAGRAM.md): collegare Instagram in sola lettura, passo per passo, con i permessi minimi.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): come è fatto, cosa gira dove, risorse usate.
- [SECURITY.md](SECURITY.md): cosa protegge cosa, rischi noti, cosa fare se un segreto è esposto.
- [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md).

## Risorse
Circa 20 MB di RAM per account a riposo, solo libreria standard di Python (nessuna dipendenza). Il browser (Chromium) parte solo quando serve leggere una pagina o disegnare un grafico, poi si chiude. Limite del contenitore: 1 GB.

## Test
```bash
cd bot && python -I -m unittest discover -s tests
python scripts/check_secrets.py
```

## Licenza
MIT, vedi [LICENSE](LICENSE). Usalo solo sui tuoi account o su quelli di chi ti ha dato il permesso.
