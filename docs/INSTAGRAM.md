# Collegare Instagram (sola lettura)

Il manager legge Instagram **solo con le API ufficiali di Meta** (Graph API). Niente password, niente scraping, niente browser che entra nel tuo profilo. Questa guida porta al token da incollare in `./manager add` (o in `accounts/<nome>/account.env` come `META_IG_TOKEN` e `META_IG_USER_ID`).

Ci vogliono circa 15 minuti. Collegare Instagram è **facoltativo**: senza, il manager lavora con quello che gli racconti e con la ricerca web.

## Cosa serve prima
1. Un account Instagram **professionale** (Creator o Business). Si cambia da Instagram: Impostazioni → Tipo di account.
2. Una **Pagina Facebook** collegata a quell'account Instagram.
3. Un account Meta Business (business.facebook.com) e un account sviluppatore (developers.facebook.com).

## Passi
1. **Portfolio business.** In *Meta Business Suite → Impostazioni* controlla di avere un portfolio che contiene la Pagina e l'account Instagram. Se l'Instagram chiede di accedere per sbloccare le impostazioni, accedi: lo fai tu, con le tue credenziali, in una finestra di Instagram.
2. **App.** Su developers.facebook.com → *Crea app*. Caso d'uso: **«Gestisci messaggi e contenuti su Instagram»**. Collega l'app al **portfolio** del punto 1. Resta in modalità sviluppo: non serve pubblicarla per un account tuo.
3. **Utente di sistema.** Portfolio → Impostazioni → *Utenti → Utenti di sistema → Aggiungi*. Nome a piacere, ruolo *Employee*. (Meta può chiedere di accettare una normativa sulle discriminazioni: serve a te, accettala.)
4. **Assegna le risorse all'utente di sistema**, con il **minimo** necessario:
   - *Pagine Facebook* → la tua Pagina → accendi **solo «Insight»**;
   - *Account Instagram* → il tuo account → accendi **solo «Insights»**;
   - *App* → la tua app → **«Visualizza insight»** (include «Testa l'app»).
5. **Genera il token.** Sull'utente di sistema → *Genera token*: scegli l'app, scadenza **Mai** (così il manager non si ferma ogni 60 giorni; lo puoi revocare quando vuoi con *Revoca token*), poi scegli i permessi:

   | Permesso | A cosa serve | Serve? |
   |---|---|---|
   | `instagram_basic` | profilo, post, profili pubblici professionali | **Sì** |
   | `instagram_manage_insights` | statistiche di account e post, pubblico | **Sì** |
   | `pages_read_engagement` | lettura legata alla Pagina | **Sì** |
   | `pages_show_list` | elenco delle Pagine | Consigliato |
   | `instagram_manage_comments` | **leggere i commenti** | Solo se vuoi l'analisi dei commenti (vedi sotto) |
   | `instagram_content_publish`, `instagram_manage_contents`, `instagram_manage_messages` | pubblicare, gestire, scrivere messaggi | **No: il manager non li usa** |

   ⚠️ Fai attenzione a cosa spunti: nell'elenco i permessi di scrittura stanno accanto a quelli di lettura. Se spunti per sbaglio `content_publish` o `messages`, **revoca il token e rigeneralo**.

   **Nota onesta sui commenti:** Meta non ha un permesso «solo lettura commenti». `instagram_manage_comments` permette di leggere ma anche di rispondere, nascondere ed eliminare. Il manager **non lo fa mai** (nel codice non esiste nessuna azione di scrittura su Instagram), ma il token tecnicamente potrebbe. Se preferisci un token che non possa scrivere neanche in teoria, non spuntarlo: perdi solo l'analisi dei commenti.
6. **Copia il token** (si vede una sola volta) e incollalo quando `./manager add` lo chiede, insieme all'**ID dell'account Instagram** (Business Suite → Impostazioni → Account Instagram, è un numero lungo).
7. **Verifica che funzioni:** `./manager check` deve mostrare `✓ Instagram: @tuoaccount (… follower)`.
8. **Verifica i permessi del token** (importante, vedi sotto): un token che funziona può comunque avere più permessi del necessario.

## Verificare i permessi del token
`./manager check` dice solo se il token funziona, non **quali permessi ha**. Per vederli:
1. Apri lo strumento di Meta [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) e incolla il token (è uno strumento di Meta: il token va solo a Meta).
2. Leggi l'elenco **Scopes**. Per la sola lettura devono esserci solo `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`, `pages_show_list` (e `instagram_manage_comments` solo se vuoi leggere i commenti).
3. Se vedi `instagram_content_publish`, `instagram_manage_contents` o `instagram_manage_messages`, il token **potrebbe** pubblicare o scrivere messaggi. EDITH non lo fa mai (nel codice non esiste nessuna azione di scrittura su Instagram), ma il rischio c'è se il token finisce in mani sbagliate. **Revoca e rigenera** il token spuntando solo i permessi della tabella.

Se per scelta tieni un token più ampio, trattalo come una chiave di casa: solo nel file `account.env` con permessi `600`, mai in chat o nel repository, e cambialo se ha toccato posti non sicuri.

Da quel momento il manager importa da solo ogni giorno post, statistiche e commenti, senza che tu faccia nulla.

## Se qualcosa non va
- **«Application does not have permission» sulle statistiche:** manca `instagram_manage_insights` nel token, oppure «Insights» nell'assegnazione delle risorse. Rigenera il token.
- **Non trovo una voce dell'interfaccia:** Meta cambia spesso i nomi. Cerca la funzione («Utenti di sistema», «Genera token», «Assegna risorse») e segui quello che vedi a schermo.
- **Il portfolio ha restrizioni («Con restrizioni»):** Meta può limitare un portfolio per le inserzioni; la lettura continua a funzionare. Le restrizioni si controllano in Business Suite → Centro per la sicurezza.
- **Token rifiutato dopo mesi:** può essere stato revocato o la password dell'account cambiata. Rigenera il token e aggiorna `accounts/<nome>/account.env`.
- **Se un token è finito dove non doveva:** *Revoca token* nell'utente di sistema, subito. Poi rigeneralo. Vedi anche [SECURITY.md](../SECURITY.md).
