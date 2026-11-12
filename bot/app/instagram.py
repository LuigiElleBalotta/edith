"""Instagram Graph API: SOLO LETTURA per ora (audit iniziale). Nessuna pubblicazione, nessuna risposta.

Il token arriva solo da variabile d'ambiente e non viene mai scritto nei log o nei messaggi d'errore.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

MEDIA_FIELDS = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"


class IgError(Exception):
    pass


def _clean(msg: str, token: str) -> str:
    msg = msg.replace(token, "***")
    return re.sub(r"EAA[A-Za-z0-9]{20,}", "***", msg)


class Instagram:
    def __init__(self, token: str, user_id: str, version: str = "v23.0", opener=None):
        self._token = token
        self.user_id = user_id
        self.base = f"https://graph.facebook.com/{version}"
        self._open = opener or urllib.request.urlopen

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._token}"})
        try:
            with self._open(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                detail = json.load(e).get("error", {}).get("message", "")
            except Exception:
                detail = ""
            raise IgError(_clean(f"Instagram HTTP {e.code}: {detail}"[:200], self._token)) from None
        except Exception as e:
            raise IgError(_clean(f"Instagram errore {type(e).__name__}", self._token)) from None

    def profile(self) -> dict:
        q = urllib.parse.urlencode({"fields": "id,username,name,followers_count,follows_count,media_count"})
        return self._get(f"{self.base}/{self.user_id}?{q}")

    def get(self, path: str) -> dict:
        """GET generico (sola lettura) su un percorso del Graph API, es. '<id>/insights?metric=reach'."""
        return self._get(f"{self.base}/{path.lstrip('/')}")

    def media(self, media_id: str) -> dict:
        q = urllib.parse.urlencode({"fields": MEDIA_FIELDS})
        return self._get(f"{self.base}/{urllib.parse.quote(str(media_id))}?{q}")

    def comments(self, media_id: str, limit: int = 8) -> list:
        q = urllib.parse.urlencode({"fields": "text,timestamp,like_count", "limit": limit})
        return self._get(f"{self.base}/{urllib.parse.quote(str(media_id))}/comments?{q}").get("data", [])

    def discover(self, username: str, n: int = 12) -> dict:
        """Business Discovery (API ufficiale): dati PUBBLICI di un altro account professionale. Sola lettura."""
        username = (username or "").strip().lstrip("@").lower()
        if not re.fullmatch(r"[a-z0-9._]{1,30}", username):
            raise IgError("nome utente non valido")
        n = max(1, min(int(n), 25))
        f = (f"business_discovery.username({username}){{username,name,biography,followers_count,media_count,"
             f"media.limit({n}){{like_count,comments_count,timestamp,media_product_type,caption,permalink}}}}")
        bd = self._get(f"{self.base}/{self.user_id}?fields=" + urllib.parse.quote(f, safe="(){},.")).get("business_discovery", {})
        media = (bd.get("media") or {}).get("data", [])
        likes = [m.get("like_count") or 0 for m in media]
        bd["media"] = [{"data": m.get("timestamp", "")[:10], "tipo": m.get("media_product_type"), "mi_piace": m.get("like_count"),
                        "commenti": m.get("comments_count"), "didascalia": m.get("caption") or "", "link": m.get("permalink")}
                       for m in media]
        if likes and bd.get("followers_count"):
            bd["media_mi_piace"] = round(sum(likes) / len(likes))
            bd["mi_piace_per_100_follower"] = round(100 * sum(likes) / len(likes) / bd["followers_count"], 2)
        return bd

    def account_insights(self, days: int = 28) -> dict:
        """Statistiche dell'account negli ultimi N giorni (max 30): totali + andamento giornaliero di copertura e follower."""
        import time
        days = max(1, min(int(days), 30))
        now = int(time.time())
        rng = f"&since={now - days * 86400}&until={now}"
        out = {"giorni": days}
        for m in ("views", "accounts_engaged", "total_interactions", "profile_views"):
            try:
                d = self._get(f"{self.base}/{self.user_id}/insights?metric={m}&period=day&metric_type=total_value{rng}")
                out[m] = (d["data"][0].get("total_value") or {}).get("value")
            except (IgError, KeyError, IndexError) as e:
                out[m] = f"non disponibile ({e})"
        for m in ("reach", "follower_count"):
            try:
                d = self._get(f"{self.base}/{self.user_id}/insights?metric={m}&period=day{rng}")
                vals = [v["value"] for v in d["data"][0]["values"]]
                out[m + "_per_giorno"] = vals
                out[m + "_totale_periodo"] = sum(vals) if m == "follower_count" else None
            except (IgError, KeyError, IndexError) as e:
                out[m + "_per_giorno"] = f"non disponibile ({e})"
        out["reach_per_giorno_nota"] = "la copertura giornaliera non si somma (account unici): guarda il valore medio"
        return out

    def insights(self, media_id: str) -> dict:
        """Statistiche del post (reach, views, saved, shares, total_interactions)."""
        q = urllib.parse.urlencode({"metric": "reach,views,saved,shares,total_interactions"})
        return self._get(f"{self.base}/{urllib.parse.quote(str(media_id))}/insights?{q}")

    def iter_media(self, limit_total: int = 1000, page: int = 50):
        """Scorre i media, dal più recente. Mai oltre limit_total."""
        q = urllib.parse.urlencode({"fields": MEDIA_FIELDS, "limit": page})
        url = f"{self.base}/{self.user_id}/media?{q}"
        n = 0
        while url and n < limit_total:
            data = self._get(url)
            for item in data.get("data", []):
                yield item
                n += 1
                if n >= limit_total:
                    return
            url = (data.get("paging") or {}).get("next")


def media_to_content(item: dict) -> dict:
    """Converte un media Instagram in una riga dell'archivio. Nessun giudizio: lo stato è 'non classificato'
    finché il proprietario (o una classificazione verificata) non separa musica da contenuti personali."""
    kind = item.get("media_product_type") or item.get("media_type")
    metrics = {"likes": item.get("like_count"), "comments": item.get("comments_count")}
    return dict(
        original_url=item.get("permalink"),
        published_at=item.get("timestamp"),
        media_type=kind,
        caption=item.get("caption"),
        metrics_json=json.dumps(metrics),
        notes=f"instagram_id={item.get('id')}",
    )
