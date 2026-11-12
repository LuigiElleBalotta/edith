#!/usr/bin/env python3
"""Cerca segreti nei file del repository (token, chiavi, password). Usato dalla CI e come controllo prima di ogni commit.
   python scripts/check_secrets.py            # controlla i file tracciati da git (o tutta la cartella se non c'è git)
Esce con 1 se trova qualcosa. Mostra solo file, riga e tipo: mai il valore."""
import os
import re
import subprocess
import sys

PATTERNS = {
    "token bot Telegram": r"\b\d{8,10}:[A-Za-z0-9_-]{35,}\b",
    "token Meta/Instagram": r"\bEAA[A-Za-z0-9]{30,}",
    "chiave API (sk-...)": r"\bsk-[A-Za-z0-9_-]{20,}",
    "token GitHub": r"\b(ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}",
    "chiave privata": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "chiave AWS": r"\bAKIA[0-9A-Z]{16}\b",
    "assegnazione sospetta": r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*['\"]?(?!\s|['\"]|metti|tuo|your|xxx|\*|<|\$|\{|example|changeme|chiave|token-|codice|os\.|secrets\.|self\.|cfg\.|env|getpass|input|args)[A-Za-z0-9/+_.!@#%^&*-]{12,}",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules", "private", "data", "accounts"}
SKIP_FILES = {"check_secrets.py"}
TEXT_EXT = {".py", ".md", ".yml", ".yaml", ".json", ".sh", ".txt", ".env", ".example", ".toml", ".cfg", ".ini", ""}


def files(root):
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout.split("\n")
        return [os.path.join(root, f) for f in out if f]
    except (OSError, subprocess.CalledProcessError):
        res = []
        for d, ds, fs in os.walk(root):
            ds[:] = [x for x in ds if x not in SKIP_DIRS]
            res += [os.path.join(d, f) for f in fs]
        return res


def scan(root):
    found = []
    for p in files(root):
        if os.path.basename(p) in SKIP_FILES or os.path.splitext(p)[1] not in TEXT_EXT or not os.path.isfile(p):
            continue
        try:
            text = open(p, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.split("\n"), 1):
            for what, rx in PATTERNS.items():
                if re.search(rx, line):
                    found.append((os.path.relpath(p, root), n, what))
    return found


if __name__ == "__main__":
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    res = scan(root)
    for f, n, what in res:
        print(f"{f}:{n}: possibile {what}")
    print("Nessun segreto trovato." if not res else f"\n{len(res)} problemi: rimuovi il valore, poi cambia il segreto (è già nella cronologia se è stato committato).")
    sys.exit(1 if res else 0)
