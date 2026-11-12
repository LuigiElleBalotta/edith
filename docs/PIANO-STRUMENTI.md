# Piano: EDITH che impara e si costruisce le estensioni

> **Stato: realizzato** (fasi A–F e una prima versione di H; **G non fatta**). Le decisioni del proprietario sono in fondo (sezione 11). Nel codice si chiamano `extensions`; nell'interfaccia **«Estensioni»**. Guida d'uso: [ESTENSIONI.md](ESTENSIONI.md).
>
> **Cosa è stato fatto davvero, e dove differisce dal piano:**
> - A: lezioni (`lezioni`), strumenti `lezione_salva` / `lezioni_leggi` / `regola_proponi`, lavoro `revisione_lezioni` (domenica), approvazione `modifica_profilo`, riproposta dopo `riproponi_dopo_giorni` (14), «Non riproporre più», pagina «Cosa ha imparato».
> - B–C: validatore, archivio in `./estensioni` (volume nel compose), versioni, passi `leggi_righe/scrivi_riga/aggiorna_riga/leggi_pagina/leggi_api/leggi_dati/chiedi_al_modello/ricorda_tra/ricorda_il`, strumenti `x_<id>_<nome>`, programmi, timer.
> - D: approvazioni `nuova_estensione` / `modifica_estensione` su Telegram **e** nel pannello (con manifest completo e «cosa cambia»).
> - E: pagine del pannello. Elementi implementati: `testo`, `tabella`, `tabella_modificabile`, `lista` (**non** `schede`, `numeri`, `modulo`). Pulsanti: spegni/accendi, torna indietro, esegui ora. **«Esporta» non c'è**: si copia la cartella.
> - F: documenti. H (catalogo): `bot/catalogo/` con 3 estensioni e `INDICE.json` (impronte), installazione solo come proposta da approvare.
> - Timer: scattano entro circa 30 secondi (il ciclo del bot). Nessun tetto su numero di estensioni o richieste; restano le protezioni tecniche (sezione 5.7).
> - **G (estensioni in codice in una gabbia): non fatta.** È la parte più rischiosa e il piano la teneva come progetto a parte.

## 1. L'idea
Oggi EDITH ha una lista **fissa** di strumenti. L'obiettivo è un assistente che **parte «vergine»**, impara man mano che viene usato e **si costruisce da solo** le funzioni che gli servono, compresa la pagina di gestione di ognuna nel pannello, per ogni account. EDITH resta la **base**: il motore (memoria, approvazioni, pannello, scheduler). Tutto il resto cresce sopra, account per account, come **estensioni**.

Un'estensione **vive fuori dal contenitore**, in una cartella sul server (`./estensioni/<account>/<estensione>/`): si copia, si sposta, si cancella senza toccare EDITH né ricostruire l'immagine.

### Tre esempi che guidano il progetto (account di cucina, inventati)
1. **Ricettario.** Il bot si accorge che si parla spesso di ricette e propone un'estensione «Ricettario»: una **raccolta di ricette** con una **pagina nel pannello** dove lo chef aggiunge e **modifica gli ingredienti**, e le modifiche si salvano.
2. **Timer di cottura.** Lo chef cucina mentre scrive al bot («metti su la pasta, 9 minuti»). L'estensione crea **timer** che avvisano su Telegram quando finisce ogni fase.
3. **Meteo.** Se l'utente chiede spesso il meteo, il bot propone un'estensione che lo legge da **un'API** e risponde senza cercarlo ogni volta sul web.

## 2. Cosa NON cambia (i paletti)
Sono le regole di [CLAUDE.md](../CLAUDE.md) e [SECURITY.md](../SECURITY.md), e valgono anche per tutto ciò che il bot costruisce:
1. **Nessuna azione verso l'esterno senza approvazione.** Un'estensione può **leggere** (da fonti approvate), **tenere i propri dati** e **avvisare il proprietario**; pubblicare, scrivere a terzi, candidarsi, comprare resta una bozza con i bottoni Approva/Rifiuta.
2. **Il bot non può approvarsi da solo.** L'approvazione arriva solo da un proprietario (bottone su Telegram o pulsante nel pannello con password).
3. **Niente segreti nel codice o nei file delle estensioni.** I segreti restano in `account.env`, scritti ma mai mostrati.
4. **Il pannello non riceve mai HTML o JavaScript dal bot.** Il bot descrive una pagina; il pannello la disegna con il suo codice (testi con escape, anti-CSRF, CSP rigida invariata).
5. **Niente accesso a Docker** dal pannello o dalle estensioni.
6. **Ogni account è isolato**: le estensioni e le pagine di un account non si vedono dall'altro.
7. **Si può sempre tornare indietro**: ogni estensione ha versioni, si può disattivare con un clic, i dati non si cancellano.

