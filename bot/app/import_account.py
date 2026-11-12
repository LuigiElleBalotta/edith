"""Importa nel database TUTTO ciò che Instagram permette di leggere dell'account (sola lettura).

Regole di privacy (le stesse di SECURITY.md):
- statistiche e commenti per singolo contenuto SOLO per i contenuti 'pubblicato' (musica); mai per personale/da classificare;
- dei commenti si salvano testo, data e mi piace: NON i nomi di chi li ha scritti;
- delle storie si salvano solo i numeri (nessuna immagine, nessun testo): spariscono dopo 24 ore e così se ne costruisce lo storico;
- delle persone nel pubblico si salvano solo totali per fascia (età, genere, paese, città).

Uso:  python -m app.import_account            (completo: 24 mesi di storia)
      python -m app.import_account --rapido   (incrementale: quello che si usa ogni giorno)
"""
import datetime as dt
import json
import re
import sys
import time

from . import config as cfgmod
from .db import Db
from .instagram import IgError, Instagram

D = 86400
WEEK_METRICS = ("views", "accounts_engaged", "total_interactions", "likes", "comments", "shares", "saves",
                "replies", "profile_links_taps", "follows_and_unfollows", "profile_views")
REEL_METRICS = ("reach", "views", "saved", "shares", "total_interactions", "likes", "comments",
                "ig_reels_avg_watch_time", "ig_reels_video_view_total_time")
BASE_METRICS = ("reach", "views", "saved", "shares", "total_interactions", "likes", "comments")
MIN_METRICS = ("reach", "saved", "shares", "total_interactions")
STORY_METRICS = ("reach", "views", "shares", "replies", "total_interactions", "follows", "profile_visits", "navigation")
SNAP_BREAKDOWNS = (("reach", "media_product_type"), ("reach", "follow_type"),
                   ("views", "media_product_type"), ("views", "follow_type"))
DEMOGRAPHICS = ("age", "gender", "country", "city")


def _day(end_time: str) -> str:
    """end_time di Instagram = fine del giorno misurato: il giorno di riferimento è quello precedente."""
    d = dt.datetime.strptime(end_time[:10], "%Y-%m-%d").date() - dt.timedelta(days=1)
    return d.isoformat()


