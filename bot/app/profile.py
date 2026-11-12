"""Profilo dell'account gestito da questa istanza: chi è, che regole ha, cosa è acceso.

Ogni account ha la sua istanza del manager (suo bot Telegram, suoi dati, suoi segreti) e un file
`profile.json` nella cartella dei dati. Senza file valgono i valori predefiniti (comportamento generico).

Campi (tutti facoltativi):
- proprietario: nome di chi gestisce l'account (come lo chiama il manager);
- ambito: cosa conta come pertinente per l'account quando si classificano i contenuti (predefinito: musica);
- identita: testo che sostituisce la presentazione iniziale del manager (chi sei, per chi lavori, come parli);
- regole_extra: elenco di regole in più, aggiunte a quelle ferree (che restano sempre);
- strumenti_spenti: nomi di strumenti da togliere;
- lavori_spenti: nomi dei lavori automatici da non far partire;
- benvenuto: frase iniziale di /start (la lista dei comandi segue sempre);
- tastiera: tasti rapidi sotto la barra di scrittura, elenco di righe di comandi (es. [["/contatti", "/agenda"]]);
- utenti: {"ID Telegram": "Nome"} per sapere chi parla quando il bot ha più proprietari;
- lavori: lavori automatici propri dell'account {nome: {weekday|None, hour, minute, prompt, reason, deliver, cond}};
- kb: {repo, branch, write_branch} archivio di conoscenza (la chiave di accesso è nell'ambiente, mai qui).
"""
import json
import os

DEFAULTS = {"proprietario": "", "ambito": "", "identita": "", "regole_extra": [], "strumenti_spenti": [], "lavori_spenti": [], "lavori": {}, "kb": {}, "utenti": {}, "benvenuto": "", "tastiera": []}


def load(data_dir) -> dict:
    out = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in DEFAULTS.items()}
    if not data_dir:
        return out
    try:
        with open(os.path.join(data_dir, "profile.json"), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return out
    if not isinstance(raw, dict):
        return out
    for k in out:
        if k in raw and isinstance(raw[k], type(out[k])):
            out[k] = raw[k]
    return out
