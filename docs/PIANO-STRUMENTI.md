# Piano: EDITH che impara e si costruisce gli strumenti

> **Stato: proposta di progetto, nessun codice ancora.** Da leggere, correggere e approvare prima di costruire.

## 1. L'idea
Oggi EDITH ha una lista **fissa** di strumenti. L'obiettivo è un assistente che **parte «vergine»**, impara man mano che viene usato e **si costruisce da solo** le funzioni che gli servono, compresa la pagina di gestione di ognuna nel pannello, per ogni account. EDITH resta la **base**: il motore (memoria, approvazioni, pannello, scheduler). Tutto il resto cresce sopra, account per account.

## 2. Cosa NON cambia (i paletti)
Sono le regole di [CLAUDE.md](../CLAUDE.md) e [SECURITY.md](../SECURITY.md), e valgono anche per tutto ciò che il bot costruisce:
1. **Nessuna azione verso l'esterno senza approvazione.** Un tool può **leggere** e **preparare**; pubblicare, scrivere, candidarsi, comprare resta una bozza con i bottoni Approva/Rifiuta.
2. **Il bot non può approvarsi da solo.** L'approvazione arriva solo da un proprietario (bottone su Telegram o pulsante nel pannello con password).
3. **Niente segreti nel codice o nei file dei tool.** I segreti restano in `account.env`, scritti ma mai mostrati.
4. **Il pannello non riceve mai HTML o JavaScript dal bot.** Il bot descrive una pagina; il pannello la disegna con il suo codice (testi con escape, anti-CSRF, CSP rigida invariata).
5. **Niente accesso a Docker** dal pannello o dai tool.
6. **Ogni account è isolato**: i tool e le pagine di un account non si vedono dall'altro.
7. **Si può sempre tornare indietro**: ogni tool ha versioni, si può disattivare con un clic, i dati non si cancellano.

## 3. Da dove si parte (già nel codice)
| C'è già | Dove | Come lo riuso |
|---|---|---|
| Strumenti fissi: elenco `SPECS` + metodi `t_*` | `tools.py` | accanto a questi, strumenti **dinamici** letti dalle cartelle degli account |
| Approvazioni a bottoni, con tipi (`KINDS`) e funzioni dopo l'OK (`HOOKS`) | `approvals.py` | nuovi tipi: `modifica_profilo`, `nuovo_strumento`, `modifica_strumento` |
| Lavori programmati propri del profilo (`lavori`: solo un prompt e un orario) | `scheduler.py`, `profile.py` | sono già il primo «tool dichiarativo»: li generalizzo |
| Proposte di modifica all'archivio con approvazione | `kb.py`, `t_kb_proponi_modifica` | stesso schema per le modifiche al profilo |
| Pannello che disegna moduli e pagine da codice | `panel.py` | un disegnatore che parte da una descrizione, non da codice |
| Lettura pagine web con difese (indirizzi pubblici, redirect, limiti) | `tools.py` (`check_public_url`, `fetch_public`) | l'unico modo in cui un tool dichiarativo esce in rete |
| Registro delle azioni | `db.audit` | ogni proposta, approvazione e uso di un tool viene registrata |

## 4. Livello 1: impara senza codice (quaderno delle lezioni)
**Cosa:** il bot tiene un quaderno di **cose imparate** («rifiuta i post con più di 3 hashtag», «risponde meglio ai reel del venerdì», «non vuole mai X») e, quando un'idea si ripete, **propone una regola per sé**.