class Importer:
    def __init__(self, db: Db, ig: Instagram, pause: float = 0.15):
        self.db, self.ig, self.pause = db, ig, pause
        self.counts, self.errors = {}, []

    def _try(self, label: str, path: str):
        time.sleep(self.pause)
        try:
            return self.ig.get(path)
        except IgError as e:
            if len(self.errors) < 25:
                self.errors.append(f"{label}: {str(e)[:110]}")
            return None

    def _n(self, k: str, n: int = 1):
        self.counts[k] = self.counts.get(k, 0) + n

    # ---------- profilo ----------
    def profile(self):
        r = self._try("profilo", f"{self.ig.user_id}?fields=username,name,biography,website,followers_count,"
                                 f"follows_count,media_count")
        if r:
            r.pop("id", None)
            r["letto_il"] = dt.date.today().isoformat()
            self.db.set("ig_profile", json.dumps(r, ensure_ascii=False))
            self._n("profilo")

    # ---------- serie giornaliere ----------
    def daily(self, months: int = 24):
        now = int(time.time())
        empty = 0
        for k in range(0, months + 1):
            until, since = now - 30 * k * D, max(now - 30 * (k + 1) * D, now - 725 * D)  # Instagram: massimo ~2 anni
            if until <= since:
                break
            r = self._try("reach giornaliera", f"{self.ig.user_id}/insights?metric=reach&period=day&since={since}&until={until}")
            vals = (((r or {}).get("data") or [{}])[0]).get("values") or []
            if not vals:
                empty += 1
                if empty >= 2:
                    break
                continue
            empty = 0
            for v in vals:
                self.db._x("INSERT OR REPLACE INTO ig_daily(day,metric,value) VALUES(?,?,?)",
                           (_day(v["end_time"]), "reach", v["value"]))
                self._n("giorni_copertura")
        r = self._try("follower_count", f"{self.ig.user_id}/insights?metric=follower_count&period=day&since={now - 29 * D}&until={now}")
        for v in (((r or {}).get("data") or [{}])[0]).get("values") or []:
            self.db._x("INSERT OR REPLACE INTO ig_daily(day,metric,value) VALUES(?,?,?)",
                       (_day(v["end_time"]), "follower_nuovi", v["value"]))
            self._n("giorni_follower")

    # ---------- totali settimanali ----------
    def weekly(self, weeks: int = 26):
        today = dt.date.today()
        monday = today - dt.timedelta(days=today.weekday())
        for w in range(1, weeks + 1):  # settimane complete: lun-dom
            start = monday - dt.timedelta(weeks=w)
            end = start + dt.timedelta(days=7)
            s = int(dt.datetime.combine(start, dt.time(), dt.timezone.utc).timestamp())
            e = int(dt.datetime.combine(end, dt.time(), dt.timezone.utc).timestamp())
            for m in WEEK_METRICS:
                if self.db._x("SELECT 1 FROM ig_period WHERE start=? AND metric=? AND breakdown=''",
                              (start.isoformat(), m)).fetchone():
                    continue
                r = self._try(f"settimana {m}", f"{self.ig.user_id}/insights?metric={m}&period=day&metric_type=total_value&since={s}&until={e}")
                tv = (((r or {}).get("data") or [{}])[0]).get("total_value")
                if tv is not None:
                    self.db._x("INSERT OR REPLACE INTO ig_period(start,end,metric,breakdown,data) VALUES(?,?,?,?,?)",
                               (start.isoformat(), end.isoformat(), m, "", json.dumps(tv)))
                    self._n("totali_settimanali")

    # ---------- istantanee 28 giorni con scomposizione ----------
    def snapshots(self):
        now = int(time.time())
        today = dt.date.today().isoformat()
        for m, b in SNAP_BREAKDOWNS:
            r = self._try(f"{m} per {b}", f"{self.ig.user_id}/insights?metric={m}&period=day&metric_type=total_value&breakdown={b}&since={now - 28 * D}&until={now}")
            tv = (((r or {}).get("data") or [{}])[0]).get("total_value")
            if tv:
                self.db._x("INSERT OR REPLACE INTO ig_period(start,end,metric,breakdown,data) VALUES(?,?,?,?,?)",
                           (today, today, m + "_28g", b, json.dumps(tv)))
                self._n("istantanee")

    # ---------- pubblico ----------
    def audience(self):
        today = dt.date.today().isoformat()
        for b in DEMOGRAPHICS:
            r = self._try(f"pubblico {b}", f"{self.ig.user_id}/insights?metric=follower_demographics&period=lifetime&metric_type=total_value&breakdown={b}")
            tv = (((r or {}).get("data") or [{}])[0]).get("total_value")
            res = (((tv or {}).get("breakdowns") or [{}])[0]).get("results") or []
            if res:
                rows = [{"valore": ", ".join(x.get("dimension_values", [])), "follower": x.get("value")} for x in res]
                self.db._x("INSERT OR REPLACE INTO ig_audience(day,metric,breakdown,data) VALUES(?,?,?,?)",
                           (today, "follower_demographics", b, json.dumps(rows, ensure_ascii=False)))
                self._n("fasce_pubblico")

    # ---------- statistiche dei singoli contenuti MUSICALI ----------
    def _targets(self, rapido: bool):
        rows = self.db._x("SELECT id,notes,media_type,published_at,metrics_json FROM content_items "
                          "WHERE status='pubblicato' ORDER BY published_at DESC").fetchall()
        today = dt.date.today()
        out = []
        for cid, notes, mtype, pub, mj in rows:
            m = re.search(r"instagram_id=(\d+)", notes or "")
            if not m:
                continue
            last = self.db._x("SELECT MAX(day) FROM ig_media_stats WHERE content_id=?", (cid,)).fetchone()[0]
            age = (today - dt.date.fromisoformat((pub or "2000-01-01")[:10])).days
            if (not last) \
                    or (rapido and age <= 45 and last < today.isoformat()) \
                    or (last < (today - dt.timedelta(days=30 if rapido else 7)).isoformat()):
                out.append((cid, m.group(1), mtype or "", mj))
        return out

    def media_stats(self, rapido: bool = False, limit: int = 400):
        today = dt.date.today().isoformat()
        for cid, iid, mtype, mj in self._targets(rapido)[:limit]:
            sets = (REEL_METRICS, BASE_METRICS, MIN_METRICS) if mtype.upper() in ("REELS", "VIDEO") else (BASE_METRICS, MIN_METRICS)
            data, err = None, ""
            for ms in sets:
                time.sleep(self.pause)
                try:
                    r = self.ig.get(f"{iid}/insights?metric={','.join(ms)}")
                    data = {d["name"]: (d["values"][0]["value"] if d.get("values") else None) for d in r.get("data", [])}
                    break
                except IgError as e:
                    err = str(e)
            if not data:
                # Instagram non fornisce statistiche per i post vecchi (prima dell'account professionale): lo segno,
                # così non si riprova ogni giorno (si ritenta dopo 30 giorni).
                self.db._x("INSERT OR REPLACE INTO ig_media_stats(content_id,day,data) VALUES(?,?,?)",
                           (cid, today, json.dumps({"_senza_statistiche": True})))
                self._n("contenuti_senza_statistiche")
                continue
            self.db._x("INSERT OR REPLACE INTO ig_media_stats(content_id,day,data) VALUES(?,?,?)",
                       (cid, today, json.dumps(data)))
            self._n("contenuti_con_statistiche")
            try:
                if (json.loads(mj or "{}").get("comments") or 0) > 0:
                    self.comments(cid, iid)
            except (ValueError, TypeError):
                pass

    def comments(self, cid: int, iid: str):
        r = self._try(f"commenti {iid}", f"{iid}/comments?fields=text,timestamp,like_count&limit=50")
        for c in (r or {}).get("data", []):
            self.db._x("INSERT OR REPLACE INTO ig_comments(comment_id,content_id,ts,text,likes) VALUES(?,?,?,?,?)",
                       (c["id"], cid, c.get("timestamp"), (c.get("text") or ""), c.get("like_count") or 0))
            self._n("commenti")

    # ---------- post in cui sei taggato ----------
    def tags(self, pages: int = 6):
        url = f"{self.ig.base}/{self.ig.user_id}/tags?fields=id,caption,timestamp,permalink&limit=25"
        for _ in range(pages):
            time.sleep(self.pause)
            try:
                r = self.ig._get(url)
            except IgError as e:
                self.errors.append(f"tag: {str(e)[:100]}")
                return
            for t in r.get("data", []):
                self.db._x("INSERT OR REPLACE INTO ig_tags(media_id,ts,permalink,caption) VALUES(?,?,?,?)",
                           (t["id"], t.get("timestamp"), t.get("permalink"), (t.get("caption") or "")))
                self._n("tag")
            url = (r.get("paging") or {}).get("next")
            if not url:
                return

    # ---------- storie (solo numeri) ----------
    def stories(self):
        r = self._try("storie", f"{self.ig.user_id}/stories?fields=id,timestamp")
        for s in (r or {}).get("data", []):
            data = None
            for ms in (STORY_METRICS, ("reach", "views", "shares", "replies"), ("reach",)):
                time.sleep(self.pause)
                try:
                    rr = self.ig.get(f"{s['id']}/insights?metric={','.join(ms)}")
                    data = {d["name"]: (d["values"][0]["value"] if d.get("values") else None) for d in rr.get("data", [])}
                    break
                except IgError:
                    continue
            if data is not None:
                self.db._x("INSERT OR REPLACE INTO ig_stories(story_id,posted,data) VALUES(?,?,?)",
                           (s["id"], s.get("timestamp"), json.dumps(data)))
                self._n("storie")

    def run(self, rapido: bool = False) -> dict:
        steps = [("profilo", self.profile), ("giornaliere", lambda: self.daily(2 if rapido else 24)),
                 ("settimanali", lambda: self.weekly(2 if rapido else 26)), ("istantanee", self.snapshots),
                 ("pubblico", self.audience), ("contenuti", lambda: self.media_stats(rapido)),
                 ("tag", self.tags), ("storie", self.stories)]
        for name, step in steps:
            try:
                step()
            except Exception as e:  # un passo che fallisce non ferma gli altri
                self.errors.append(f"{name}: {type(e).__name__}")
        self.db.set("import:ultimo", dt.datetime.now().isoformat(timespec="seconds"))
        self.db.set("import:errori", json.dumps(self.errors, ensure_ascii=False))  # il bot deve poterli spiegare
        self.db.audit("sistema", "import_account", json.dumps({"rapido": rapido, **self.counts, "errori": len(self.errors)}))
        return {"importati": self.counts, "errori": self.errors}


def sync_new_content(db: Db, ig: Instagram) -> dict:
    """Contenuti nuovi dell'account -> archivio (stato 'da_classificare')."""
    from .audit_instagram import import_media
    return import_media(db, ig, limit_total=200)


def main() -> int:
    cfg = cfgmod.load()
    token, uid = cfg.ig_token, cfg.ig_user_id
    if not token or not uid:
        print("META_IG_TOKEN / META_IG_USER_ID mancanti")
        return 2
    db = Db(cfg.data_dir)
    ig = Instagram(token, uid, cfg.graph_version)
    rapido = "--rapido" in sys.argv
    print("nuovi contenuti:", sync_new_content(db, ig))
    res = Importer(db, ig).run(rapido)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
