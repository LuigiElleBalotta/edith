# Cronologia

## 0.3 — EDITH e pannello web
- Il progetto si chiama **EDITH** ed è più generico: l'ambito dell'account (`ambito`) decide cosa conta come pertinente quando si classificano i contenuti.
- **Pannello web** (Python, nessuna dipendenza, nessun JavaScript): creazione guidata di un account, personalità e regole, chiavi, verifica dei collegamenti, riavvio e messa da parte. Solo da localhost, con password; vedi [docs/PANEL.md](docs/PANEL.md).
- Pannello rifatto con Tailwind (compilato nel repo, nessun Node): pagine guidate, un testo di aiuto con esempio per ogni campo, passi numerati con barra di avanzamento, messaggi chiari, tema scuro, uso da telefono.
- Nuova pagina **Stato e registro**: risorse, stato degli account, ultime righe del registro (segreti oscurati), riavvio di tutti gli account.
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