- **Dati:** tabella `lezioni` (testo, fonte: cosa l'ha fatta nascere, quante volte si è ripetuta, stato: `nuova / proposta / adottata / scartata`).
- **Strumenti:** `lezione_salva`, `lezioni_leggi`.
- **Lavoro programmato** `revisione_lezioni` (settimanale): guarda le lezioni ripetute e crea un'approvazione `modifica_profilo` con **il prima e il dopo** (aggiunta o modifica a `regole_extra`).
- **Dopo il sì:** il codice applica la modifica a `profile.json`, solo sui campi consentiti (`regole_extra`, `benvenuto`, `ambito`; **mai** utenti, chiavi, archivio). Vale subito (il profilo si ricarica a ogni conversazione).
- **Cosa non fa:** non cambia mai le sue regole in silenzio. Sul pannello c'è la pagina «Cosa ha imparato» con la lista, e si può scartare o disattivare una lezione.

## 5. Livello 2: strumenti e pagine dichiarativi
### 5.1 Il manifest
Un tool è una cartella `accounts/<nome>/tools/<id>/` con un `manifest.json`. Esempio (inventato):
```json
{
  "versione": 1,
  "id": "concorsi",
  "nome": "Concorsi",
  "descrizione": "Ogni lunedì cerca concorsi aperti e li elenca.",
  "effetti": "leggere",
  "domini": ["example.org"],
  "impostazioni": [
    {"chiave": "parole", "tipo": "elenco", "etichetta": "Parole chiave", "aiuto": "Una per riga.", "esempio": "cantautori, festival"},
    {"chiave": "giorno", "tipo": "scelta", "etichetta": "Giorno del report", "opzioni": ["lunedì", "venerdì"], "predefinito": "lunedì"}
  ],
  "passi": [
    {"tipo": "leggi_pagina", "url": "https://example.org/bandi?q={parole}", "estrai": "testo"},
    {"tipo": "chiedi_al_modello", "istruzione": "Elenca i concorsi aperti con scadenza e link. Non inventare.", "uscita": "righe"}
  ],
  "programma": {"giorno": "{giorno}", "ora": "09:00"},
  "mostra": [
    {"tipo": "tabella", "titolo": "Concorsi aperti", "colonne": ["nome", "scadenza", "link"], "da": "righe"}
  ]
}
```

### 5.2 Cosa può contenere
- **Campi delle impostazioni:** `testo`, `numero`, `si_no`, `scelta`, `elenco`, `segreto`. Il pannello li trasforma in un modulo con aiuto ed esempio, **come oggi**. I `segreto` sono in sola scrittura.
- **Passi** (solo questi, in v1): `leggi_pagina` (GET su un dominio dichiarato), `leggi_dati` (query **in sola lettura**, con nome, sui dati dell'account), `chiedi_al_modello` (un prompt con regole fisse), `salva_righe` (nella tabella dei dati del tool). **Non c'è** nessun passo che pubblica, scrive messaggi o fa POST.
- **Programma:** quando parte da solo (giorno/ora, come i `lavori` di oggi).
- **Cosa mostra la pagina:** `tabella`, `schede`, `lista`, `testo`, `numeri`. Sempre da dati salvati, sempre con escape.
- **Segreti:** il manifest non li legge. Può solo usare `{segreto:chiave}` in una intestazione di una richiesta verso **un dominio dichiarato**.

### 5.3 Dove stanno le cose
```
accounts/<nome>/tools/<id>/
   manifest.json        versione approvata
   versioni/v1.json …   storico (per tornare indietro)
   in_attesa/manifest.json   proposta non ancora approvata
data/<nome>/manager.sqlite
   tool_config(tool_id, chiave, valore)      impostazioni (i segreti NON qui: in account.env)
   tool_dati(tool_id, ts, riga_json)         risultati, con tetto di righe e dimensione
```

### 5.4 Il flusso
1. L'utente dice qualcosa («voglio un controllo settimanale dei concorsi»).
2. Il bot chiama `strumento_proponi(manifest)`. Il codice **valida** il manifest (formato, id, domini, limiti, nessun campo sconosciuto).
3. Se valido: finisce in `in_attesa/` e parte un'approvazione `nuovo_strumento`. Su Telegram arriva un **riassunto in italiano semplice**: cosa fa, **a quali domini si collega**, quali impostazioni chiede, quando parte, cosa salva, «non può pubblicare né scrivere». Nel pannello c'è l'anteprima completa (compreso il JSON) con Approva / Rifiuta.
4. **Approva:** il manifest passa a `manifest.json`, si salva la versione, il tool compare tra gli strumenti del bot (`x_<id>`) e la sua **pagina** compare nel pannello sotto l'account.
5. **Rifiuta o da modificare:** il bot riceve il motivo e può riproporre.
6. Per **cambiare** un tool: nuova versione, nuova approvazione, con le differenze evidenziate.

### 5.5 Il pannello
- `/account/<slug>/strumenti`: elenco (attivo/spento, versione, ultimo risultato, «in attesa di approvazione»).
- `/account/<slug>/strumenti/<id>`: la pagina del tool, **disegnata dal pannello** dal manifest: modulo delle impostazioni (valori controllati contro il manifest, anti-CSRF) e le sezioni `mostra`.
- Pulsanti: **Spegni**, **Torna alla versione precedente**, **Esegui ora**.
- Nessun HTML dal manifest: titoli, etichette, aiuti sono testo, sempre con escape. Gli stili sono classi Tailwind già nel CSS.

### 5.6 Il bot lo vede come strumento
`Tools.specs()` aggiunge uno strumento `x_<id>` per ogni tool approvato e attivo, con i parametri presi dal manifest; `Tools.run()` esegue i passi. Gli errori tornano come testo, come oggi.

## 6. Livello 3 (dopo): strumenti in codice, in una gabbia
Solo quando il livello 2 non basta. Idea, da progettare meglio quando ci arriviamo:
- il bot scrive `tool.py` **e un test**; li esegue prima di proporre;
- l'approvazione mostra **il codice** (non solo il riassunto);
- gira in un **secondo contenitore** (`edith-tools`): senza chiavi, filesystem in sola lettura, nessun accesso a Docker, risorse limitate, rete solo verso un proxy con elenco di domini ammessi; EDITH lo chiama via HTTP locale;
- dichiara cosa può fare (`leggere`), e il resto passa dalle approvazioni come oggi.
Non si fa con `exec` dentro EDITH: lì ci sono le chiavi.

## 7. Livello 4 (dopo): il «market»
- Una cartella `tools/` nel repository (o un repository a parte) con tool già rivisti: `manifest.json`, una descrizione e un'impronta (`sha256`).
- **Installare** = copiare in `in_attesa/` con l'etichetta «dal catalogo», controllare l'impronta, e **chiedere l'approvazione**.
- Nessun aggiornamento automatico: una versione nuova è una nuova approvazione.
- I tool creati dal bot si possono «pubblicare» nel catalogo **solo dopo averli ripuliti** da dati dell'account (controllo automatico + occhio umano).

## 8. Rischi e difese
| Rischio | Difesa |
|---|---|
| Una pagina web con istruzioni nascoste (prompt injection) convince il bot a proporre un tool dannoso | il bot **non può approvare**; l'approvazione mostra domini e passi; i testi letti dal web sono dati, non istruzioni; limite di proposte al giorno |
| Un tool manda fuori dati (esfiltrazione) | solo `GET` verso i **domini approvati**; nessun `POST`; nessun passo di scrittura; i domini sono nel riassunto dell'approvazione; tetto di richieste al giorno |
| SSRF (il tool chiama indirizzi interni) | stessi controlli di oggi (`check_public_url`): solo indirizzi pubblici, redirect controllati, dimensione massima |
| XSS o furto di chiavi dal pannello | niente HTML/JS dal manifest, testi sempre con escape, CSP invariata, anti-CSRF |
| Segreti nei manifest o nei risultati | il formato non ha un modo di leggerli; solo `{segreto:chiave}` verso un dominio dichiarato; il controllo segreti esamina i manifest; il registro oscura i valori noti |
| Tool che consumano risorse o riempiono il disco | tetti: passi per tool, righe e byte salvati, richieste/giorno, tool per account |
| Un tool rompe qualcosa | versioni, «torna indietro» e «spegni» con un clic; i dati non si cancellano |
| Un account vede i tool di un altro | percorsi e tabelle per account; test che lo dimostra |
| Si perde traccia di chi ha fatto cosa | ogni proposta, approvazione, esecuzione e modifica va in `db.audit` |

## 9. Cosa cambia nei documenti
- `CLAUDE.md`, regola 1 e mappa del codice: «gli strumenti in sola lettura» diventa «gli strumenti **dichiarativi approvati** in sola lettura».
- `SECURITY.md`: una sezione «Strumenti creati dal bot».
- `docs/ARCHITECTURE.md`: dove stanno tool, dati e pagine.
- Nuova guida per l'utente: «Come chiedere un nuovo strumento».

## 10. Come lo costruiamo (fasi con criterio di «fatto»)
| Fase | Cosa | Fatto quando |
|---|---|---|
| A | Tabelle `lezioni`, strumenti, lavoro `revisione_lezioni`, approvazione `modifica_profilo`, pagina «Cosa ha imparato» | una lezione ripetuta diventa una proposta con prima/dopo; solo dopo il sì cambia `profile.json` (test) |
| B | Formato del manifest + validatore + cartelle + versioni | manifest non validi rifiutati con messaggio chiaro; test su campi sconosciuti, domini, tetti |
| C | Passi (`leggi_pagina`, `leggi_dati`, `chiedi_al_modello`, `salva_righe`) + `x_<id>` + programma | un tool di prova gira, salva righe e rispetta i tetti, **senza rete reale nei test** |
| D | Approvazioni `nuovo_strumento`/`modifica_strumento` su Telegram e nel pannello, con anteprima | niente si attiva senza il sì; rifiuto e «da modificare» tornano al bot |
| E | Disegnatore delle pagine (`/strumenti`) + impostazioni + «Esegui ora» + spegni/torna indietro | la pagina esce solo dal manifest; XSS e CSRF provati con test |
| F | Documenti e guida utente | la guida è seguibile da chi non conosce il progetto |
| G (dopo) | Gabbia per tool in codice | progetto a parte |
| H (dopo) | Catalogo/market | progetto a parte |

Ogni fase: test, controllo segreti, ricerca di dati personali, poi commit e push.

## 11. Domande aperte (per te)
1. **Primo esempio concreto.** Quale tool vorresti vedere nascere per primo? Mi serve per provare il formato su un caso vero.
2. **Come lo chiamiamo nell'interfaccia?** «Strumenti», «Competenze», «Abilità»? (Nel codice resta `tools`.)
3. **Dove si approva?** Telegram e pannello entrambi (consigliato), o solo uno?
4. **Tetti iniziali.** Proposta: 10 tool per account, 20 richieste/giorno per tool, 500 righe salvate per tool, 3 proposte nuove al giorno.
5. **Catalogo.** Cartella `tools/` in questo repository, oppure repository a parte?
6. **Lezioni.** Il bot può proporre regole per sé solo dopo 3 ripetizioni (consigliato), oppure anche subito?
