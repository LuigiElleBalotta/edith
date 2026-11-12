"""Rigenera bot/catalogo/INDICE.json: l'impronta (sha256) di ogni estensione del catalogo.

Va lanciato dopo ogni modifica a un file del catalogo. Il test controlla che l'indice sia aggiornato:
una estensione con impronta diversa non si installa (protezione contro file cambiati a mano).

    python scripts/aggiorna_catalogo.py
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bot"))

from app import extensions  # noqa: E402


def main() -> int:
    d = os.path.join(ROOT, "bot", "catalogo")
    indice = {}
    for n in sorted(os.listdir(d)):
        if not n.endswith(".json") or n == "INDICE.json":
            continue
        with open(os.path.join(d, n), "rb") as f:
            raw = f.read()
        m = json.loads(raw.decode("utf-8"))
        extensions.validate_manifest(m)  # un manifest non valido non entra nel catalogo
        indice[m["id"]] = hashlib.sha256(raw).hexdigest()
    with open(os.path.join(d, "INDICE.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(indice, f, indent=2, sort_keys=True)
        f.write(chr(10))
    print(f"catalogo: {len(indice)} estensioni")
    return 0


if __name__ == "__main__":
    sys.exit(main())
