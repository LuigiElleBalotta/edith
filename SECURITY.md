# Sicurezza

Il manager lavora su account social veri, quindi è costruito per **non poter fare danni da solo**: legge, prepara bozze e aspetta il tuo OK.

## Segnalare un problema di sicurezza
Apri una *Security advisory* privata nel repository (scheda Security) invece di una issue pubblica.

## Cosa non può fare, per costruzione
- **Nessuna scrittura su Instagram.** Nel codice non esiste nessuna azione che pubblica, commenta, risponde o scrive messaggi. Anche se il token avesse quei permessi, il programma non ha le funzioni per usarli.
- **Nessun contatto con terzi.** Prepara bozze di messaggi, candidature e risposte: si usano a mano. Segnare qualcosa come «inviato» o «pubblicato» vale solo con il bottone **Fatto** o con parole vere del proprietario (la frase citata deve comparire negli ultimi 8 messaggi della chat: un lavoro automatico non può quindi sbloccare nulla).
- **Nessuna azione senza approvazione.** Ogni proposta si decide una volta sola, con i bottoni, e solo da un proprietario.

## Chi può usarlo
- Solo i proprietari dell'account (ID Telegram in `account.env`, più chi un proprietario abilita con `/abilita`). Gli altri sono ignorati in silenzio e registrati (`accesso_negato`).
- Nei gruppi risponde solo nel gruppo registrato con `/gruppo`; gli altri gruppi sono ignorati. Con la privacy di Telegram attiva (consigliato) riceve solo menzioni, risposte e comandi.
- Il testo che arriva da siti web, commenti, file e dall'archivio di conoscenza è un **dato**, mai un'istruzione: non può cambiare le regole del manager.

## Segreti
- Mai nel codice né nel repository. Stanno in `.env` (comuni) e in `accounts/<nome>/account.env` (per account), con permessi `600`. `.env.example` ha solo segnaposto.
- I messaggi d'errore e i registri non contengono token, chiavi o intestazioni di autorizzazione (c'è un test). Le chiavi si chiedono in modo nascosto.
- `scripts/check_secrets.py` gira a ogni push (CI) e cerca token Telegram, token Meta, chiavi API, chiavi private. Installalo anche come controllo prima del commit: `ln -s ../../scripts/check_secrets.py .git/hooks/pre-commit`.
- Se un segreto finisce in un posto sbagliato (chat, log, commit): **cambialo subito**, non basta cancellarlo.
  - Bot Telegram: @BotFather → `/revoke`, poi aggiorna `account.env`.
  - Token Instagram: Business Suite → Utenti di sistema → *Revoca token*, poi rigenera.
  - Chiave IA: revocala dal servizio che l'ha emessa.
  - Chiave dell'archivio: elimina la *Deploy key* dal repository e rigenera con `./manager add`.

## Pannello web
- Spento finché non c'è `PANEL_PASSWORD` (almeno 12 caratteri). La password sta in `.env` e non viene mai mostrata; il confronto è a tempo costante e dopo 5 errori il login si blocca per 5 minuti.
- Il compose lo pubblica **solo su `127.0.0.1`**: da fuori serve un tunnel SSH o un proxy HTTPS tuo. Non esporlo in chiaro su Internet.
- Sessione in cookie `HttpOnly` + `SameSite=Strict` (`Secure` dietro HTTPS), codice anti-CSRF in ogni modulo, controllo dell'indirizzo richiesto contro il DNS rebinding (`PANEL_ALLOWED_HOSTS`), nessun JavaScript e `Content-Security-Policy` che blocca tutto il resto (solo il foglio di stile del pannello, `style-src 'self'`).
- Il registro mostrato nel pannello oscura i token e le chiavi noti e i modelli comuni (codice bot Telegram, Bearer); resta in memoria, non su disco. L'aggiornamento del programma non è possibile dal pannello, apposta: niente accesso a Docker.
- I segreti si **scrivono ma non si leggono**: i campi dei token restano vuoti e dicono solo se c'è un valore. Ogni token nuovo viene verificato prima di essere salvato.
- Chi entra nel pannello può cambiare personalità, proprietari e chiavi di tutti gli account: trattalo come l'accesso al server.

