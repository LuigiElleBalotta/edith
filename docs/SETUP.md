# Guida completa: dall'inizio alla fine

Questa guida porta da «ho un server» a «EDITH lavora per me», con il pannello web raggiungibile in HTTPS. Si può fare in un'ora circa. Ogni parte rimanda alla guida di dettaglio.

Se ti fa guidare un assistente (come Claude Code), leggete insieme anche [GUIDARE-L-UTENTE.md](GUIDARE-L-UTENTE.md): spiega cosa fa lui, cosa fai tu, e cosa non deve mai chiederti.

## 0. Cosa serve
| Cosa | A cosa serve | Obbligatorio |
|---|---|---|
| Un server o PC sempre acceso, con Docker | fa girare EDITH (circa 20 MB di RAM per account) | sì |
| Un servizio IA compatibile OpenAI (`/v1`) | il «cervello»: [OmniRoute](https://github.com/diegosouzapw/OmniRoute) o un provider | sì |
| Un account Telegram | per creare un bot per ogni account e parlarci | sì |
| Un account Instagram professionale + Pagina Facebook + app Meta | per leggere statistiche e post | no, si può aggiungere dopo |
| Un dominio e un proxy HTTPS | per usare il pannello web da fuori casa | no: basta un tunnel SSH |
| Un repository Git privato | l'«archivio di conoscenza» dell'account | no |

## 1. Installare
```bash
git clone https://github.com/LuigiElleBalotta/edith.git
cd edith
./setup.sh
```
`setup.sh` crea le cartelle, chiede indirizzo e chiave del servizio IA, genera la **password del pannello** (te la mostra una volta; sta anche in `.env`), avvia il contenitore e ti guida a creare il primo account.

Il contenitore usa l'immagine `ghcr.io/luigielleballotta/edith:latest`. Se vuoi costruirla tu: `docker compose build`.

## 2. Il servizio IA
EDITH parla con un servizio **compatibile OpenAI**: serve l'indirizzo (finisce con `/v1`) e una chiave.
- Con OmniRoute: crea una chiave dedicata per EDITH (così la puoi revocare da sola) e usa l'indirizzo del tuo OmniRoute.
- Modelli: in `.env` ci sono `MODEL_NORMAL` (chat), `MODEL_REASON` (piani e analisi), `MODEL_LIGHT` (lavori di fondo). Metti i nomi che il tuo servizio espone.
- Ogni account può avere una **chiave propria** (pannello → account → «Chiavi e collegamenti»). Se non la metti usa quella comune.
- Verifica: `./manager check` deve dire `✓ Intelligenza artificiale`.

## 3. Il bot Telegram
Lo crea la procedura guidata, ma a mano è così:
1. Su Telegram scrivi a **@BotFather**, manda `/newbot`, scegli nome e username (deve finire con `bot`).
2. Copia il **codice** che ti dà. È come una password: non incollarlo in chat pubbliche, in issue o nel repository.
3. Incollalo nella procedura guidata (`./manager add` o pannello → «Nuovo account»).
4. Scrivi «ciao» al bot: così EDITH capisce chi sei e ti abilita come proprietario. Solo i proprietari possono usarlo; gli altri vengono ignorati.

Per aggiungere un socio o un collaboratore: scrive al bot, tu rispondi al suo messaggio con `/abilita`.

## 4. Instagram (facoltativo, solo lettura)
Segui [INSTAGRAM.md](INSTAGRAM.md): app Meta, utente di sistema, permessi minimi, token. È la parte più lunga (circa 15 minuti) e quella dove è più facile sbagliare un permesso: la guida ha una tabella e una sezione «Verificare i permessi del token».

## 5. Il pannello web
Parte da solo se in `.env` c'è `PANEL_PASSWORD`. Di base è raggiungibile **solo dal computer dove gira**: `http://localhost:8787`. Da un altro computer, con un tunnel:
```bash
ssh -L 8787:localhost:8787 utente@tuo-server
```
Per usarlo da un indirizzo tuo con HTTPS, vedi il punto 6.

## 6. Pannello in HTTPS su un tuo dominio
Il pannello cambia proprietari e chiavi: **non metterlo mai su Internet senza HTTPS**.

1. **DNS.** Crea un record `A` (es. `edith.tuodominio.it`) verso l'IP del server.
2. **Proxy inverso.** Qualsiasi proxy va bene (nginx, Caddy, aaPanel…). Deve inoltrare a `http://127.0.0.1:8787`, mandare l'intestazione `Host` originale e `X-Forwarded-Proto: https` (così il cookie diventa `Secure`).
   - *aaPanel:* Sito → «Progetto proxy inverso» → dominio `edith.tuodominio.it`, URL di destinazione `http://127.0.0.1:8787`, «Invia dominio» = `$http_host`. Poi, nel sito, scheda **SSL → Let's Encrypt** (verifica con file) e attiva **Forza HTTPS**. Se non trovi l'interruttore, aggiungilo dal file di configurazione del sito: un redirect `301` da `http` a `https`.
   - *Caddy:* `edith.tuodominio.it { reverse_proxy 127.0.0.1:8787 }` (HTTPS e redirect sono automatici).
3. **Indirizzo ammesso.** In `.env` metti il dominio in `PANEL_ALLOWED_HOSTS`, poi ricrea il contenitore:
   ```
   PANEL_ALLOWED_HOSTS=edith.tuodominio.it,localhost,127.0.0.1
   ```
   ```bash
   docker compose up -d
   ```
   Senza questo il pannello risponde `421 Indirizzo non ammesso` (è la difesa contro il DNS rebinding).
4. **Prova:**
   ```bash
   curl -sI http://edith.tuodominio.it/login | head -3     # deve essere 301 verso https
   curl -sI https://edith.tuodominio.it/login | head -3    # deve essere 200
   ```
   Poi apri l'indirizzo nel browser e accedi con `PANEL_PASSWORD`.

## 7. Uso quotidiano
| Voglio | Comando | Dal pannello |
|---|---|---|
| vedere cosa c'è | `./manager list` | pagina iniziale |
| controllare i collegamenti | `./manager check` | account → «Verifica i collegamenti» |
| vedere cosa succede | `./manager logs` | «Stato e registro» |
| riavviare | `./manager restart` | «Riavvia» |
| aggiungere un account | `./manager add` | «+ Nuovo account» |
| mettere da parte un account | `./manager remove nome` | account → «Metti da parte» |
| aggiornare | `./manager update` | **non dal pannello** (serve l'accesso a Docker) |

## 8. Aggiornare, copiare i dati, ripartire
- **Aggiornare:** `./manager update` (scarica l'immagine nuova e riavvia). I dati stanno in `./data`, non nel contenitore: non si perdono.
- **Backup:** copia le cartelle `./data` e `./accounts` (contengono database e segreti: tienile in un posto privato). Non finiscono mai su Git.
- **Spostare su un altro server:** copia `.env`, `./data`, `./accounts`, poi `./setup.sh` e `docker compose up -d`.

## 9. Se qualcosa non va
| Sintomo | Cosa controllare |
|---|---|
| Il bot non risponde | `./manager logs`; Telegram → `./manager check`; sei tra i proprietari? |
| «Telegram non accetta questo codice» | il codice è stato copiato intero? Rigeneralo da @BotFather (`/token`) |
| Errori dell'IA / 403 sul modello | la chiave è valida? Il servizio espone quel modello? Controlla `MODEL_*` in `.env` |
| Instagram «non ha permesso» | vedi [INSTAGRAM.md](INSTAGRAM.md), sezione «Se qualcosa non va» |
| Pannello: «Indirizzo non ammesso» (421) | manca il dominio in `PANEL_ALLOWED_HOSTS` |
| Pannello: login che non tiene | il proxy non manda `X-Forwarded-Proto: https`, oppure stai usando `http` |
| Pannello bloccato | 5 password sbagliate = 5 minuti di pausa |
| Un segreto è finito dove non doveva | revocalo subito nel servizio che l'ha emesso, poi rigeneralo: vedi [SECURITY.md](../SECURITY.md) |
