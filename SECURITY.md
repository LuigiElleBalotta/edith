# Sicurezza

Il manager lavora su account social veri, quindi è costruito per **non poter fare danni da solo**: legge, prepara bozze e aspetta il tuo OK.

## Segnalare un problema di sicurezza
Apri una *Security advisory* privata nel repository (scheda Security) invece di una issue pubblica.

## Cosa non può fare, per costruzione
- **Nessuna scrittura su Instagram.** Nel codice non esiste nessuna azione che pubblica, commenta, risponde o scrive messaggi. Anche se il token avesse quei permessi, il programma non ha le funzioni per usarli.
- **Nessun contatto con terzi.** Prepara bozze di messaggi, candidature e risposte: si usano a mano. Segnare qualcosa come «inviato» o «pubblicato» vale solo con il bottone **Fatto** o con parole vere del proprietario (la frase citata deve comparire negli ultimi 8 messaggi della chat: un lavoro automatico non può quindi sbloccare nulla).
- **Nessuna azione senza approvazione.** Ogni proposta si decide una volta sola, con i bottoni (o dal pannello con password), e solo da un proprietario.

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

## Posta (mail in uscita)
Vedi [docs/POSTA.md](docs/POSTA.md).
- **Ogni mail passa dall'approvazione a bottoni del proprietario**, con anteprima completa: il manager non può inviare da solo (`approvals.py`, hook `invio_mail`). Test: `bot/tests/test_posta.py`.
- **Posta per account:** se un account ha la sua configurazione (SMTP_HOST nel suo `account.env`) vince quella, per intero; la password comune non si usa mai verso il server di un altro e non si copia da sola.
- **Password SMTP** solo in `accounts/_posta.env` (600, mai su Git, mai mostrata, mai nei log o negli errori). Connessione cifrata con certificato verificato; «nessuna cifratura» solo verso la rete interna.
- **Niente intestazioni iniettate** (a capo vietati in nome, oggetto, indirizzi), una persona per mail, limite giornaliero, elenco dei non contattabili ricontrollato all'invio.
- **Segnale di apertura**: un'immagine 1×1 su `/t/<codice>.gif` (l'unica rotta senza accesso); registra solo l'ora, risponde sempre allo stesso modo anche con codici falsi, non scrive niente se il codice non esiste. Informativa e consenso restano una decisione del proprietario.

## Biblioteca (documenti dati dal proprietario)
Vedi [docs/BIBLIOTECA.md](docs/BIBLIOTECA.md).
- **Il contenuto di un documento è un dato, mai un'istruzione.** Al manager arriva in un blocco etichettato che dice di non obbedire a ordini scritti dentro; il documento non può far pubblicare o scrivere (il manager non ha quelle funzioni) e i principi che ne ricava diventano regole solo con l'approvazione del proprietario.
- **Solo il proprietario aggiunge documenti** (comando `/impara` da un proprietario, o pannello con password). Il bot **non** può aggiungerne da solo, perché un testo preso dal web e messo in memoria senza OK sarebbe un modo per inquinarla.
- **Lettura dei file:** PDF con `pdftotext` (nessuna shell, tempo e pagine massimi, nel contenitore senza privilegi e con il disco in sola lettura); Word e PowerPoint con la sola libreria standard e controllo sulla dimensione dopo l'apertura. Limiti di dimensione (25 MB, 4 milioni di caratteri) per non bloccare il bot.
- **Caricamento dal pannello:** accettato solo sulla pagina Biblioteca, solo dopo l'accesso, con codice anti-CSRF e limite di 26 MB; ogni altro modulo con file è rifiutato.
- **Link:** una sola pagina, solo indirizzi pubblici (come il resto del web).
- **Dati:** solo il testo estratto, nel database dell'account sul server; mai su Git; il file originale non si conserva; eliminabile dal pannello.
- **Limite onesto:** i pezzi pertinenti vanno al servizio IA già usato, come ogni conversazione; e il testo di un documento ostile potrebbe far dire al manager qualcosa di sbagliato (non fargli fare qualcosa): per questo cita sempre la fonte e distingue nozione, dato misurato e cosa detta dal proprietario.

