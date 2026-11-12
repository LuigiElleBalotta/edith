# Architettura

Un contenitore, tanti account. Ogni account è un thread con il suo bot Telegram, il suo database e le sue regole.

```
                       ┌────────────────────── contenitore "edith" ──────────────────────┐
Tu (Telegram) ⇄ Telegram ⇄  account A  (thread: bot, SQLite, profilo, token Instagram)                │
Tu (Telegram) ⇄ Telegram ⇄  account B  (thread: bot, SQLite, profilo, token Instagram)   ⇄ servizio IA (OpenAI-compatibile)
                       │     browser interno  (127.0.0.1, token casuale, Chromium solo a richiesta)  │
                       └──────────────────────────────────────────────────────────────────────────┘
                            ./data/<nome>/  ·  ./accounts/<nome>/      (volumi, fuori dal contenitore)
```

## Perché un server e non il PC
Un programma sul PC non può rispondere a Telegram quando il PC è spento. Il bot usa il *long polling*: è lui a chiedere a Telegram se ci sono messaggi, quindi **non servono porte aperte, proxy o certificati**.

## Componenti (`bot/app/`)
| File | Cosa fa |
|---|---|
| `main.py` | avvia un thread per account, ricontrolla ogni 30 s se ne è comparso uno nuovo, riavvia con pausa chi va in errore; gestisce comandi, bottoni, gruppo, file |
| `config.py` | impostazioni comuni (ambiente) + una cartella per account (`account.env`, `profile.json`) |
| `accounts.py` | procedura guidata: `add`, `list`, `check`, `remove` |
| `agent.py` | personalità e regole ferree, stato reale nel prompt, scelta del modello, ciclo con strumenti |
| `ai.py` | **unico** punto che parla con l'IA (qualunque endpoint compatibile OpenAI) |
| `tools.py` | gli strumenti del manager (archivio, Instagram in lettura, web, bozze, contatti, piano…) |
| `db.py` | memoria SQLite per account: messaggi, archivio, piano, contatti, approvazioni, registro |
| `scheduler.py` | lavori automatici (report, ricerca, piano), agenda, promemoria contatti |
| `approvals.py`, `guard.py` | approvazione a bottoni; blocco sui contenuti non gestiti |
| `instagram.py`, `import_account.py` | Graph API in sola lettura; importazione quotidiana |
| `kb.py` | archivio di conoscenza (git): lettura, ricerca, modifiche solo con approvazione |
| `tg.py` | client Telegram, libreria standard |
| `browser_service.py` | Chromium a richiesta per leggere pagine e disegnare grafici |

Nessuna dipendenza esterna: solo libreria standard di Python.

## Modelli
Tre corsie, configurabili da `MODEL_NORMAL`, `MODEL_REASON`, `MODEL_LIGHT` (comuni o per account):
- **normale**: chat e bozze;
- **ragionamento**: strategia, piano editoriale, analisi (se non risponde, ripiega sul normale);
- **leggero**: lavori di fondo (classificazione, riassunti), senza dati privati dei messaggi.

Gli esempi usano id in stile OmniRoute (`cc/claude-sonnet-5-5`); con altri provider basta cambiare i nomi.

## Risorse
- A riposo: circa 20 MB di RAM per account.
- Chromium parte solo per leggere una pagina o disegnare un grafico (uno alla volta, limite 50 s) e si chiude.
- Limite del contenitore: 1 GB di RAM, 1,5 CPU, 300 processi.
- Disco: i file ricevuti si eliminano dopo 7 giorni (`MEDIA_RETENTION_DAYS`); le copie del database sono le ultime 7.

## Browser: tre modalità (`BROWSER_MODE`)
- `internal` (predefinita): un solo contenitore. Chromium gira con ambiente vuoto, profilo nuovo per ogni richiesta e solo verso indirizzi pubblici.
- `external`: un secondo contenitore **isolato**, senza accesso ai segreti (stessa immagine, `python -m app.browser_service`), con `BROWSER_URL` e `BROWSER_TOKEN`. È la scelta più sicura: vedi [SECURITY.md](../SECURITY.md).
- `off`: niente browser (si perdono grafici e lettura di pagine dinamiche).

## Limiti noti
- Telegram cloud permette download di file fino a 20 MB.
- Gli account condividono processo e utente: la separazione è logica (file e database distinti, controlli di accesso), non di sistema operativo.
