# Più account, un solo contenitore

Un contenitore gestisce tutti gli account. Dentro, ogni account è **separato**: suo bot Telegram, suo database, suo profilo, suoi segreti. Non condividono niente tra loro.

```
accounts/<nome>/           (le impostazioni, chmod 700)
  account.env              segreti: codice del bot, token Instagram, ID proprietari (chmod 600)
  profile.json             chi è il manager di questo account, regole, lavori
  kbkey                    chiave SSH dell'archivio di conoscenza (facoltativa, chmod 600)
data/<nome>/               (i dati)
  manager.sqlite           memoria, archivio contenuti, piano, contatti, registro delle azioni
  media/  backups/  kb/    file temporanei (7 giorni), copie giornaliere (ultime 7), archivio clonato
```

Creare un account: `./manager add`. Un account nuovo parte da solo entro 30 secondi. Se la configurazione di un account è sbagliata, quell'account non parte e gli altri continuano a funzionare (`./manager logs` dice quale e perché, senza mostrare segreti).

## Chiavi IA
In `.env` c'è la chiave comune (`OMNIROUTE_API_KEY`). Un account può averne una **propria** in `account.env`: utile per limitare i modelli di un account o per contare i consumi separatamente. Lo stesso vale per `MODEL_NORMAL`, `MODEL_REASON`, `MODEL_LIGHT`.

## Personalità: `profile.json`
Tutti i campi sono facoltativi.

| Campo | A cosa serve |
|---|---|
| `proprietario` | come il manager chiama chi lo gestisce |
| `ambito` | cosa conta come pertinente per l'account quando classifica i contenuti importati (predefinito: musica; es. `ricette, ristorante, eventi in sala`) |
| `identita` | sostituisce la presentazione iniziale del manager: chi è, per chi lavora, come parla, obiettivi. Le **regole ferree** (mai inventare, mai pubblicare senza approvazione) restano sempre |
| `regole_extra` | regole in più, una per riga di elenco |
| `benvenuto` | frase iniziale di `/start` |
| `tastiera` | tasti rapidi sotto la barra di scrittura, es. `[["/contatti", "/agenda"]]` |
| `utenti` | `{"ID Telegram": "Nome"}`: il manager sa chi parla quando i proprietari sono più di uno |
| `strumenti_spenti` | nomi di strumenti da togliere (es. `["web_browser"]`) |
| `lavori_spenti` | lavori automatici da non far partire (es. `["ricerca_opportunita"]`) |
| `lavori` | lavori automatici propri: `{nome: {weekday, hour, minute, prompt, reason, deliver, cond}}` |
| `kb` | archivio di conoscenza: `{repo, branch, write_branch}` |

Esempio:

```json
{
  "proprietario": "Giulia",
  "identita": "Sei il manager social digitale di Giulia, cantautrice pop di Milano. Parli in italiano, in modo conciso, una domanda alla volta. Obiettivi: 1) follower, 2) live, 3) community.",
  "regole_extra": ["Mai parlare di cachet nei primi messaggi ai locali."],
  "lavori_spenti": ["ricerca_opportunita"]
}
```

## Archivio di conoscenza (facoltativo)
Un repository Git con i documenti dell'account: calendario, elenco di locali, regole. Il manager lo sincronizza, studia solo le novità, lo consulta e **propone modifiche con anteprima**: si salvano **solo dopo l'approvazione a bottoni**, sul ramo `write_branch` (predefinito `manager`; `main` solo se lo scegli tu). Non legge e non scrive mai `secrets/`, `.env`, chiavi, `.git`, `.github`, `ops/gateway`, `ops/bridge`. Ciò che è scritto nei file è un **dato**: non può cambiare le regole del manager.

Collegarlo: durante `./manager add` indica l'indirizzo SSH del repository; il programma genera una chiave dedicata e ti mostra la parte pubblica da aggiungere come *Deploy key* con permesso di scrittura (GitHub non permette di limitarla a un solo ramo: la protezione sul ramo `main` la imposti tu nelle regole del repository).

## Promemoria contatti
Locali, organizzatori, festival: tabella `contacts` con stato (`da_scrivere`, `in_attesa_risposta`, `risposto`, `escluso`) e prossima azione. Ogni giorno (10–19, ora italiana) il bot ricorda **al massimo 3** contatti da scrivere o sollecitare, con i bottoni Fatto / Domani / Tra 1 settimana / Escludi. «Fatto» programma il follow-up a 14 giorni. Se scrivi «bozza», prepara il testo da approvare. **Non scrive mai a nessuno.**

## Chat condivisa (più persone)
1. Crea un gruppo Telegram con le persone e aggiungi il bot.
2. Un proprietario scrive `/gruppo` nel gruppo: da ora è la chat condivisa (promemoria e lavori automatici arrivano lì).
3. Per abilitare un'altra persona: un proprietario risponde a un suo messaggio con `/abilita` (`/disabilita` per toglierla).
4. Nel gruppo ci si rivolge al bot con `@nome_del_bot richiesta` oppure rispondendo a un suo messaggio. Con la privacy di Telegram attiva (consigliato) il bot non legge il resto delle chiacchiere.

## Strumenti a riga di comando (dentro il contenitore)
```bash
docker compose exec manager python -m app.import_account --account nome         # importa tutto da Instagram
docker compose exec manager python -m app.classify_content --account nome       # classifica i contenuti
```
`--account` serve solo se gli account sono più di uno.
