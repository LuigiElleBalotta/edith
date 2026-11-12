"""Memoria persistente (SQLite). Sopravvive a riavvii e cambi di sessione."""
import os
import re
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  role TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'conversazione', content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL,
  payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'in_attesa');
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS media(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, file_unique_id TEXT,
  name TEXT, mime TEXT, size INTEGER, sha256 TEXT, path TEXT, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS content_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, platform TEXT NOT NULL,
  original_url TEXT, song TEXT, original_artist TEXT, published_at TEXT, media_type TEXT,
  caption TEXT, metrics_json TEXT, file_location TEXT, status TEXT NOT NULL,
  reuse_potential TEXT, notes TEXT, source TEXT NOT NULL, verified_at TEXT, media_id INTEGER);
CREATE TABLE IF NOT EXISTS opportunities(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, name TEXT NOT NULL, source_url TEXT NOT NULL,
  description TEXT, location TEXT, eligibility TEXT, deadline TEXT, costs TEXT, credibility TEXT,
  relevance TEXT, benefits TEXT, next_action TEXT, last_verified TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'da_valutare');
CREATE TABLE IF NOT EXISTS ig_daily(
  day TEXT NOT NULL, metric TEXT NOT NULL, value REAL, PRIMARY KEY(day, metric));
CREATE TABLE IF NOT EXISTS ig_period(
  start TEXT NOT NULL, end TEXT NOT NULL, metric TEXT NOT NULL, breakdown TEXT NOT NULL DEFAULT '',
  data TEXT NOT NULL, PRIMARY KEY(start, end, metric, breakdown));
CREATE TABLE IF NOT EXISTS ig_audience(
  day TEXT NOT NULL, metric TEXT NOT NULL, breakdown TEXT NOT NULL, data TEXT NOT NULL,
  PRIMARY KEY(day, metric, breakdown));
CREATE TABLE IF NOT EXISTS ig_media_stats(
  content_id INTEGER NOT NULL, day TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(content_id, day));
CREATE TABLE IF NOT EXISTS ig_comments(
  comment_id TEXT PRIMARY KEY, content_id INTEGER NOT NULL, ts TEXT, text TEXT, likes INTEGER);
CREATE TABLE IF NOT EXISTS ig_tags(
  media_id TEXT PRIMARY KEY, ts TEXT, permalink TEXT, caption TEXT);
CREATE TABLE IF NOT EXISTS ig_stories(
  story_id TEXT PRIMARY KEY, posted TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ped_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, plan TEXT NOT NULL, day TEXT NOT NULL,
  format TEXT, kind TEXT, title TEXT NOT NULL, song TEXT, artist TEXT, goal TEXT, reason TEXT,
  status TEXT NOT NULL DEFAULT 'proposto');
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL,
  source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'dichiarato_dal_proprietario');
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, due TEXT NOT NULL, instruction TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'in_attesa', attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, topic TEXT, text TEXT NOT NULL, why TEXT,
  status TEXT NOT NULL DEFAULT 'in_coda', asked_ts REAL, reminded INTEGER NOT NULL DEFAULT 0, answer TEXT);
CREATE TABLE IF NOT EXISTS appunti(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, tag TEXT NOT NULL, text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'attivo');
CREATE TABLE IF NOT EXISTS contacts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, name TEXT NOT NULL, kind TEXT, source_url TEXT NOT NULL,
  notes TEXT, status TEXT NOT NULL DEFAULT 'da_valutare');
