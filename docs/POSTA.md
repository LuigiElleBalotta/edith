# Posta: mail ai contatti, sempre con il tuo OK

Il manager può **preparare** mail per i contatti da scrivere (locali, organizzatori, agenzie). **Non ne manda mai una da solo**: la vedi per intero su Telegram e parte solo se premi «Approva».

## Configurarla (una volta, dal pannello)
1. Pannello → **Posta**.
2. Inserisci server SMTP, porta, protezione (di solito STARTTLS sulla 587), nome utente, **password**, indirizzo da cui partono le mail (per esempio `info@tuodominio.it`).
3. Premi **Salva**, poi **Invia la mail di prova** verso un tuo indirizzo. Se qualcosa non va, il pannello dice cosa (password, certificato, porta…).

Le impostazioni valgono per **tutti gli account**; ogni account cambia solo il nome del mittente. La password sta solo nel file `accounts/_posta.env` sul server (permessi 600, mai su Git) e il pannello non la mostra mai. Finché la posta non è configurata, il manager non ha gli strumenti per le mail.

## Come lavora il manager
- `contatto_aggiungi`: aggiunge un contatto. Se manca anche **un solo dato** (nome, tipo, zona, canale, email/telefono/handle secondo il canale, link della fonte, priorità, data della prima scrittura) **non salva e te lo chiede**. Non inventa mai i dati.
- `mail_proponi`: prepara la mail (una persona, oggetto, testo fino a 2500 caratteri). Crea la proposta con i bottoni; **la mail non parte**.
- `mail_registro`: le ultime mail inviate e se risultano aperte.
- `mail_non_contattare`: mette un indirizzo nell'elenco di chi non va più contattato (da lì nessuna mail).
- `mail_stato`: quante ne sono partite oggi e il limite.

## Sicurezza
- **Approvazione per ogni mail**, con anteprima completa. Un'eventuale mail già scritta a quell'indirizzo negli ultimi 14 giorni compare come avviso.
- **Una persona per mail**, mai in copia. Nome, oggetto e indirizzi non possono contenere a capo (niente intestazioni iniettate).
- **Limite giornaliero** (predefinito 20, cambiabile) e **elenco degli indirizzi da non contattare**, ricontrollati al momento dell'invio.
- **Connessione cifrata con certificato verificato.** «Nessuna cifratura» è ammessa solo verso `localhost` o indirizzi della rete interna.
- In ogni mail c'è una riga per smettere di ricevere (e l'intestazione `List-Unsubscribe`).
- Nel registro del programma non finiscono né password né testi delle mail; l'archivio delle mail inviate sta nel database dell'account sul server.

## Il segnale di apertura («pixel»)
Se nel pannello hai messo l'**indirizzo pubblico** (`https://…`) e lasci acceso «Segui le aperture», ogni mail contiene un'immagine invisibile di 1 pixel servita dal pannello (`/t/<codice>.gif`, l'unica pagina senza accesso). Quando viene caricata si registra **solo l'ora**: nessun IP, nessun programma di posta. Il manager può dirti quali mail risultano aperte.

Da sapere:
- **È indicativo**: Apple Mail, Gmail e altri aprono le immagini da soli (o le tengono in cache), quindi «aperta» non vuol dire «letta», e a volte l'apertura non arriva. Non è una prova.
- **Privacy:** nell'Unione Europea il tracciamento delle aperture richiede, in teoria, un'informativa (e talvolta il consenso). Dichiararlo o no è una scelta tua; il programma non aggiunge avvisi da solo. Per spegnerlo togli la spunta in «Posta».

## Messaggi privati (DM) su Instagram
Il manager **prepara solo il testo** del messaggio (come bozza da approvare); lo mandi tu a mano. Con le API ufficiali di Meta non si può scrivere per primi a chi non ti conosce, e il repository di alcune band vieta all'IA i DM.
