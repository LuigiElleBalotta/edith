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
- riproponi_dopo_giorni: dopo quanti giorni il manager può riproporre una regola che hai rifiutato (predefinito 14);
- kb: {repo, branch, write_branch} archivio di conoscenza (la chiave di accesso è nell'ambiente, mai qui).
"""
import json
import os

DEFAULTS = {"proprietario": "", "ambito": "", "identita": "", "regole_extra": [], "strumenti_spenti": [], "lavori_spenti": [], "lavori": {}, "kb": {}, "utenti": {}, "benvenuto": "", "tastiera": [], "riproponi_dopo_giorni": 14}


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


def apply_rule(data_dir, azione: str, nuovo: str = "", vecchio: str = "") -> str:
    """Cambia SOLO regole_extra in profile.json (aggiungi / sostituisci / rimuovi). Scrittura atomica. Chiamata solo dopo l'approvazione."""
    import tempfile
    path = os.path.join(data_dir, "profile.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    regole = [str(r) for r in (data.get("regole_extra") or [])]
    nuovo, vecchio = (nuovo or "").strip()[:400], (vecchio or "").strip()[:400]
    low = [r.strip().lower() for r in regole]
    if azione == "aggiungi":
        if not nuovo:
            raise ValueError("manca il testo della regola")
        if nuovo.lower() in low:
            return "La regola c'era già."
        regole.append(nuovo)
    elif azione in ("sostituisci", "rimuovi"):
        if vecchio.lower() not in low:
            raise ValueError("la regola da cambiare non c'è più")
        i = low.index(vecchio.lower())
        if azione == "rimuovi":
            regole.pop(i)
        else:
            if not nuovo:
                raise ValueError("manca il testo della nuova regola")
            regole[i] = nuovo
    else:
        raise ValueError("azione non valida")
    data["regole_extra"] = regole
    os.makedirs(data_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=data_dir, prefix=".profile-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(chr(10))
    os.replace(tmp, path)
    return "Regola aggiornata."