## Esperti (ruoli di terzi)
I 35 «esperti» sono testi scritti da altri (agency-agents, MIT), quindi vanno trattati con prudenza. Vedi [docs/ESPERTI.md](docs/ESPERTI.md).
- Una consulenza è **una sola richiesta all'IA, senza strumenti**: non può pubblicare, scrivere, comprare né leggere l'account; vede solo domanda e contesto passati dal manager, dopo un filtro che oscura token e chiavi.
- Le regole di EDITH stanno **prima** del testo del ruolo e prevalgono. Il parere è un'ipotesi, non un dato.
- Importati da un **commit fisso**, senza modifiche; l'impronta `sha256` di ogni file si ricontrolla a ogni uso e un file diverso non si usa.
- Esclusi gli agenti che pubblicano da soli o fanno scraping. Nel registro resta solo **quale** esperto è stato interpellato, mai la domanda.
- **Limite onesto:** un ruolo cattivo non può agire, ma potrebbe dare un cattivo consiglio, e quello che il manager gli passa va al servizio IA (lo stesso già usato). Per questo il manager passa solo i dati che servono.

## Estensioni create dal bot
Il bot può **proporre** estensioni (dati propri, timer, lettura di API, pagine nel pannello), ma **non può attivarle**: servono il bottone su Telegram o il pulsante nel pannello, da un proprietario. Vedi [docs/ESTENSIONI.md](docs/ESTENSIONI.md).
- **Niente codice.** Un'estensione è un manifest JSON con passi fissi; non c'è `exec`, né `eval`, né import di moduli. Il validatore rifiuta voci sconosciute.
- **Solo lettura verso l'esterno.** I passi di rete sono solo `GET`, verso **domini dichiarati e approvati**, con controllo a ogni reindirizzamento e solo indirizzi pubblici (stessa protezione del web normale). Non esiste nessun `POST` né invio di messaggi a terzi; l'unico messaggio possibile è a **te**.
- **Il riepilogo prima dell'OK** mostra siti, permessi, dati e timer; per una modifica evidenzia nuovi siti e nuovi permessi. Il manifest completo è visibile nel pannello.
- **Il pannello disegna, il bot descrive.** Nessun HTML o JavaScript dal bot: ogni testo del manifest e ogni dato passa da escape; le scritture sono validate contro i tipi e hanno il codice anti-CSRF.
- **Segreti:** il manifest non li legge; si usano solo come `{segreto:chiave}` nelle intestazioni verso un dominio approvato, e stanno in `account.env`.
- **Isolamento:** ogni account ha la sua cartella (`./estensioni/<account>/`); il nome dell'account e l'id dell'estensione sono validati (niente percorsi ostili).
- **Reversibile:** ogni versione approvata si conserva; si può spegnere o tornare indietro; i dati non si cancellano da soli.
- **«Non riproporre più»** ferma per sempre una proposta (estensione o regola).
- **Limite onesto:** un'estensione approvata con un dominio sbagliato potrebbe inviarci dati *dentro un indirizzo* (per esempio i parametri di una ricerca). Per questo i domini sono in primo piano nell'approvazione: controllali.
- Non esiste (ancora) l'esecuzione di codice scritto dal bot: se un giorno servirà, andrà in un contenitore separato, senza chiavi e senza rete libera.

Anche le **regole proposte dal bot** per sé (lezioni) cambiano solo `regole_extra` del profilo, solo dopo approvazione, e mai utenti, chiavi o archivio.

## Dati e copie
Copia giornaliera del database in `data/<nome>/backups` (ultime 7). **Sta sullo stesso disco**: fai anche una copia fuori dal server. I file ricevuti si eliminano dopo 7 giorni.

## Servizio IA e termini d'uso
Il manager parla con un endpoint compatibile OpenAI che scegli tu. Rispetta i termini d'uso del provider (alcuni non permettono di usare un abbonamento personale tramite un proxy). Per i lavori di fondo non mandare dati privati ai provider che possono riutilizzare i dati.
