# Estensioni: funzioni in più, costruite con il tuo OK

EDITH parte con pochi strumenti. Le **estensioni** sono funzioni in più che il manager può proporre quando ne vede il bisogno (o che installi dal catalogo): un ricettario con una pagina da modificare, un timer che ti avvisa quando finisce la cottura, il meteo letto da un servizio pubblico. Ognuna ha la sua pagina nel pannello.

**Niente si attiva senza il tuo OK.** Il manager propone, tu decidi.

## Come funziona, in breve
1. Il manager nota che ti serve qualcosa (chiedi spesso il meteo, parli sempre di ricette…) e te lo propone.
2. Ti arriva un messaggio su Telegram con un riassunto in italiano semplice e i bottoni **Approva / Rifiuta / Cambia / Non riproporre più**. La stessa proposta compare nel pannello, in *Estensioni → Da approvare*, con anche il testo completo (JSON). Decidi dove preferisci: l'altro canale si aggiorna da solo.
3. Se approvi, l'estensione si attiva e la sua pagina compare nel pannello.
4. Se rifiuti, il manager può riproporla più avanti. Se premi **Non riproporre più**, non la riproporrà mai.

### Cosa leggi prima di approvare
- **Cosa può fare**: leggere da siti che approvi, tenere i suoi dati, mandarti un messaggio a un'ora precisa.
- **A quali siti si collega** (se ce ne sono). Guardali: sono l'unico posto verso cui l'estensione può andare.
- **Che dati tiene**, quali strumenti dà al manager, se parte da sola e quando.
- Se è una **modifica**: cosa cambia rispetto alla versione approvata, con **⚠️ nuovi siti** o **nuovi permessi** in evidenza.

## Dove stanno i file
```
./estensioni/<account>/<id>/
    manifest.json        la versione approvata
    versioni/v1.json …   le versioni passate (si può tornare indietro)
    in_attesa/           una proposta non ancora approvata
    dati.sqlite          i dati propri di questa estensione
```
Stanno **fuori dal contenitore**, in una cartella accanto a `data` e `accounts`. Gli aggiornamenti di EDITH non le toccano. Per spostarle o fare una copia basta copiare la cartella. Per toglierne una: spegnila dal pannello (i dati restano) oppure cancella la sua cartella.

## Usarle dal pannello
In **Estensioni** vedi l'elenco; cliccandone una:
- **Impostazioni**: i campi che l'estensione chiede (una città, un orario, una chiave). I campi *segreto* si scrivono ma non si mostrano mai; vanno in `account.env`, non nell'estensione.
- **Tabelle modificabili**: aggiungi, cambia o elimini righe a mano (ogni scrittura è controllata: un numero deve essere un numero, un campo obbligatorio non può restare vuoto). Prima di eliminare ti chiede conferma.
- **Spegni / Accendi**, **Torna alla versione precedente**, **Esegui ora** (se ha un programma).

## Timer e programmi
- **Timer** (`ricorda_tra`, `ricorda_il`): un messaggio a te, su Telegram, tra N minuti o a una data. Possono essere più d'uno (le fasi di una ricetta). Scattano entro circa **30 secondi** dall'ora indicata.
- **Programma**: l'estensione può eseguire uno dei suoi strumenti ogni giorno o un certo giorno della settimana, e mandarti il risultato. Una sola prova al giorno: se qualcosa va storto, non ti riempie di messaggi.

## Il catalogo
In **Catalogo** ci sono estensioni già pronte (ricettario, timer di cottura, meteo). Ognuna ha un'**impronta** controllata: se il file è stato cambiato a mano, non si installa. «Proponi l'installazione» **non installa**: crea una richiesta che approvi tu dopo aver letto cosa fa.

## Cosa ha imparato (le lezioni)
Mentre lavora, il manager annota cose che nota («preferisce i testi corti»). Se una lezione vale la pena, ti **propone una regola per sé**, mostrando il prima e il dopo. La regola cambia solo se approvi, e vale subito.
- Se la rifiuti, la riproporrà **non prima di 14 giorni** (si cambia con `riproponi_dopo_giorni` in `profile.json`).
- Con **Non riproporre più** non tornerà mai. Dalla pagina **Cosa ha imparato** puoi anche riattivare una lezione scartata.

## Cosa non può fare, mai
Un'estensione **non** può pubblicare, commentare, scrivere a nessuno, fare richieste che inviano dati, leggere le tue chiavi o toccare i dati di un altro account. Non contiene codice: è una descrizione che EDITH legge con passi fissi e controllati. Dettagli in [SECURITY.md](../SECURITY.md).

---

# Riferimento del formato (`manifest.json`)