CREATE TABLE IF NOT EXISTS watch(
  username TEXT PRIMARY KEY, ts REAL NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS lezioni(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, testo TEXT NOT NULL, fonte TEXT,
  ripetizioni INTEGER NOT NULL DEFAULT 1, stato TEXT NOT NULL DEFAULT 'nuova', riproponi_dopo REAL);
CREATE TABLE IF NOT EXISTS ext_timers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, due REAL NOT NULL, ext TEXT NOT NULL,
  message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'in_attesa', attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS fonti(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, titolo TEXT NOT NULL, tipo TEXT NOT NULL, origine TEXT,
  sha256 TEXT, pagine INTEGER NOT NULL DEFAULT 0, pezzi INTEGER NOT NULL DEFAULT 0, stato TEXT NOT NULL DEFAULT 'nuova',
  riassunto TEXT, principi INTEGER NOT NULL DEFAULT 0, nota TEXT, chiave TEXT);
CREATE TABLE IF NOT EXISTS pezzi(
  id INTEGER PRIMARY KEY AUTOINCREMENT, fonte_id INTEGER NOT NULL, ordine INTEGER NOT NULL, pagina INTEGER NOT NULL DEFAULT 0,
  titolo TEXT, testo TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS pezzi_fonte ON pezzi(fonte_id);
CREATE TABLE IF NOT EXISTS mail_inviate(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, contact_id INTEGER, to_addr TEXT NOT NULL, subject TEXT NOT NULL,
  body TEXT NOT NULL, token TEXT NOT NULL, tracking INTEGER NOT NULL DEFAULT 0, aperture INTEGER NOT NULL DEFAULT 0,
  prima_apertura REAL, ultima_apertura REAL);
CREATE INDEX IF NOT EXISTS mail_token ON mail_inviate(token);
CREATE TABLE IF NOT EXISTS mail_blocco(addr TEXT PRIMARY KEY, ts REAL NOT NULL, motivo TEXT);
CREATE TABLE IF NOT EXISTS watch_snap(
  username TEXT NOT NULL, day TEXT NOT NULL, followers INTEGER, media_count INTEGER, avg_likes REAL, avg_comments REAL,
  PRIMARY KEY(username, day));
"""


CONTENT_STATUSES = ("pubblicato", "non_pubblicato", "pronto_per_la_pubblicazione", "da_montare",
                    "da_rilanciare", "da_riutilizzare", "materiale_portfolio", "archiviato",
                    # interni: contenuto importato, non ancora separato tra musica e personale
                    "da_classificare", "personale_non_gestito")
OPPORTUNITY_STATUSES = ("da_valutare", "consigliata", "scartata", "bozza_pronta", "inviata", "scaduta")


class Db:
    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "manager.sqlite")
        self.profile_dir = data_dir  # dove sta profile.json (l'account può tenerlo altrove)
        self.slug = os.path.basename(os.path.normpath(data_dir))  # nome dell'account (chi crea il Db può impostarlo)
        self.ext_root = os.environ.get("EXTENSIONS_DIR", "/extensions")  # cartella delle estensioni, FUORI dal contenitore
        self.hooks = {}  # azioni da fare DOPO un'approvazione, per questo account
        self._lock = threading.Lock()
        self._c = sqlite3.connect(self.path, check_same_thread=False)
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.executescript(SCHEMA)
        self.fts = True  # ricerca testuale della Biblioteca (SQLite FTS5); se manca si ripiega su una ricerca più semplice
        try:
            self._c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS pezzi_fts USING fts5(testo, titolo, tokenize='unicode61 remove_diacritics 2')")
        except sqlite3.OperationalError:
            self.fts = False
        self._migrate()
        self._c.commit()

    def _migrate(self):
        # nome neutro per le informazioni dette dal proprietario (nelle versioni precedenti il nome era legato a una persona)
        for t, in self._c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            cols = [r[1] for r in self._c.execute(f"PRAGMA table_info({t})")]
            if "source" in cols:
                self._c.execute(f"UPDATE {t} SET source='dichiarato_dal_proprietario' WHERE source='dichiarato_da_luigi'")
        """Aggiunge le colonne nuove alle tabelle già esistenti (i database vecchi non si perdono)."""
        have = {r[1] for r in self._c.execute("PRAGMA table_info(contacts)").fetchall()}
        for col, typ in (("handle", "TEXT"), ("channel", "TEXT"), ("priority", "INTEGER"), ("next_followup", "TEXT"),
                         ("last_contact", "TEXT"), ("contact_count", "INTEGER NOT NULL DEFAULT 0"), ("last_reminder", "TEXT"),
                         ("email", "TEXT"), ("phone", "TEXT"), ("zone", "TEXT")):
            if col not in have:
                self._c.execute(f"ALTER TABLE contacts ADD COLUMN {col} {typ}")

    def close(self):
        with self._lock:
            self._c.close()

    def _x(self, sql, args=()):
        with self._lock:
            cur = self._c.execute(sql, args)
            self._c.commit()
            return cur

    # --- conversazione ---
    def add_message(self, role: str, content: str, kind: str = "conversazione"):
        self._x("INSERT INTO messages(ts,role,kind,content) VALUES(?,?,?,?)",
                (time.time(), role, kind, content))

    def history(self, n: int):
        rows = self._x("SELECT role,content FROM messages ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    # --- chiave/valore (offset Telegram, pausa, ecc.) ---
    def get(self, key: str, default: str = "") -> str:
        r = self._x("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set(self, key: str, value: str):
        self._x("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))

    # --- lezioni: cose imparate dal bot (le regole proposte passano sempre dall'approvazione) ---
    @staticmethod
    def _lnorm(t: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (t or "").lower())).strip()

    def lesson_add(self, testo: str, fonte: str = ""):
        """Ritorna (id, stato, nuova). Una lezione già nota aumenta le ripetizioni; una scartata per sempre non rientra."""
        t = (testo or "").strip()[:400]
        n = self._lnorm(t)
        for lid, txt, stato in self._x("SELECT id,testo,stato FROM lezioni").fetchall():
            if self._lnorm(txt) == n:
                if stato != "mai_piu":
                    self._x("UPDATE lezioni SET ripetizioni=ripetizioni+1 WHERE id=?", (lid,))
                return lid, stato, False
        cur = self._x("INSERT INTO lezioni(ts,testo,fonte) VALUES(?,?,?)", (time.time(), t, (fonte or "")[:300]))
        return cur.lastrowid, "nuova", True

    def lessons_list(self, stato: str = "", limit: int = 30):
        """stato: '' tutte tranne mai_piu; 'da_riproporre' = nuove o rifiutate da abbastanza tempo."""
        q = "SELECT id,ts,testo,fonte,ripetizioni,stato,riproponi_dopo FROM lezioni WHERE stato!='mai_piu'"
        a = []
        if stato == "da_riproporre":
            q += " AND (stato='nuova' OR (stato='rifiutata' AND COALESCE(riproponi_dopo,0)<=?))"
            a.append(time.time())
        elif stato:
            q = "SELECT id,ts,testo,fonte,ripetizioni,stato,riproponi_dopo FROM lezioni WHERE stato=?"
            a.append(stato)
        rows = self._x(q + " ORDER BY ripetizioni DESC, id DESC LIMIT ?", (*a, limit)).fetchall()
        return [dict(zip(("id", "ts", "testo", "fonte", "ripetizioni", "stato", "riproponi_dopo"), r)) for r in rows]

    def lesson_get(self, lid: int):
        r = self._x("SELECT id,ts,testo,fonte,ripetizioni,stato,riproponi_dopo FROM lezioni WHERE id=?", (lid,)).fetchone()
        return dict(zip(("id", "ts", "testo", "fonte", "ripetizioni", "stato", "riproponi_dopo"), r)) if r else None

    def lesson_set(self, lid: int, stato: str, riproponi_dopo: float = None) -> bool:
        if stato not in ("nuova", "proposta", "adottata", "rifiutata", "scartata", "mai_piu"):
            raise ValueError("stato lezione non valido")
        return self._x("UPDATE lezioni SET stato=?, riproponi_dopo=? WHERE id=?", (stato, riproponi_dopo, lid)).rowcount > 0

    # --- timer delle estensioni (messaggio al proprietario a un'ora precisa) ---
    def timer_add(self, ext: str, due: float, message: str) -> int:
        return self._x("INSERT INTO ext_timers(ts,due,ext,message) VALUES(?,?,?,?)", (time.time(), due, ext, message[:300])).lastrowid

    def timers_due(self, now: float):
        return self._x("SELECT id,ext,message,attempts FROM ext_timers WHERE status='in_attesa' AND due<=? ORDER BY due", (now,)).fetchall()

    def timer_set(self, tid: int, status: str, attempts: int = None):
        self._x("UPDATE ext_timers SET status=?, attempts=COALESCE(?,attempts) WHERE id=?", (status, attempts, tid))

    # --- audit ---
    def audit(self, actor: str, action: str, detail: str = ""):
        self._x("INSERT INTO audit(ts,actor,action,detail) VALUES(?,?,?,?)",
                (time.time(), actor, action, detail[:500]))

    # --- media ---
    def add_media(self, **k):
        self._x("INSERT INTO media(ts,file_unique_id,name,mime,size,sha256,path,status) VALUES(?,?,?,?,?,?,?,?)",
                (time.time(), k.get("file_unique_id"), k.get("name"), k.get("mime"),
                 k.get("size"), k.get("sha256"), k.get("path"), k["status"]))

    # --- archivio contenuti (non dipende da Instagram) ---
    def add_content(self, platform: str, status: str, source: str, **k) -> int:
        """`source` = da dove viene l'informazione (es. 'instagram_api', 'dichiarato_dal_proprietario')."""
        if status not in CONTENT_STATUSES:
            raise ValueError(f"stato contenuto non valido: {status}")
        cols = ("original_url", "song", "original_artist", "published_at", "media_type", "caption",
                "metrics_json", "file_location", "reuse_potential", "notes", "verified_at", "media_id")
        vals = [k.get(c) for c in cols]
        cur = self._x(
            "INSERT INTO content_items(ts,platform,status,source," + ",".join(cols) + ") VALUES(?,?,?,?," +
            ",".join("?" * len(cols)) + ")", (time.time(), platform, status, source, *vals))
        return cur.lastrowid

    def content_url_exists(self, url: str) -> bool:
        return self._x("SELECT 1 FROM content_items WHERE original_url=? LIMIT 1", (url,)).fetchone() is not None

    def content_to_classify(self, limit: int = 40, exclude=()):
        ex = tuple(exclude)
        # Attenzione: "NOT IN (NULL)" non restituisce mai righe, quindi la clausola va omessa se vuota.
        cond = f" AND id NOT IN ({','.join('?' * len(ex))})" if ex else ""
        return self._x("SELECT id,caption,media_type,published_at FROM content_items "
                       f"WHERE status='da_classificare'{cond} ORDER BY id LIMIT ?",
                       (*ex, limit)).fetchall()

    def content_set_status(self, content_id: int, status: str, song=None, original_artist=None, note=None):
        if status not in CONTENT_STATUSES:
            raise ValueError(f"stato contenuto non valido: {status}")
        self._x("UPDATE content_items SET status=?, song=COALESCE(?,song), original_artist=COALESCE(?,original_artist), "
                "notes=COALESCE(notes,'') || COALESCE(?,'') WHERE id=?", (status, song, original_artist, note, content_id))

    def content_search(self, text: str = "", status: str = "", by_likes: bool = False, limit: int = 10):
        cond, args = [], []
        if text:
            cond.append("(caption LIKE ? OR song LIKE ? OR original_artist LIKE ?)")
            args += [f"%{text}%"] * 3
        if status:
            cond.append("status=?")
            args.append(status)
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        order = "CAST(json_extract(metrics_json,'$.likes') AS INTEGER) DESC" if by_likes else "published_at DESC"
        cur = self._x(f"SELECT * FROM content_items {where} ORDER BY {order} LIMIT ?", (*args, limit))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def instagram_id_for(self, ref: str):
        """Dal link del post all'id Instagram salvato in archivio (note: instagram_id=...)."""
        row = self._x("SELECT notes FROM content_items WHERE original_url=? LIMIT 1",
                      (ref.split('?')[0].rstrip('/') + '/',)).fetchone() or \
              self._x("SELECT notes FROM content_items WHERE original_url=? LIMIT 1", (ref,)).fetchone()
        m = re.search(r"instagram_id=(\d+)", (row[0] if row else "") or "")
        return m.group(1) if m else None

    # --- fatti dichiarati dal proprietario ---
    def add_fact(self, text: str, source: str = "dichiarato_dal_proprietario", status: str = "dichiarato_dal_proprietario") -> int:
        row = self._x("SELECT id FROM facts WHERE text=? LIMIT 1", (text,)).fetchone()
        if row:
            return row[0]
        return self._x("INSERT INTO facts(ts,text,source,status) VALUES(?,?,?,?)", (time.time(), text, source, status)).lastrowid

    def facts_list(self, limit: int = 30):
        return [r[0] for r in self._x("SELECT text FROM facts ORDER BY id LIMIT ?", (limit,)).fetchall()]

    def facts_with_ids(self, limit: int = 100):
        return [{"id": r[0], "testo": r[1], "stato": r[2]} for r in
                self._x("SELECT id,text,status FROM facts ORDER BY id LIMIT ?", (limit,)).fetchall()]

    def fact_delete(self, fact_id: int) -> bool:
        return self._x("DELETE FROM facts WHERE id=?", (fact_id,)).rowcount > 0

    def recent_user_texts(self, n: int = 8):
        return [r[0] for r in self._x("SELECT content FROM messages WHERE role='user' ORDER BY id DESC LIMIT ?", (n,)).fetchall()]

    # --- appunti del manager (idee, lezioni, tendenze, hashtag...) ---
    def note_add(self, tag: str, text: str) -> int:
        row = self._x("SELECT id FROM appunti WHERE tag=? AND text=? AND status='attivo' LIMIT 1", (tag, text)).fetchone()
        if row:
            return row[0]
        return self._x("INSERT INTO appunti(ts,tag,text) VALUES(?,?,?)", (time.time(), tag, text)).lastrowid

    def notes_list(self, tag: str = "", text: str = "", status: str = "attivo", limit: int = 30):
        cond, args = [], []
        for col, val in (("tag", tag), ("status", status)):
            if val:
                cond.append(f"{col}=?"); args.append(val)
        if text:
            cond.append("text LIKE ?"); args.append(f"%{text}%")
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        cur = self._x(f"SELECT id,tag,text,status,ts FROM appunti {where} ORDER BY id DESC LIMIT ?", (*args, limit))
        return [dict(zip(("id", "tag", "testo", "stato", "ts"), r)) for r in cur.fetchall()]

    def note_set_status(self, note_id: int, status: str) -> bool:
        return self._x("UPDATE appunti SET status=? WHERE id=?", (status, note_id)).rowcount > 0

    # --- contatti professionali pubblici (locali, organizzatori, artisti) ---
    CONTACT_STATUSES = ("da_valutare", "da_scrivere", "interessante", "in_attesa_risposta", "risposto", "scartato", "escluso", "contattato")

    def contact_add(self, name: str, kind: str, source_url: str, notes: str = "", handle: str = None, priority: int = None,
                    next_followup: str = None, status: str = "da_valutare", channel: str = None,
                    email: str = None, phone: str = None, zone: str = None) -> int:
        row = self._x("SELECT id FROM contacts WHERE source_url=? AND name=? LIMIT 1", (source_url, name)).fetchone()
        if row:
            return 0
        return self._x("INSERT INTO contacts(ts,name,kind,source_url,notes,status,handle,priority,next_followup,channel,email,phone,zone) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (time.time(), name, kind, source_url, notes, status, handle, priority, next_followup, channel, email, phone, zone)).lastrowid

    _CONTACT_COLS = "id,name,kind,source_url,notes,status,handle,channel,priority,next_followup,last_contact,contact_count,email,phone,zone"
    _CONTACT_KEYS = ("id", "nome", "tipo", "fonte", "note", "stato", "handle", "canale", "priorita", "prossima_azione_il",
                     "ultimo_contatto", "messaggi_inviati", "email", "telefono", "zona")

    def contacts_list(self, text: str = "", limit: int = 30, status: str = ""):
        cond, args = [], []
        if text:
            cond.append("(name LIKE ? OR kind LIKE ? OR notes LIKE ? OR handle LIKE ?)")
            args += [f"%{text}%"] * 4
        if status:
            cond.append("status=?"); args.append(status)
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        cur = self._x(f"SELECT {self._CONTACT_COLS} FROM contacts {where} ORDER BY COALESCE(priority,9), id DESC LIMIT ?", (*args, limit))
        return [dict(zip(self._CONTACT_KEYS, r)) for r in cur.fetchall()]

    def contact_get(self, contact_id: int):
        r = self._x(f"SELECT {self._CONTACT_COLS} FROM contacts WHERE id=?", (contact_id,)).fetchone()
        return dict(zip(self._CONTACT_KEYS, r)) if r else None

    def contact_update(self, contact_id: int, status: str = None, notes: str = None, next_followup: str = None) -> bool:
        return self._x("UPDATE contacts SET status=COALESCE(?,status), notes=COALESCE(?,notes), "
                       "next_followup=COALESCE(?,next_followup) WHERE id=?", (status, notes, next_followup, contact_id)).rowcount > 0

    def contact_sent(self, contact_id: int, today: str, followup_days: int = 14, channel: str = None) -> bool:
        """Registra che il messaggio è partito: ora si aspetta la risposta e il prossimo follow-up è tra N giorni."""
        import datetime as _d
        nxt = (_d.date.fromisoformat(today) + _d.timedelta(days=followup_days)).isoformat() if followup_days else None
        return self._x("UPDATE contacts SET status='in_attesa_risposta', last_contact=?, next_followup=?, "
                       "contact_count=contact_count+1, channel=COALESCE(?,channel) WHERE id=?",
                       (today, nxt, channel, contact_id)).rowcount > 0

    def contacts_due(self, today: str, limit: int = 20):
        """Da scrivere o da sollecitare: stato 'da_scrivere' o 'in_attesa_risposta' con data arrivata."""
        cur = self._x(f"SELECT {self._CONTACT_COLS} FROM contacts WHERE status IN ('da_scrivere','in_attesa_risposta') "
                      "AND next_followup IS NOT NULL AND next_followup<=? ORDER BY COALESCE(last_reminder,''), COALESCE(priority,9), next_followup LIMIT ?",
                      (today, limit))
        return [dict(zip(self._CONTACT_KEYS, r)) for r in cur.fetchall()]

    def contact_reminded(self, contact_id: int, today: str):
        self._x("UPDATE contacts SET last_reminder=? WHERE id=?", (today, contact_id))

    # --- posta inviata (dopo l'approvazione del proprietario) ---
    def mail_log(self, contact_id, to_addr: str, subject: str, body: str, token: str, tracking: bool) -> int:
        return self._x("INSERT INTO mail_inviate(ts,contact_id,to_addr,subject,body,token,tracking) VALUES(?,?,?,?,?,?,?)",
                       (time.time(), contact_id, to_addr, subject, body, token, 1 if tracking else 0)).lastrowid

    def mail_open(self, token: str) -> bool:
        """Registra l'apertura (solo l'ora: nessun IP, nessun programma di posta)."""
        now = time.time()
        return self._x("UPDATE mail_inviate SET aperture=aperture+1, prima_apertura=COALESCE(prima_apertura,?), ultima_apertura=? "
                       "WHERE token=? AND tracking=1", (now, now, token)).rowcount > 0

    def mail_today(self) -> int:
        import datetime as _d
        start = _d.datetime.combine(_d.date.today(), _d.time.min).timestamp()
        return self._x("SELECT COUNT(*) FROM mail_inviate WHERE ts>=?", (start,)).fetchone()[0]

    def mail_recent_to(self, addr: str, days: int = 14) -> int:
        return self._x("SELECT COUNT(*) FROM mail_inviate WHERE lower(to_addr)=lower(?) AND ts>=?", (addr, time.time() - days * 86400)).fetchone()[0]

    def mail_list(self, limit: int = 30, con_testo: bool = False) -> list:
        cur = self._x("SELECT id,ts,to_addr,subject,tracking,aperture,prima_apertura,contact_id" + (",body" if con_testo else "")
                      + " FROM mail_inviate ORDER BY id DESC LIMIT ?", (limit,))
        chiavi = ("id", "ts", "a", "oggetto", "tracciata", "aperture", "prima_apertura", "contatto") + (("testo",) if con_testo else ())
        return [dict(zip(chiavi, r)) for r in cur.fetchall()]

    def mail_blocked(self, addr: str) -> bool:
        return self._x("SELECT 1 FROM mail_blocco WHERE addr=?", ((addr or "").strip().lower(),)).fetchone() is not None

    def mail_block(self, addr: str, motivo: str = "") -> bool:
        return self._x("INSERT OR IGNORE INTO mail_blocco(addr,ts,motivo) VALUES(?,?,?)", ((addr or "").strip().lower(), time.time(), motivo[:200])).rowcount > 0

    # --- account da monitorare (concorrenti, artisti simili) ---
    def watch_add(self, username: str, note: str = "") -> bool:
        return self._x("INSERT OR IGNORE INTO watch(username,ts,note) VALUES(?,?,?)", (username, time.time(), note)).rowcount > 0

    def watch_remove(self, username: str) -> bool:
        return self._x("DELETE FROM watch WHERE username=?", (username,)).rowcount > 0

    def watch_list(self):
        return [dict(zip(("username", "nota"), r)) for r in self._x("SELECT username,note FROM watch ORDER BY ts").fetchall()]

    def watch_snap_save(self, username: str, day: str, followers, media_count, avg_likes, avg_comments):
        self._x("INSERT OR REPLACE INTO watch_snap VALUES(?,?,?,?,?,?)", (username, day, followers, media_count, avg_likes, avg_comments))

    def watch_snaps(self, username: str, limit: int = 12):
        cur = self._x("SELECT day,followers,media_count,avg_likes,avg_comments FROM watch_snap WHERE username=? "
                      "ORDER BY day DESC LIMIT ?", (username, limit))
        return [dict(zip(("giorno", "follower", "post_totali", "media_mi_piace", "media_commenti"), r)) for r in cur.fetchall()]

    # --- opportunità: lettura e aggiornamento ---
    def opportunities_list(self, status: str = "", limit: int = 30):
        where, args = ("WHERE status=?", [status]) if status else ("", [])
        cur = self._x(f"SELECT id,name,source_url,deadline,eligibility,costs,next_action,last_verified,status FROM opportunities "
                      f"{where} ORDER BY COALESCE(deadline,'9999') LIMIT ?", (*args, limit))
        return [dict(zip(("id", "nome", "fonte", "scadenza", "requisiti", "costi", "prossima_azione", "verificata_il", "stato"), r))
                for r in cur.fetchall()]

    def opportunity_update(self, opp_id: int, status: str = None, deadline: str = None, next_action: str = None) -> bool:
        if status is not None and status not in OPPORTUNITY_STATUSES:
            raise ValueError(f"stato opportunità non valido: {status}")
        return self._x("UPDATE opportunities SET status=COALESCE(?,status), deadline=COALESCE(?,deadline), "
                       "next_action=COALESCE(?,next_action) WHERE id=?", (status, deadline, next_action, opp_id)).rowcount > 0

    # --- PED: modifica di una voce ---
    def ped_item_update(self, item_id: int, **k) -> bool:
        allowed = {"status", "day", "title", "reason"}
        sets = {c: v for c, v in k.items() if c in allowed and v is not None}
        if not sets:
            return False
        return self._x("UPDATE ped_items SET " + ",".join(f"{c}=?" for c in sets) + " WHERE id=?",
                       (*sets.values(), item_id)).rowcount > 0

    # --- bozze (approvazioni) ---
    def approvals_list(self, status: str = "", limit: int = 15):
        import json as _j
        where, args = ("WHERE status=?", [status]) if status else ("", [])
        out = []
        for i, kind, payload, st, ts in self._x(
                f"SELECT id,kind,payload,status,ts FROM approvals {where} ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall():
            p = _j.loads(payload)
            out.append({"id": i, "tipo": kind, "stato": st, "titolo": p.get("titolo"), "testo": p.get("testo"),
                        "riferimento": p.get("riferimento")})
        return out

    # --- attività programmate dal manager (una tantum) ---
    def task_add(self, due: str, instruction: str) -> int:
        return self._x("INSERT INTO tasks(ts,due,instruction) VALUES(?,?,?)", (time.time(), due, instruction)).lastrowid

    def tasks_pending(self):
        return [dict(zip(("id", "due", "instruction", "attempts"), r)) for r in
                self._x("SELECT id,due,instruction,attempts FROM tasks WHERE status='in_attesa' ORDER BY due").fetchall()]

    def task_set(self, task_id: int, status: str, attempts: int = None):
        self._x("UPDATE tasks SET status=?, attempts=COALESCE(?,attempts) WHERE id=?", (status, attempts, task_id))

    # --- domande che il manager pone al proprietario ---
    def question_add(self, text: str, why: str = "", topic: str = "") -> int:
        """Mette in coda una domanda. Ritorna 0 se ce n'è già una uguale ancora aperta o se la coda è piena."""
        open_ = self._x("SELECT text FROM questions WHERE status IN ('in_coda','posta')").fetchall()
        if len(open_) >= 5 or any(o[0].strip().lower() == text.strip().lower() for o in open_):
            return 0
        return self._x("INSERT INTO questions(ts,topic,text,why) VALUES(?,?,?,?)",
                       (time.time(), topic, text, why)).lastrowid

    def question_get(self, status: str):
        cur = self._x("SELECT id,topic,text,why,asked_ts,reminded FROM questions WHERE status=? ORDER BY id LIMIT 1", (status,))
        r = cur.fetchone()
        return dict(zip(("id", "topic", "text", "why", "asked_ts", "reminded"), r)) if r else None

    def question_set(self, qid: int, status: str, answer: str = None, asked: bool = False, reminded: bool = False):
        self._x("UPDATE questions SET status=?, answer=COALESCE(?,answer), asked_ts=CASE WHEN ? THEN ? ELSE asked_ts END, "
                "reminded=CASE WHEN ? THEN 1 ELSE reminded END WHERE id=?",
                (status, answer, int(asked), time.time(), int(reminded), qid))

    def question_counts(self) -> dict:
        return {s: n for s, n in self._x("SELECT status,COUNT(*) FROM questions GROUP BY status").fetchall()}

    # --- piano editoriale (PED) ---
    def ped_replace(self, plan: str, items: list, keep: bool = False) -> int:
        """Inserisce le voci del piano; se keep=False sostituisce prima quelle ancora 'proposto'."""
        if not keep:
            self._x("DELETE FROM ped_items WHERE plan=? AND status='proposto'", (plan,))
        n = 0
        for it in items:
            self._x("INSERT INTO ped_items(ts,plan,day,format,kind,title,song,artist,goal,reason) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (time.time(), plan, it["day"], it.get("format"), it.get("kind"), it["title"], it.get("song"),
                     it.get("artist"), it.get("goal"), it.get("reason")))
            n += 1
        return n

    def ped_set_status(self, old: str, new: str, before_day: str = None) -> int:
        """Cambia lo stato delle voci del PED (es. proposto -> approvato; approvato e passato -> trascorso)."""
        if before_day:
            return self._x("UPDATE ped_items SET status=? WHERE status=? AND day<?", (new, old, before_day)).rowcount
        return self._x("UPDATE ped_items SET status=? WHERE status=?", (new, old)).rowcount

    def ped_list(self, plan: str = None, from_day: str = None, to_day: str = None):
        cond, args = [], []
        if plan:
            cond.append("plan=?"); args.append(plan)
        if from_day:
            cond.append("day>=?"); args.append(from_day)
        if to_day:
            cond.append("day<=?"); args.append(to_day)
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        cur = self._x(f"SELECT id,plan,day,format,kind,title,song,artist,goal,reason,status FROM ped_items {where} ORDER BY day,id", args)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def content_summary(self) -> dict:
        rows = self._x("SELECT status,COUNT(*) FROM content_items GROUP BY status").fetchall()
        return {s: n for s, n in rows}

    # --- opportunità professionali ---
    def add_opportunity(self, name: str, source_url: str, last_verified: str, **k) -> int:
        if not source_url or not last_verified:
            raise ValueError("ogni opportunità richiede fonte ufficiale e data di verifica")
        status = k.get("status", "da_valutare")
        if status not in OPPORTUNITY_STATUSES:
            raise ValueError(f"stato opportunità non valido: {status}")
        cols = ("description", "location", "eligibility", "deadline", "costs", "credibility",
                "relevance", "benefits", "next_action")
        cur = self._x(
            "INSERT INTO opportunities(ts,name,source_url,last_verified,status," + ",".join(cols) +
            ") VALUES(?,?,?,?,?," + ",".join("?" * len(cols)) + ")",
            (time.time(), name, source_url, last_verified, status, *[k.get(c) for c in cols]))
        return cur.lastrowid

    def opportunities_summary(self) -> dict:
        rows = self._x("SELECT status,COUNT(*) FROM opportunities GROUP BY status").fetchall()
        return {s: n for s, n in rows}

    def media_older_than(self, ts: float):
        return self._x("SELECT id,path FROM media WHERE status='salvato' AND ts<?", (ts,)).fetchall()

    def media_mark_deleted(self, media_id: int):
        self._x("UPDATE media SET status='eliminato', path=NULL WHERE id=?", (media_id,))

    # --- stato ---
    def paused(self) -> bool:
        return self.get("paused", "0") == "1"

    def counts(self) -> dict:
        out = {}
        for t in ("messages", "media", "approvals", "facts"):
            out[t] = self._x(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        out["approvals_pending"] = self._x(
            "SELECT COUNT(*) FROM approvals WHERE status='in_attesa'").fetchone()[0]
        return out