## 3. Da dove si parte (già nel codice)
| C'è già | Dove | Come lo riuso |
|---|---|---|
| Strumenti fissi: elenco `SPECS` + metodi `t_*` | `tools.py` | accanto a questi, strumenti **dinamici** letti dalle cartelle degli account |
| Approvazioni a bottoni, con tipi (`KINDS`) e funzioni dopo l'OK (`HOOKS`) | `approvals.py` | nuovi tipi: `modifica_profilo`, `nuovo_strumento`, `modifica_strumento` |
| Lavori programmati propri del profilo (`lavori`: solo un prompt e un orario) | `scheduler.py`, `profile.py` | sono già il primo «tool dichiarativo»: li generalizzo |
| Attività una tantum («avvisami tra N minuti»): `programma_attivita` | `tools.py`, `scheduler.py` (`run_due_tasks`) | base dei **timer** delle estensioni |
| Proposte di modifica all'archivio con approvazione | `kb.py`, `t_kb_proponi_modifica` | stesso schema per le modifiche al profilo |
| Pannello che disegna moduli e pagine da codice | `panel.py` | un disegnatore che parte da una descrizione, non da codice |
| Lettura pagine web con difese (indirizzi pubblici, redirect, limiti) | `tools.py` (`check_public_url`, `fetch_public`) | l'unico modo in cui un tool dichiarativo esce in rete |
| Registro delle azioni | `db.audit` | ogni proposta, approvazione e uso di un tool viene registrata |

## 4. Livello 1: impara senza codice (quaderno delle lezioni)
**Cosa:** il bot tiene un quaderno di **cose imparate** («rifiuta i post con più di 3 hashtag», «risponde meglio ai reel del venerdì», «non vuole mai X») e **propone una regola per sé**, anche subito se ritiene che valga la pena.

