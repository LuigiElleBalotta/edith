# Guidare un utente nel setup (per assistenti IA e per chi aiuta)

Questa pagina è per chi **accompagna una persona** nell'installazione di EDITH: un assistente come Claude Code, o un amico tecnico. L'utente tipo sa usare il computer ma **non è per forza un esperto** di server, Meta o social. Il passo-passo vero è in [SETUP.md](SETUP.md); qui c'è *come* condurlo.

## Principi
1. **Italiano semplice, passi piccoli.** Una cosa alla volta, con il risultato atteso («dovresti vedere…»). Niente sigle senza spiegarle.
2. **Prima capisci, poi agisci.** Chiedi cosa vuole ottenere (quale profilo, per chi, che ambito) prima di toccare qualcosa.
3. **Controlla sempre il risultato.** Dopo ogni passo: `./manager check`, un `curl`, uno screenshot. Non dire «fatto» senza averlo verificato.
4. **Dì le cose come stanno.** Se un permesso è più ampio del necessario, se un passo non è andato, se non sai: dillo.
5. **L'ultima parola è sua.** Ogni azione che esce dal suo computer o dal suo server (pubblicare un repository, cambiare DNS, creare app Meta) va **proposta e confermata**.

## Cosa fa l'assistente e cosa fa l'utente
| Lo fa l'assistente (se ha accesso) | Lo fa sempre l'utente |
|---|---|
| installare, configurare Docker e `.env`, lanciare i controlli | **accedere** agli account (Meta, Instagram, aaPanel, server): password, codici di verifica, MFA |
| scrivere le configurazioni del proxy, verificare HTTPS | creare il bot con @BotFather (o incollare il codice) |
| creare le app Meta e l'utente di sistema **se l'utente è già dentro** al browser | accettare normative e condizioni (sono sue) |
| riassumere cosa ha fatto e cosa resta | decidere cosa si pubblica, a chi si scrive, cosa si compra |

## Segreti: regole che non si piegano
- **Mai chiedere una password in chat.** Se serve un accesso, l'utente lo fa da sé nella sua finestra, oppure usa una chiave SSH. L'assistente non digita mai password per l'utente.
- **Se l'utente incolla un segreto in chat** (token, chiave, password): usalo solo dove serve (file `.env` o `account.env` con permessi `600`, sul server), non scriverlo in file del progetto, in documenti, nella memoria dell'assistente o in un commit. Poi digli con calma che quel segreto ora è in una conversazione e **andrebbe cambiato**: è un consiglio, non un rimprovero.
- **Mai** nei log, negli screenshot, nei messaggi di errore riportati all'utente.
- Prima di ogni `git push`: `python scripts/check_secrets.py` e una ricerca di nomi, ID ed email dell'utente nei file e nella **storia** dei commit (un dato finito in un commit vecchio resta pubblico per sempre).
- Se compare un campo con una chiave in una pagina web, **non fare lo snapshot** del campo (ne leggerebbe il contenuto): usa uno screenshot.

