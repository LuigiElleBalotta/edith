# Cronologia

## 0.6 — Biblioteca
- **Gruppo Telegram:** nel gruppo condiviso risponde ai messaggi di chi è abilitato (non a quelli rivolti ad altre persone; modalità «solo menzioni» a scelta); se la privacy di Telegram gli nasconde i messaggi lo avvisa una volta nel gruppo e lo dice in `/stato`. Con un gruppo scrive solo lì; in privato risponde solo in privato.
- **Mail inviate** visibili nel pannello (account → Posta): destinatario, data, testo e aperture.
- **Posta propria per account**: ogni account può avere la sua posta (account → Posta) e quella vince sulla comune, per intero e senza mescolare password. L'indirizzo del foglio di stile cambia a ogni aggiornamento, così il browser non resta con la grafica vecchia.
- **Posta**: pagina «Posta» nel pannello (server SMTP, password mai mostrata, bottone di prova); strumenti `mail_proponi` (la mail parte solo dopo l'approvazione a bottoni), `mail_registro`, `mail_stato`, `mail_non_contattare`; limite giornaliero, elenco dei non contattabili, riga per disiscriversi, segnale di apertura facoltativo (`/t/<codice>.gif`: solo l'ora). `contatto_aggiungi`: se manca un dato lo chiede, non inventa. Vedi [docs/POSTA.md](docs/POSTA.md).
- **Voce di E.D.I.T.H.** per il bot, di serie (scelta «Come parla»: E.D.I.T.H., neutra o descritta da te). Le regole e l'onestà valgono più dello stile.
- **Pannello a tutta larghezza** (menu laterale, due colonne, moduli) e tema del visore; screenshot nel README.
- **Archivio per tutti, dal sito.** Ogni account può avere un archivio di note e tabelle senza Git: pagina **Archivio** del pannello (crea l'archivio interno, scrivi e modifica le note; la versione precedente resta in `.versioni/`). Chi ha già un repository Git può collegarlo dal sito (indirizzi SSH validati, chiave di sola scrittura sul repository generata dal pannello e mai mostrata). Il manager usa gli stessi strumenti `kb_*` in entrambi i casi e le sue modifiche passano sempre dall'approvazione.
- Il manager parla di ciò che ha studiato come di cose che sa, senza citare pagine. Lo studio riprova una volta se l'IA dà una risposta vuota e non fallisce per un solo blocco. Il pannello chiude con una risposta chiara anche i rifiuti prima della lettura (cadeva a intermittenza la connessione).
- **Biblioteca**: il manager studia i documenti che gli dai (PDF, Word, PowerPoint, testo, Markdown, pagine web) da Telegram (`/impara`) o dal pannello. Il testo viene diviso in pezzi con titolo e pagina e indicizzato (SQLite FTS5); a ogni messaggio il sistema cerca da solo i pezzi pertinenti e li mette nel contesto, con l'avviso che sono nozioni di terzi; il manager cita fonte e pagina.
- **Studio in background**: riassunto e principi operativi, che diventano lezioni (le regole solo con il tuo OK).
- I ruoli dei 35 esperti sono nella stessa ricerca automatica. Strumenti `biblioteca_cerca` e `biblioteca_elenco` (il bot non può aggiungere documenti).
- Pannello: pagina **Biblioteca** (carica file fino a 25 MB, link, testo; elenco, studia di nuovo, elimina). Nell'immagine c'è `poppler-utils` per i PDF. Vedi [docs/BIBLIOTECA.md](docs/BIBLIOTECA.md).

## 0.5 — Esperti
- **Esperti**: 35 ruoli di consulenza (social, contenuti, PR, bandi, vendite, pubblicità, traduzioni…) dal progetto open source [agency-agents](https://github.com/msitarzewski/agency-agents) (MIT), importati senza modifiche da un commit fisso, con impronta ricontrollata a ogni uso. Il manager li interpella per un parere (`esperti_elenco`, `esperto_consulta`); sono **solo consulenza**: nessuno strumento, nessuna azione, nessun accesso all'account, regole di EDITH prima del testo del ruolo, token oscurati. Vedi [docs/ESPERTI.md](docs/ESPERTI.md).
- Pannello: pagina **Esperti** per accenderli e spegnerli per account (`esperti_spenti` nel profilo).
- Lo script `scripts/importa_esperti.py` riscarica l'elenco scelto (esclusi gli agenti che pubblicano da soli o fanno scraping).

## 0.4 — Estensioni e lezioni
- **Estensioni**: il bot può proporre funzioni in più (dati propri con pagina modificabile, timer, lettura di API, programmi), descritte da un manifest e **sempre approvate** dal proprietario da Telegram o dal pannello. Vivono fuori dal contenitore (`./estensioni`). Vedi [docs/ESTENSIONI.md](docs/ESTENSIONI.md).
- **Lezioni**: il bot annota cosa impara e propone regole per sé (con il prima e il dopo); cambiano solo `regole_extra` e solo dopo l'OK. Le rifiutate si riproporranno dopo qualche giorno; **«Non riproporre più»** le ferma per sempre.
- Pannello: pagine delle estensioni (impostazioni, tabelle modificabili, esegui ora, spegni, versioni), «Da approvare», «Cosa ha imparato», **Catalogo** (ricettario, timer di cottura, meteo, con impronta controllata).
- Piano e decisioni: [docs/PIANO-STRUMENTI.md](docs/PIANO-STRUMENTI.md). Non c'è ancora l'esecuzione di codice scritto dal bot.

## 0.3 — EDITH e pannello web
- Il progetto si chiama **EDITH** ed è più generico: l'ambito dell'account (`ambito`) decide cosa conta come pertinente quando si classificano i contenuti.
- **Pannello web** (Python, nessuna dipendenza, nessun JavaScript): creazione guidata di un account, personalità e regole, chiavi, verifica dei collegamenti, riavvio e messa da parte. Solo da localhost, con password; vedi [docs/PANEL.md](docs/PANEL.md).
- Pannello rifatto con Tailwind (compilato nel repo, nessun Node): pagine guidate, un testo di aiuto con esempio per ogni campo, passi numerati con barra di avanzamento, messaggi chiari, tema scuro, uso da telefono.
- Nuova pagina **Stato e registro**: risorse, stato degli account, ultime righe del registro (segreti oscurati), riavvio di tutti gli account.
- Documentazione: guida completa [docs/SETUP.md](docs/SETUP.md), guida per chi accompagna un utente [docs/GUIDARE-L-UTENTE.md](docs/GUIDARE-L-UTENTE.md), [CLAUDE.md](CLAUDE.md) e [AGENTS.md](AGENTS.md); in [docs/INSTAGRAM.md](docs/INSTAGRAM.md) come verificare i permessi del token.
- Le modifiche al profilo valgono subito, senza riavviare.
- OmniRoute 3.8.53: provato con tutti e tre i modelli su entrambi gli account.

## 0.2 — Un contenitore, più account
- **Un solo contenitore** per tutti gli account (prima: uno per account, più un browser a parte). Ogni account ha ancora dati, bot Telegram, regole e chiavi separati.
- **Browser integrato** nell'immagine: Chromium parte solo quando serve. Modalità `internal`, `external` (contenitore isolato) o `off`.
- **Procedura guidata** (`./setup.sh`, `./manager add`): crea l'account passo per passo, verifica ogni dato prima di salvare, capisce da solo chi è il proprietario, genera la chiave dell'archivio. Un account nuovo parte da solo, senza riavvii.
- `./manager list | check | remove | logs | update`.
- Il prompt non è più legato a una persona: nome e personalità arrivano da `profile.json` (`proprietario`, `identita`, `regole_extra`).
- Strumenti e campi con nomi neutri (`chiedi_al_proprietario`, `frase_del_proprietario`); i dati esistenti vengono migrati da soli.
- Un account scritto male non ferma gli altri; chi va in errore si riprova con pausa crescente.
- Repository pubblico: documenti generici, GitHub Actions (test, controllo segreti, immagine su ghcr.io, deploy facoltativo), `scripts/check_secrets.py`.

## 0.1 — Il manager
- Bot Telegram con memoria persistente, autorizzazione per ID, pausa, ricezione file e foto, scelta del modello (normale / ragionamento / leggero).
- Strumenti di sola lettura: archivio, Instagram dal vivo, statistiche di account e post, storico importato, web (ricerca, lettura, browser), grafici.
- Importazione quotidiana da Instagram (profilo, post, statistiche, pubblico, commenti) e classificazione automatica dei contenuti; blocco sui contenuti non gestiti.
- Piano editoriale a 30 giorni (`/piano`, `/calendario`) con rinnovo automatico e approvazione a bottoni.
- Agenda autonoma: domande al proprietario al momento giusto, attività programmate, revisione interna settimanale, report settimanale e ricerca opportunità.
- Contatti: pipeline (da scrivere, in attesa, risposto, escluso), promemoria giornalieri con bottoni, follow-up programmato, bozze da approvare.
- Concorrenti e artisti simili: monitoraggio nel tempo e confronto con grafici.
- Archivio di conoscenza (repository Git): lettura, studio quotidiano, modifiche solo con approvazione, ramo separato.
- Più proprietari e gruppo condiviso (`/gruppo`, `/abilita`, `/disabilita`).
- Test automatici, copie giornaliere del database, pulizia dei file.