- **Dati:** tabella `lezioni` (testo, fonte: cosa l'ha fatta nascere, quante volte si è ripetuta, stato: `nuova / proposta / adottata / scartata / mai_piu`, `riproponi_dopo`).
- **Strumenti:** `lezione_salva`, `lezioni_leggi`.
- **Riproporre:** se la proposta viene rifiutata o lasciata senza risposta, il bot può **riproporla dopo qualche giorno** (di base 14, regolabile nel profilo). Se l'utente preme **«Non riproporre più»**, la lezione passa a `mai_piu` e **non torna mai**. Vale anche per le proposte di estensioni (sezione 5).
- **Lavoro programmato** `revisione_lezioni` (settimanale): guarda le lezioni, riporta in primo piano quelle da riproporre e crea un'approvazione `modifica_profilo` con **il prima e il dopo** (aggiunta o modifica a `regole_extra`).
- **Dopo il sì:** il codice applica la modifica a `profile.json`, solo sui campi consentiti (`regole_extra`, `benvenuto`, `ambito`; **mai** utenti, chiavi, archivio). Vale subito (il profilo si ricarica a ogni conversazione).
- **Cosa non fa:** non cambia mai le sue regole in silenzio. Sul pannello c'è la pagina «Cosa ha imparato» con la lista, e si può scartare o disattivare una lezione.

## 5. Livello 2: estensioni dichiarative (strumenti, dati, pagine, timer)
### 5.1 Il manifest
Un'estensione è una cartella `estensioni/<account>/<id>/` con un `manifest.json`. Esempio (inventato): un ricettario.
```json
{
  "versione": 1,
  "id": "ricettario",
  "nome": "Ricettario",
  "descrizione": "Raccolta di ricette con ingredienti modificabili.",
  "effetti": "dati_propri",
  "collezioni": [
    {"nome": "ricette", "campi": [
      {"chiave": "titolo", "tipo": "testo", "etichetta": "Titolo", "obbligatorio": true},
      {"chiave": "porzioni", "tipo": "numero", "etichetta": "Porzioni", "predefinito": 4},
      {"chiave": "ingredienti", "tipo": "elenco", "etichetta": "Ingredienti", "aiuto": "Uno per riga, con la quantità.", "esempio": "200 g di farina"},
      {"chiave": "procedimento", "tipo": "testo_lungo", "etichetta": "Procedimento"}
    ]}
  ],
  "strumenti": [
    {"nome": "ricetta_cerca", "descrizione": "Cerca una ricetta per titolo o ingrediente.", "parametri": [{"chiave": "testo", "tipo": "testo"}],
     "passi": [{"tipo": "leggi_righe", "collezione": "ricette", "cerca": "{testo}"}]},
    {"nome": "ricetta_salva", "descrizione": "Salva una ricetta nel ricettario.", "parametri": "collezione:ricette",
     "passi": [{"tipo": "scrivi_riga", "collezione": "ricette"}]}
  ],
  "pagine": [
    {"titolo": "Ricette", "mostra": [
      {"tipo": "tabella_modificabile", "collezione": "ricette", "colonne": ["titolo", "porzioni"], "modulo": "completo"}
    ]}
  ]
}
```
Altri due esempi, in breve:
```json
{"id": "timer_cottura", "nome": "Timer di cottura", "effetti": "avvisa_proprietario",
 "strumenti": [{"nome": "timer_avvia", "descrizione": "Avvisa tra N minuti.", "parametri": [{"chiave": "minuti", "tipo": "numero"}, {"chiave": "cosa", "tipo": "testo"}],
   "passi": [{"tipo": "ricorda_tra", "minuti": "{minuti}", "messaggio": "{cosa}: tempo scaduto"}]}]}
```
```json
{"id": "meteo", "nome": "Meteo", "effetti": "leggere", "domini": ["api.open-meteo.com"],
 "impostazioni": [{"chiave": "citta_lat", "tipo": "numero", "etichetta": "Latitudine"}, {"chiave": "citta_lon", "tipo": "numero", "etichetta": "Longitudine"}],
 "strumenti": [{"nome": "meteo_oggi", "descrizione": "Meteo di oggi.", "parametri": [],
   "passi": [{"tipo": "leggi_api", "url": "https://api.open-meteo.com/v1/forecast?latitude={citta_lat}&longitude={citta_lon}&daily=temperature_2m_max,precipitation_sum&timezone=auto", "estrai": ["daily.temperature_2m_max", "daily.precipitation_sum"]}]}]}
```

### 5.2 Cosa può contenere
- **Campi** (impostazioni e collezioni): `testo`, `testo_lungo`, `numero`, `si_no`, `scelta`, `elenco`, `data`, `segreto`. Il pannello li trasforma in moduli con aiuto ed esempio, **come oggi**. I `segreto` sono in sola scrittura.
- **Collezioni:** dati dell'estensione, con campi tipizzati. L'utente li **modifica dal pannello** (aggiungi, cambia, elimina); il bot li legge e li scrive con gli strumenti dell'estensione. Sono dati **propri** dell'estensione: non toccano nulla fuori.
- **Passi** (solo questi, in v1):

  | Passo | Cosa fa | Esce dal server? |
  |---|---|---|
  | `leggi_righe` / `scrivi_riga` / `aggiorna_riga` | legge o scrive nelle collezioni dell'estensione | no |
  | `leggi_pagina` / `leggi_api` | `GET` su un **dominio dichiarato e approvato**; `leggi_api` estrae campi da una risposta JSON | sì, solo lettura |
  | `leggi_dati` | query **in sola lettura**, con nome, sui dati dell'account | no |
  | `chiedi_al_modello` | un prompt con regole fisse | verso il servizio IA già configurato |
  | `ricorda_tra` / `ricorda_il` | **timer**: un messaggio al proprietario su Telegram tra N minuti o a una data, anche più d'uno (le fasi di una ricetta) | solo il messaggio al proprietario |

  **Non esiste** nessun passo che pubblica, scrive a terzi, o fa `POST` verso l'esterno.
- **Programma:** quando parte da solo (giorno/ora, come i `lavori` di oggi).
- **Cosa mostra la pagina:** `tabella`, `tabella_modificabile`, `modulo`, `schede`, `lista`, `testo`, `numeri`. Sempre da dati salvati, sempre con escape.
- **Segreti:** il manifest non li legge. Può solo usare `{segreto:chiave}` in un'intestazione di una richiesta verso **un dominio dichiarato** (es. la chiave di un'API meteo).
- **Effetti dichiarati** (`effetti`): `leggere`, `dati_propri`, `avvisa_proprietario`. Compaiono nel riassunto dell'approvazione. Qualsiasi altra cosa non è un'estensione: è una bozza da approvare, come oggi.

### 5.3 Dove stanno le cose (fuori dal contenitore)
```
./estensioni/<account>/<id>/          cartella sul server, montata nel contenitore
   manifest.json                       versione approvata
   versioni/v1.json, v2.json …         storico, per tornare indietro
   in_attesa/manifest.json             proposta non ancora approvata
   dati.sqlite                         le collezioni di QUESTA estensione (portabile)
```
Il contenitore monta `./estensioni` come volume (come `./data` e `./accounts`): le estensioni sopravvivono agli aggiornamenti e si copiano come file. Le impostazioni non segrete stanno nel manifest approvato o in `dati.sqlite`; i segreti restano in `account.env`.

