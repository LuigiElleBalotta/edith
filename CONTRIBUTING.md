# Contribuire

Grazie! Qualche regola semplice, che nasce dal fatto che questo programma lavora su account veri.

1. **Mai scrittura verso l'esterno senza approvazione.** Una funzione che pubblica, commenta, scrive o si candida non entra, a meno di essere dietro un'approvazione a bottoni, `guard.py` e un test che lo dimostra.
2. **Mai segreti nel repository.** `python scripts/check_secrets.py` deve passare.
3. **Mai inventare.** Il manager distingue fatto verificato / detto dal proprietario / ipotesi. Un cambiamento che rende più facile inventare non entra.
4. **Solo libreria standard** di Python, salvo ottime ragioni: il contenitore resta piccolo.
5. **Test.** `cd bot && python -I -m unittest discover -s tests` (nessuna rete: le chiamate esterne si simulano).
6. Messaggi per le persone **in italiano semplice**, senza gergo.

7. **Nessun dato personale** (nomi, ID, email, domini privati) nei file né nella storia dei commit: gli esempi sono inventati.

Le regole complete e la mappa del codice sono in [CLAUDE.md](CLAUDE.md).

Per cambiamenti grandi apri prima una issue.