## Lavorare nel browser dell'utente
- Prima di **scrivere** qualsiasi cosa: fai uno screenshot e controlla quale finestra e quale campo hanno il focus. Un errore qui può finire in un'app che non c'entra (di lavoro, di un'altra persona).
- Non toccare finestre, cartelle o servizi che non fanno parte del lavoro.
- Se un clic apre una finestra di conferma che non ti aspetti, fermati e chiedi.
- Se l'utente interrompe un'azione, **non riprovare uguale**: chiedi cosa vuole.

## Il percorso, in ordine
1. **Capire.** Per chi è l'account? Ha già un profilo Instagram professionale? Un server? Un servizio IA? Quanto vuole collegare subito?
2. **Server e Docker.** Verifica `docker --version`; clona il repository; `./setup.sh`.
3. **Servizio IA.** Indirizzo e chiave dedicata a EDITH; `./manager check`.
4. **Primo account.** Bot Telegram → «ciao» al bot → verifica. Spiega che solo lui potrà usarlo.
5. **Instagram (facoltativo).** Segui [INSTAGRAM.md](INSTAGRAM.md). Qui servono più attenzione e più pazienza: vedi sotto.
6. **Pannello web.** Prima in locale; poi, se vuole, dominio + HTTPS ([SETUP.md](SETUP.md), punto 6).
7. **Primo giorno.** Fagli scrivere al bot cosa fa, per chi, quali obiettivi. Spiega cosa fa da solo (promemoria, report) e cosa **non** fa mai (pubblicare, scrivere a nome suo).
8. **Chiusura.** Elenca cosa è stato fatto, cosa resta (backup, aggiornamenti) e cosa va cambiato (segreti passati in chat).

## Meta: dove ci si perde
- **Interfaccia che cambia.** I nomi delle voci cambiano spesso. Se un pulsante non c'è, cerca la funzione («Utenti di sistema», «Genera token», «Assegna risorse») e guarda cosa c'è davvero a schermo: non andare a memoria.
- **Permessi: il minimo.** Alla generazione del token i permessi di **scrittura** stanno accanto a quelli di lettura: un clic sbagliato crea un token che potrebbe pubblicare o scrivere messaggi. Dopo averlo generato, **verifica** i permessi del token (guida: «Verificare i permessi del token» in [INSTAGRAM.md](INSTAGRAM.md)). Se sono più ampi del necessario, **dillo** e proponi di rigenerarlo; se l'utente decide di tenerlo, è una sua scelta consapevole.
- **Portfolio con restrizioni.** Può limitare le inserzioni ma non la lettura. Non richiedere revisioni a nome suo senza il suo ok.
- **Il token si vede una volta sola.** Se si chiude la finestra, si rigenera.

## Cose che l'assistente non fa mai da solo
Pubblicare su Instagram, commentare, scrivere messaggi o candidature, comprare, firmare, cambiare DNS o proprietà di domini, creare repository pubblici, attivare il deploy automatico, dare a un contenitore l'accesso a Docker, allargare un permesso. Se serve, lo propone e aspetta il sì.

## Estensioni e lezioni: spiegarle bene
- Digli che il manager può **proporre** funzioni in più (estensioni) e regole per sé (lezioni), ma **non attiva niente da solo**: decide lui, da Telegram o dal pannello.
- Prima che approvi, fagli leggere **a quali siti si collega** e **cosa può fare**: sono le due cose che contano. Se non lo convince, **Rifiuta**; se non vuole più sentirne parlare, **Non riproporre più**.
- Per provare senza rischi: dal pannello → account → *Catalogo* → «Timer di cottura» (non si collega a nessun sito).
- Dettagli: [ESTENSIONI.md](ESTENSIONI.md).

## La Biblioteca: come spiegarla
Se l'utente ha un corso, una guida o degli appunti, può darglieli: da Telegram con `/impara` (file allegato con la didascalia) o dal pannello → *Biblioteca*. Spiega onestamente che il bot non «cambia», ma si costruisce una **memoria** che rilegge quando serve, citando la pagina; che i PDF di sole immagini non si leggono; e che i principi che ricava diventano regole **solo con il suo OK**. Ricordagli il diritto d'autore (uso proprio). Dettagli: [BIBLIOTECA.md](BIBLIOTECA.md).

## Gli esperti
Il manager può chiedere un secondo parere a consulenti (social, PR, bandi…). Spiega all'utente che sono **solo consigli**: non vedono il suo account, non possono agire, e il manager li confronta coi dati veri. Dal pannello → account → *Esperti* si spengono quelli che non servono. Dettagli: [ESPERTI.md](ESPERTI.md).

## Dopo il setup: aiutare a usarlo
- Fagli provare: «chiedi al bot di fare il piano dei prossimi 7 giorni».
- Mostra dove si cambiano personalità e regole: pannello → account → «Personalità» (vale subito).
- Spiega i promemoria dei contatti: bottoni **Fatto / Domani / Escludi**, massimo 3 al giorno.
- Ricordagli che ogni bozza ha bisogno del suo OK.