## Contenitore
Utente non-root, filesystem in sola lettura, nessuna capability, `no-new-privileges`, nessuna porta esposta, limiti di memoria (1 GB), CPU e processi. Il bot parla solo in uscita (Telegram, servizio IA, Meta, siti pubblici).

## Più account nello stesso contenitore: cosa significa
Ogni account ha database, bot, regole e chiavi propri e **non vede mai i dati di un altro** (il codice li tiene in oggetti distinti). Ma gli account **condividono processo e utente di sistema**: se qualcuno trovasse un errore di esecuzione di codice nel programma, potrebbe leggere i segreti di tutti. Se i tuoi account appartengono a persone diverse che non si fidano tra loro, usa **un'installazione separata per ciascuno**.

## Instagram
- Solo API ufficiali Meta, solo lettura. Nessun login con password, nessuno scraping, nessun cookie.
- Il token ideale ha solo `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement` (guida in [docs/INSTAGRAM.md](docs/INSTAGRAM.md)). Per leggere i commenti Meta richiede `instagram_manage_comments`, che permette anche di scrivere: il manager non lo fa mai, ma se vuoi evitare anche il rischio teorico, non concederlo.
- Il permesso di Meta riguarda l'**intero** account: il confine («solo contenuti musicali / professionali») lo impone il programma. I contenuti `personale_non_gestito` o `da_classificare` sono bloccati: nessuna lettura di dettaglio, nessuna statistica, nessuna azione (`guard.py`, con test).
- Commenti: si salvano testo, data e mi piace, **mai i nomi** di chi scrive. Storie: solo numeri. Pubblico: solo totali per fascia.

## Lettura del web e browser
- Solo http/https verso indirizzi **pubblici**; ogni reindirizzamento viene ricontrollato. Rete interna e indirizzi di servizio cloud sono bloccati. Limite noto: nessuna protezione contro il cambio di DNS tra controllo e richiesta.
- Il browser (Chromium) parte solo quando serve, con ambiente vuoto, profilo nuovo cancellato subito, senza cookie né login. Il servizio ascolta solo su `127.0.0.1` con un token casuale generato all'avvio e mai scritto su disco.
- **Compromesso della modalità `internal` (predefinita):** Chromium gira senza la sua sandbox interna (dentro un contenitore non è disponibile) e **nello stesso contenitore** del bot. Una pagina ostile che sfruttasse un difetto di Chromium potrebbe, in teoria, leggere i file degli account. Chi vuole l'isolamento completo usa `BROWSER_MODE=external` (secondo contenitore senza segreti, stessa immagine) oppure `off`. Tieni l'immagine aggiornata (`./manager update`): Chromium si aggiorna con lei.
- I grafici: il modello fornisce solo tipo e numeri; l'SVG lo scrive il nostro codice (testo neutralizzato) e il browser accetta solo SVG senza script, link, immagini o `foreignObject`.

## Archivio di conoscenza
Si leggono solo file di testo. Mai letti né scritti: `secrets/`, `.env`, chiavi, `.git`, `.github`, `ops/gateway`, `ops/bridge` (vale anche per ricerca ed elenco). Le modifiche passano da anteprima + approvazione e vanno su un ramo separato (`manager`). La *Deploy key* di GitHub non si può limitare a un ramo: proteggi `main` con le regole del repository.

## Lavori automatici
Report, ricerca opportunità e piano partono da soli ma fanno solo due cose: leggere (Instagram, web) e scrivere al proprietario su Telegram, in silenzio. Limiti: 20 attività in attesa (entro 60 giorni), 5 domande in coda, una domanda ogni 20 ore e solo tra le 10 e le 20, al massimo 3 promemoria contatti al giorno. Se un lavoro fallisce 3 volte nella settimana rinuncia. `/pausa` ferma tutto.

## Dati e copie
Copia giornaliera del database in `data/<nome>/backups` (ultime 7). **Sta sullo stesso disco**: fai anche una copia fuori dal server. I file ricevuti si eliminano dopo 7 giorni.

## Servizio IA e termini d'uso
Il manager parla con un endpoint compatibile OpenAI che scegli tu. Rispetta i termini d'uso del provider (alcuni non permettono di usare un abbonamento personale tramite un proxy). Per i lavori di fondo non mandare dati privati ai provider che possono riutilizzare i dati.