### 5.4 Il flusso
1. L'utente dice o ripete qualcosa («metti su la pasta», «che tempo fa?»), oppure chiede lui un'estensione.
2. Il bot chiama `estensione_proponi(manifest)`. Il codice **valida** il manifest (formato, id, domini, campi sconosciuti, riferimenti).
3. Se valido: finisce in `in_attesa/` e parte un'approvazione `nuova_estensione`. **Su Telegram** arriva un riassunto in italiano semplice: cosa fa, **a quali domini si collega**, che dati tiene, quali timer può creare, «non può pubblicare né scrivere a nessuno». **Nel pannello** c'è l'anteprima completa (anche il JSON). Si approva da uno dei due; l'altro si aggiorna.
4. **Approva:** il manifest passa a `manifest.json`, si salva la versione, gli strumenti diventano disponibili al bot e la **pagina** compare nel pannello sotto l'account.
5. **Rifiuta / da modificare / «non riproporre più»:** il bot riceve la scelta e il motivo. Con «non riproporre più» smette di proporre quell'estensione.
6. Per **cambiare** un'estensione: nuova versione, nuova approvazione, con le differenze evidenziate.

### 5.5 Il pannello
- `/account/<slug>/estensioni`: elenco (attiva/spenta, versione, «in attesa di approvazione»).
- `/account/<slug>/estensioni/<id>`: le pagine, **disegnate dal pannello** dal manifest: moduli delle impostazioni, tabelle modificabili, risultati. Ogni scrittura è controllata contro i tipi dei campi, con anti-CSRF.
- Pulsanti: **Spegni**, **Torna alla versione precedente**, **Esegui ora**, **Esporta** (copia la cartella dell'estensione).
- Nessun HTML dal manifest: titoli, etichette, aiuti e dati sono testo, sempre con escape. Gli stili sono classi Tailwind già nel CSS.

### 5.6 Il bot lo vede come strumento
`Tools.specs()` aggiunge gli strumenti `x_<id>_<nome>` delle estensioni approvate e attive, con i parametri presi dal manifest; `Tools.run()` esegue i passi. Gli errori tornano come testo, come oggi.

### 5.7 Protezioni tecniche (non sono quote)
Non ci sono limiti sul **numero** di estensioni, richieste o righe: sul proprio server si fa quello che si vuole, e i tetti si possono impostare nel profilo (spenti di base). Restano fisse solo le protezioni che servono a non bloccare il bot: **tempo massimo** per passo, **dimensione massima** di una risposta letta, **freno ai cicli** (un'estensione che si richiama all'infinito), e la **paginazione** delle tabelle nel pannello. La difesa contro la fuga di dati non è un tetto: sono i **domini approvati**.

## 6. Livello 3 (dopo): strumenti in codice, in una gabbia
Solo quando il livello 2 non basta. Idea, da progettare meglio quando ci arriviamo:
- il bot scrive `tool.py` **e un test**; li esegue prima di proporre;
- l'approvazione mostra **il codice** (non solo il riassunto);
- gira in un **secondo contenitore** (`edith-tools`): senza chiavi, filesystem in sola lettura, nessun accesso a Docker, risorse limitate, rete solo verso un proxy con elenco di domini ammessi; EDITH lo chiama via HTTP locale;
- dichiara cosa può fare (`leggere`), e il resto passa dalle approvazioni come oggi.
Non si fa con `exec` dentro EDITH: lì ci sono le chiavi.

## 7. Livello 4 (dopo): il «market»
- Una cartella `catalogo/` nel repository (o un repository a parte: da decidere) con estensioni già riviste: `manifest.json`, una descrizione e un'impronta (`sha256`).
- **Installare** = copiare in `in_attesa/` con l'etichetta «dal catalogo», controllare l'impronta, e **chiedere l'approvazione**.
- Nessun aggiornamento automatico: una versione nuova è una nuova approvazione.
- Le estensioni create dal bot si possono «pubblicare» nel catalogo **solo dopo averle ripulite** da dati dell'account (controllo automatico + occhio umano).

## 8. Rischi e difese
| Rischio | Difesa |
|---|---|
| Una pagina web con istruzioni nascoste (prompt injection) convince il bot a proporre un tool dannoso | il bot **non può approvare**; l'approvazione mostra domini e passi; i testi letti dal web sono dati, non istruzioni; può proporre ma non approvare; «non riproporre più» le ferma |
| Un'estensione manda fuori dati (esfiltrazione) | solo `GET` verso i **domini approvati**; nessun `POST`; nessun passo che scrive fuori; i domini sono nel riassunto dell'approvazione; tetti opzionali nel profilo |
| SSRF (l'estensione chiama indirizzi interni) | stessi controlli di oggi (`check_public_url`): solo indirizzi pubblici, redirect controllati, dimensione massima |
| XSS o furto di chiavi dal pannello | niente HTML/JS dal manifest, testi sempre con escape, CSP invariata, anti-CSRF |
| Segreti nei manifest o nei risultati | il formato non ha un modo di leggerli; solo `{segreto:chiave}` verso un dominio dichiarato; il controllo segreti esamina i manifest; il registro oscura i valori noti |
| Estensioni che bloccano o appesantiscono il bot | timeout, dimensione massima delle risposte, freno ai cicli, limite di memoria del contenitore; tetti opzionali nel profilo |
| L'utente modifica i dati dal pannello con valori strani | ogni scrittura è validata contro i tipi dei campi, con anti-CSRF e escape alla visualizzazione |
| Un'estensione rompe qualcosa | versioni, «torna indietro» e «spegni» con un clic; i dati non si cancellano |
| Un account vede le estensioni di un altro | cartelle per account (`estensioni/<account>/…`); test che lo dimostra |
| Si perde traccia di chi ha fatto cosa | ogni proposta, approvazione, esecuzione e modifica va in `db.audit` |

## 9. Cosa cambia nei documenti
- `CLAUDE.md`, regola 1 e mappa del codice: «gli strumenti in sola lettura» diventa «gli strumenti fissi in sola lettura **più le estensioni dichiarative approvate**».
- `SECURITY.md`: una sezione «Estensioni create dal bot».
- `docs/ARCHITECTURE.md`: dove stanno estensioni, dati e pagine (`./estensioni`).
- `docker-compose.yml` e `setup.sh`: il volume `./estensioni`.
- Nuova guida per l'utente: «Come chiedere un'estensione».

## 10. Come lo costruiamo (fasi con criterio di «fatto»)
| Fase | Cosa | Fatto quando |
|---|---|---|
| A | Tabella `lezioni`, strumenti, lavoro `revisione_lezioni`, riproposta dopo N giorni e «non riproporre più», approvazione `modifica_profilo`, pagina «Cosa ha imparato» | una lezione diventa una proposta con prima/dopo; solo dopo il sì cambia `profile.json`; «non riproporre più» è definitivo (test) |
| B | Formato del manifest + validatore + cartella `./estensioni` (volume nel compose) + versioni | manifest non validi rifiutati con messaggio chiaro; test su campi sconosciuti, domini, riferimenti |
| C | Passi (dati, API, pagina, modello, timer) + strumenti `x_<id>_<nome>` + programma | le tre estensioni d'esempio (ricettario, timer, meteo) girano **senza rete reale nei test** e rispettano le protezioni |
| D | Approvazioni `nuova_estensione`/`modifica_estensione` su Telegram **e** nel pannello, con anteprima e «non riproporre più» | niente si attiva senza il sì; i due canali restano allineati |
| E | Disegnatore delle pagine (`/estensioni`), tabelle modificabili, moduli, «Esegui ora», spegni/torna indietro/esporta | la pagina esce solo dal manifest; XSS, CSRF e valori non validi provati con test |
| F | Documenti e guida utente («Come chiedere un'estensione») | la guida è seguibile da chi non conosce il progetto |
| G (dopo) | Gabbia per estensioni in codice | progetto a parte |
| H (dopo) | Catalogo/market | progetto a parte |

Ogni fase: test, controllo segreti, ricerca di dati personali, poi commit e push.

## 11. Decisioni prese dal proprietario
1. **Primo esempio:** account di cucina con **ricettario** (dati + pagina modificabile), **timer di cottura** e **meteo da API**. Le estensioni **vivono fuori dal contenitore** (`./estensioni`).
2. **Nome:** «Estensioni» nell'interfaccia.
3. **Approvazione:** da **Telegram e dal pannello**.
4. **Tetti:** nessuno come regola; opzionali nel profilo. Restano le protezioni tecniche della sezione 5.7.
5. **Catalogo:** da decidere più avanti (fase H).
6. **Lezioni:** il bot può proporle anche subito; le ripropone dopo qualche giorno; **«Non riproporre più»** le ferma per sempre.
