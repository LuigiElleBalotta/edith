# Pannello web

Un'interfaccia da browser per fare le stesse cose di `./manager`, senza toccare file o terminale. È scritta in Python con la sola libreria standard, **gira dentro il contenitore** (nessun programma in più, quasi nessuna memoria) e non usa JavaScript.

## Cosa si fa dal pannello
- **Vedere gli account:** bot, stato (attivo/fermo), Instagram, archivio, messaggi.
- **Creare un account** passo per passo: verifica il codice del bot, capisce da solo chi sei (scrivi «ciao» al bot e premi *controlla*), verifica la chiave IA e il token Instagram, genera la chiave dell'archivio.
- **Cambiare la personalità:** come ti chiama, chi è il manager, regole in più, cosa conta come pertinente, benvenuto, strumenti e lavori da spegnere. **Vale subito**, senza riavviare.
- **Chi può usarlo** (gli ID Telegram dei proprietari) e **le chiavi** (token Instagram, chiave IA propria): si scrivono ma **non si mostrano mai**. Ogni valore nuovo viene verificato prima di essere salvato.
- **Verificare i collegamenti**, **riavviare** un account, **metterlo da parte** (i dati non si cancellano).
- **Stato e registro** (come `./manager status` e `./manager logs`): memoria, CPU e spazio usati, stato di ogni account, ultime righe del registro con token e chiavi oscurati, «Riavvia tutti gli account».

Ogni campo ha sotto una riga che spiega a cosa serve, con un esempio.

- **Estensioni** (dentro ogni account): elenco, pagina di ciascuna con impostazioni e tabelle modificabili, «Da approvare» (le proposte del manager), spegni/accendi, versioni, «Esegui ora». Vedi [ESTENSIONI.md](ESTENSIONI.md).
- **Cosa ha imparato**: le lezioni del manager e le sue proposte di regole; «Non riproporre più».
- **Esperti**: accendi o spegni i consulenti che il manager può interpellare, per questo account. Vedi [ESPERTI.md](ESPERTI.md).
- **Catalogo**: estensioni già pronte, da proporre a te stesso per l'approvazione.

## Accenderlo
Si accende solo se in `.env` c'è `PANEL_PASSWORD` (almeno 12 caratteri). `./setup.sh` ne genera una e te la mostra una volta; sta anche in `.env`, dove puoi cambiarla. Dopo la modifica: `./manager restart`.

## Raggiungerlo
Il contenitore lo pubblica **solo su `127.0.0.1:8787`** del computer dove gira: da fuori non si vede. Due modi per usarlo:

1. **Tunnel SSH** (il più semplice e sicuro). Dal tuo computer:
   ```bash
   ssh -L 8787:localhost:8787 utente@tuo-server
   ```
   poi apri http://localhost:8787.
2. **Proxy HTTPS tuo** (nginx, Caddy, aaPanel…) che inoltra verso `127.0.0.1:8787`. Aggiungi il tuo dominio a `PANEL_ALLOWED_HOSTS` in `.env`, altrimenti il pannello rifiuta le richieste (è una difesa contro il DNS rebinding). Il proxy deve inviare `X-Forwarded-Proto: https`: così il cookie diventa `Secure`.

**Non pubblicarlo su Internet senza HTTPS.** Chi entra nel pannello può cambiare proprietari e chiavi di tutti gli account.

## Stile
L'aspetto usa [Tailwind CSS](https://tailwindcss.com), già compilato in `bot/app/static/panel.css` (versionato): per usare il pannello non serve Node. Per rigenerarlo vedi [bot/ui/README.md](../bot/ui/README.md). Il pannello resta senza JavaScript: il foglio di stile viene servito dal pannello stesso (`style-src 'self'`).

## Cosa non fa
- Non aggiorna il programma (`./manager update`): servirebbe dare al contenitore il controllo di Docker, cioè l'accesso root al server. Si aggiorna dal server.
- Non mostra token o chiavi già salvati (se li perdi, si rigenerano nel servizio che li ha emessi).
- Non cambia le impostazioni comuni (`.env`): servono sul server.
- Non cancella dati: «Metti da parte» sposta solo la configurazione.
- Il registro mostra solo le ultime 200 righe dall'avvio; per lo storico usa `./manager logs`.

## Sicurezza
Dettagli in [SECURITY.md](../SECURITY.md#pannello-web): password con blocco dopo 5 errori, cookie `HttpOnly` + `SameSite=Strict`, codice anti-CSRF, controllo dell'indirizzo richiesto, nessun JavaScript, `Content-Security-Policy` rigida.
