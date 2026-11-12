# Esperti: un team di consulenti per il manager

EDITH da sola conosce il tuo account e i suoi strumenti. Gli **esperti** le danno un **secondo parere di mestiere**: strategia social, contenuti, PR, candidature a bandi, vendite e contatti, pubblicità, traduzioni. Sono ruoli già pronti, scelti dal progetto open source [agency-agents](https://github.com/msitarzewski/agency-agents) (licenza MIT, autori «AgentLand Contributors»), importati **senza modifiche**.

## Come funziona
1. Fai una domanda difficile («come preparo la candidatura a questo festival?», «che formato di reel conviene?»).
2. Il manager guarda l'elenco (`esperti_elenco`), sceglie chi interpellare (`esperto_consulta`) e gli passa **la domanda e i dati che servono**.
3. L'esperto risponde con un **parere**. Il manager lo confronta con i dati veri del tuo account e **decide lui cosa dirti**, distinguendo «dato misurato» da «parere dell'esperto».

Non lo fa a ogni risposta: solo quando serve un parere in più.

## Anche nella Biblioteca
I ruoli degli esperti sono indicizzati nella [Biblioteca](BIBLIOTECA.md): per i temi che coprono, la ricerca automatica li ritrova da sola (dopo i tuoi documenti e al massimo un pezzo per volta), oltre a poterli interpellare a richiesta. Se spegni un esperto, esce anche dalla ricerca.

## Cosa un esperto NON può fare
- **Non agisce.** È una sola richiesta all'IA, **senza strumenti**: non pubblica, non scrive a nessuno, non compra, non apre programmi.
- **Non vede il tuo account.** Riceve solo la domanda e il contesto che il manager gli passa, **dopo un filtro** che oscura token e chiavi.
- **Non cambia le regole.** Le regole di EDITH (non inventare, niente scorciatoie scorrette, solo consulenza, italiano semplice) vengono scritte **prima** del testo del ruolo e prevalgono.
- **Non è una misura.** I numeri di riferimento che trovi nei ruoli («engagement 3,5%») sono indicativi, non misurati sul tuo account: il manager li presenta come ipotesi.

## Chi c'è (35 esperti)
| Divisione | Esperti |
|---|---|
| Marketing e social | Social Media Strategist, Instagram Curator, Content Creator, TikTok Strategist, Growth Hacker, Video Optimization, Short-Video Editing Coach, Podcast Strategist, Email Strategist, PR & Communications, SEO Specialist, LinkedIn Content Creator, Reddit Community Builder |
| Design e immagine | Brand Guardian, Visual Storyteller, Whimsy Injector, Image Prompt Engineer |
| Vendite e contatti | Outbound Strategist, Proposal Strategist, Offer & Lead Gen Strategist |
| Pubblicità | Paid Social Strategist, Ad Creative Strategist |
| Supporto e analisi | Analytics Reporter, Executive Summary Generator, Legal Compliance Checker |
| Prodotto e ricerca | Trend Researcher, Feedback Synthesizer, Research Synthesist |
| Specialisti | Grant Writer, Chief of Staff, Business Strategist, Language Translator, Pricing Analyst, Cultural Intelligence Strategist, Customer Service |

I ruoli sono scritti in inglese: l'esperto risponde comunque in italiano semplice.

**Esclusi apposta:** gli agenti di agency-agents che pubblicano da soli o fanno scraping (per esempio il «Carousel Growth Engine» o il «Multi-Platform Publisher»), perché EDITH non pubblica e non fa scraping.

## Accenderli e spegnerli
Dal pannello, dentro l'account: **Esperti**. Ognuno ha **Accendi / Spegni**; vale subito. Si può anche scrivere a mano in `profile.json`: `"esperti_spenti": ["seo_specialist"]`.

## Sicurezza (sono testi di terzi)
Un ruolo è un testo scritto da altri, quindi lo trattiamo con prudenza:
- **Versione fissa.** Si importa da un commit preciso, mai da «main».
- **Impronta controllata a ogni uso.** In `bot/esperti/INDICE.json` c'è lo `sha256` di ogni file; se un file è cambiato (a mano o per errore) **non si usa** e il pannello lo segna «impronta non valida».
- **Nessun potere.** Anche se un ruolo contenesse istruzioni scorrette, la chiamata non ha strumenti: al peggio produce un cattivo consiglio, che il manager tratta come ipotesi.
- **Nessun segreto in uscita**: richiesta, contesto e risposta passano dal filtro di oscuramento.
- Nel registro si scrive **solo quale esperto** è stato interpellato, mai la domanda.

## Aggiornare o aggiungere esperti (per chi sviluppa)
```
python scripts/importa_esperti.py              # riscarica l'elenco scelto dal commit fissato
python scripts/importa_esperti.py <commit>     # per passare a un commit più nuovo
```
Per aggiungerne uno: aggiungi il percorso a `SCELTI` nello script, rilancia, **leggi il file importato prima di fare commit**, e controlla che non chieda di pubblicare o fare scraping. Il test controlla che indice, script e file coincidano.

## Crediti e licenza
I ruoli sono del progetto [agency-agents](https://github.com/msitarzewski/agency-agents), licenza MIT, © 2025 AgentLand Contributors. Il testo della licenza è in [`bot/esperti/LICENSE-agency-agents.txt`](../bot/esperti/LICENSE-agency-agents.txt) e l'origine esatta (repository e commit) in `bot/esperti/INDICE.json`.