Il manager lo conosce già (lo strumento `estensione_formato`). Questo è per chi vuole capire gli errori o preparare un manifest da dare al manager (o da aggiungere al catalogo). Un file copiato a mano nella cartella di un'estensione **non** crea nessuna richiesta di approvazione e non si attiva: le estensioni entrano solo da una proposta approvata, oppure dal catalogo.

## Voci del manifest
`versione` (1), `id`, `nome`, `descrizione`, `effetti`, `domini`, `impostazioni`, `collezioni`, `strumenti`, `pagine`, `programma`. Voci sconosciute = errore.

| Voce | Regole |
|---|---|
| `id` | minuscole, numeri e `_`, da 2 a 24 caratteri, inizia con una lettera |
| `effetti` | lista tra `leggere`, `dati_propri`, `avvisa_proprietario`. Deve comprendere **tutti** quelli che i passi usano |
| `domini` | i siti ammessi, es. `api.open-meteo.com`. Ogni indirizzo dei passi deve essere `https`, su uno di questi domini, scritto per intero (niente variabili nel dominio, niente utente o porta) |
| `impostazioni` | lista di campi che compili nel pannello |
| `collezioni` | `[{nome, campi}]`: i dati propri |
| `strumenti` | `[{nome, descrizione, parametri, passi}]`; il manager li vede come `x_<id>_<nome>` |
| `pagine` | `[{titolo, mostra: [...]}]` |
| `programma` | `{strumento, giorno, ora, invia}`; lo strumento non deve avere parametri |

## Campi
`{chiave, tipo, etichetta, aiuto, esempio, predefinito, opzioni, obbligatorio}`.
Tipi: `testo`, `testo_lungo`, `numero`, `si_no`, `scelta` (con `opzioni`), `elenco` (una voce per riga), `data` (AAAA-MM-GG), `segreto` (solo nelle impostazioni).

## Passi
Nei testi `{nome}` è un parametro dello strumento o un'impostazione. `{segreto:chiave}` si può usare **solo** nelle `intestazioni` di `leggi_api`.

| Passo | Cosa fa | Esce dal server? |
|---|---|---|
| `leggi_righe` `{collezione, cerca?, limite?}` | legge le righe | no |
| `scrivi_riga` `{collezione}` | salva una riga con i parametri | no |
| `aggiorna_riga` `{collezione}` | cambia **solo i campi passati** (serve `id`) | no |
| `leggi_pagina` `{url}` | `GET` di una pagina, trasformata in testo | sì, solo lettura, solo `domini` |
| `leggi_api` `{url, estrai?, intestazioni?}` | `GET` di una risposta JSON; `estrai` sono percorsi come `daily.temperature_2m_max.0` | sì, solo lettura, solo `domini` |
| `leggi_dati` `{nome}` | dati dell'account in sola lettura: `fatti`, `contatti`, `opportunita`, `appunti`, `piano` | no |
| `chiedi_al_modello` `{istruzione}` | elabora il testo dei passi prima con l'IA già configurata | verso l'IA |
| `ricorda_tra` `{minuti, messaggio}` / `ricorda_il` `{quando, messaggio}` | timer: messaggio a te su Telegram | solo il messaggio a te |

**Non esiste** nessun passo che pubblichi, scriva a terzi o faccia `POST`.

## Pagine
`mostra`: `{tipo:"testo", testo}`, `{tipo:"tabella", collezione, colonne}`, `{tipo:"tabella_modificabile", collezione, colonne}`, `{tipo:"lista", collezione, campo}`. Le impostazioni compaiono da sole.

## Un esempio completo
Vedi i tre file in [`bot/catalogo/`](../bot/catalogo/): `ricettario.json` (dati + pagina modificabile), `timer_cottura.json` (timer), `meteo.json` (API + programma).

## Errori comuni
| Messaggio | Cosa fare |
|---|---|
| «`effetti` deve dichiarare anche…» | aggiungi quell'effetto alla lista |
| «… non è tra i `domini` dichiarati» | aggiungi il sito a `domini` (e controlla che sia quello giusto) |
| «l'indirizzo deve iniziare con https://» | usa `https` |
| «il sito deve essere scritto per intero» | niente `{variabili}`, utente o porta nel dominio |
| «… non è un parametro né un'impostazione» | scrivi `{nome}` con il nome di un parametro o di un'impostazione |
| «c'è già una proposta in attesa» | decidi prima quella (Telegram o pannello) |
| «il proprietario ha detto di NON riproporre…» | era stato premuto «Non riproporre più» |

## Per chi sviluppa
Codice: `bot/app/extensions.py` (validazione, archivio, esecuzione, timer, approvazioni) e `bot/app/panel_ext.py` (pagine). Il catalogo si rigenera con `python scripts/aggiorna_catalogo.py`; un test controlla che l'indice sia aggiornato. Piano e motivazioni: [PIANO-STRUMENTI.md](PIANO-STRUMENTI.md).
