"""Archivio di conoscenza (knowledge base) di un account: un repository git di file di testo (analisi, regole,
calendario, tabelle CSV...) che il manager studia, tiene aggiornato e consulta.

Regole di sicurezza (valgono per ogni account):
- si legge SOLO testo; `secrets/`, `.env`, chiavi, `.git`, `.github` non si leggono e non si scrivono mai;
- ogni scrittura passa da un'anteprima (diff) e da un'approvazione del proprietario con i bottoni;
- si scrive sul ramo configurato (predefinito `manager`, mai `main` se non scelto dal proprietario);
- il codice che fa girare l'automazione (`ops/gateway`, `ops/bridge`) non è modificabile da qui.
"""
import difflib
import os
import subprocess
from pathlib import Path


class KbError(Exception):
    pass


class KnowledgeBase:
    DENY_TOP = {".git", ".github", "secrets", "inbox", "node_modules", "__pycache__"}
    DENY_PREFIX = ("data/raw", "data/private", "ops/gateway", "ops/bridge")
    DENY_NAMES = (".env", "id_rsa", "id_ed25519", "write_key", "known_hosts", "credentials")
    READ_EXT = {".md", ".txt", ".csv", ".json", ".yml", ".yaml", ".ics", ".py", ".js", ".css", ".html", ".toml", ".sql", ".tsv"}
    MAX_READ = 130_000
    MAX_FILE_WRITE = 400_000

    def __init__(self, root: str, repo: str = "", key: str = "", read_branch: str = "main", write_branch: str = "manager",
                 author: str = "Manager (bot)", runner=None):
        self.root = Path(root)
        self.repo, self.key = repo, key
        self.read_branch, self.write_branch, self.author = read_branch, write_branch, author
        self._run = runner or subprocess.run

    # --- git ---
    def _env(self):
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.root.parent), "GIT_TERMINAL_PROMPT": "0",
               "GIT_AUTHOR_NAME": self.author, "GIT_COMMITTER_NAME": self.author,
               "GIT_AUTHOR_EMAIL": "manager@localhost", "GIT_COMMITTER_EMAIL": "manager@localhost"}
        if self.key:
            kh = self.root.parent / "known_hosts"
            env["GIT_SSH_COMMAND"] = (f"ssh -i {self.key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "
                                      f"-o UserKnownHostsFile={kh} -o BatchMode=yes")
        return env

    def _git(self, *args, cwd=None, check=True) -> str:
        try:
            p = self._run(["git", *args], cwd=str(cwd or self.root), env=self._env(), capture_output=True, text=True, timeout=120)
        except Exception as e:  # git assente, timeout...
            raise KbError(f"git non utilizzabile: {type(e).__name__}") from None
        if check and p.returncode != 0:
            raise KbError((p.stderr or p.stdout or "errore git").strip().splitlines()[-1][:300])
        return (p.stdout or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.repo)

    def head(self) -> str:
        return self._git("rev-parse", "--short", "HEAD") if (self.root / ".git").exists() else ""

    def sync(self) -> dict:
        """Porta la copia locale all'ultimo stato del ramo principale. Ritorna {commit, precedente, file_cambiati, data}."""
        if not self.configured:
            raise KbError("archivio non configurato per questo account")
        before = ""
        if not (self.root / ".git").exists():
            self.root.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--quiet", "--branch", self.read_branch, self.repo, str(self.root), cwd=self.root.parent)
        else:
            before = self._git("rev-parse", "HEAD")
            self._git("fetch", "--quiet", "origin")
            self._git("checkout", "--quiet", "-f", self.read_branch)
            self._git("reset", "--quiet", "--hard", f"origin/{self.read_branch}")
        after = self._git("rev-parse", "HEAD")
        changed = []
        if before and before != after:
            changed = [f for f in self._git("diff", "--name-only", before, after).splitlines() if f and self._allowed(f, write=False)]
        return {"commit": after[:7], "precedente": before[:7], "file_cambiati": changed,
                "data": self._git("log", "-1", "--format=%cd", "--date=format:%d/%m/%Y %H:%M")}

    # --- percorsi ---
    def _allowed(self, rel: str, write: bool) -> bool:
        parts = Path(rel).parts
        if not parts or ".." in parts or Path(rel).is_absolute():
            return False
        if parts[0] in self.DENY_TOP or any(p in self.DENY_TOP for p in parts):
            return False
        low = rel.replace("\\", "/").lower()
        if any(low == d or low.startswith(d + "/") for d in self.DENY_PREFIX):
            return False
        if any(n in Path(rel).name.lower() for n in self.DENY_NAMES):
            return False
        return True

    def _path(self, rel: str, write: bool = False) -> Path:
        rel = (rel or "").strip().lstrip("/").replace("\\", "/")
        if rel and not self._allowed(rel, write):
            raise KbError("percorso non consentito (riservato o fuori dall'archivio)")
        p = (self.root / rel).resolve()
        if self.root.resolve() not in (p, *p.parents):
            raise KbError("percorso fuori dall'archivio")
        return p

    # --- lettura ---
    def listdir(self, rel: str = "") -> list:
        p = self._path(rel)
        if not p.is_dir():
            raise KbError("non è una cartella")
        out = []
        for c in sorted(p.iterdir()):
            r = (Path(rel) / c.name).as_posix()
            if not self._allowed(r, False):
                continue
            out.append({"nome": c.name + ("/" if c.is_dir() else ""), "byte": c.stat().st_size if c.is_file() else None})
        return out

    def read(self, rel: str) -> str:
        p = self._path(rel)
        if not p.is_file():
            raise KbError("file non trovato")
        if p.suffix.lower() not in self.READ_EXT:
            raise KbError("tipo di file non leggibile (solo testo)")
        data = p.read_text(encoding="utf-8", errors="replace")
        if len(data) > self.MAX_READ:
            return data[: self.MAX_READ] + f"\n[... file lungo {len(data)} caratteri: letto fino a {self.MAX_READ}; usa kb_cerca per il resto ...]"
        return data

    def search(self, text: str, limit: int = 40) -> list:
        needle = (text or "").strip().lower()
        if len(needle) < 2:
            raise KbError("testo da cercare troppo corto")
        hits = []
        for f in sorted(self.root.rglob("*")):
            if len(hits) >= limit:
                break
            if not f.is_file() or f.suffix.lower() not in self.READ_EXT:
                continue
            rel = f.relative_to(self.root).as_posix()
            if not self._allowed(rel, False):
                continue
            try:
                for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if needle in line.lower():
                        hits.append({"file": rel, "riga": n, "testo": line.strip()})
                        if len(hits) >= limit:
                            break
            except OSError:
                continue
        return hits

    # --- scrittura (solo dopo approvazione) ---
    def prepare(self, rel: str, contenuto: str = None, vecchio: str = None, nuovo: str = None):
        """Calcola il nuovo testo del file e l'anteprima (diff). Non scrive nulla. Ritorna (nuovo_testo, diff)."""
        p = self._path(rel, write=True)
        if p.suffix.lower() not in self.READ_EXT:
            raise KbError("si possono modificare solo file di testo")
        old = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        if vecchio is not None:
            if old.count(vecchio) != 1:
                raise KbError("il testo da sostituire non compare esattamente una volta nel file" if vecchio in old else
                              "il testo da sostituire non si trova nel file")
            new = old.replace(vecchio, nuovo or "", 1)
        elif contenuto is not None:
            new = contenuto
        else:
            raise KbError("indica il contenuto nuovo oppure testo_da_sostituire e nuovo_testo")
        if len(new) > self.MAX_FILE_WRITE:
            raise KbError("file troppo grande")
        if new == old:
            raise KbError("nessuna differenza: il file è già così")
        diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}", n=2))
        return new, diff

    def apply(self, rel: str, new_text: str, message: str) -> str:
        """Scrive il file e lo pubblica sul ramo di scrittura. Ritorna 'ramo@commit'."""
        if not self.configured:
            raise KbError("archivio non configurato")
        self._path(rel, write=True)
        self.sync()  # parto sempre dall'ultimo stato
        wb = self.write_branch
        if wb != self.read_branch:
            self._git("checkout", "--quiet", "-B", wb, f"origin/{self.read_branch}")
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_text, encoding="utf-8", newline="")
        self._git("add", "--", rel)
        self._git("commit", "--quiet", "-m", message[:200])
        try:
            if wb != self.read_branch:
                self._git("push", "--quiet", "--force-with-lease", "origin", wb)
            else:
                self._git("push", "--quiet", "origin", self.read_branch)
        finally:
            self._git("checkout", "--quiet", "-f", self.read_branch, check=False)
        return f"{wb}@{self._git('rev-parse', '--short', wb)}"
