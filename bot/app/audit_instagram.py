"""Audit iniziale di Instagram: importa i METADATI dei contenuti (solo lettura) nell'archivio.

Uso (dentro il contenitore):  python -m app.audit_instagram
Non pubblica nulla, non risponde a nessuno, non scarica i video.
"""
import os
import sys
import time

from . import config as cfgmod
from .db import Db
from .instagram import IgError, Instagram, media_to_content


def import_media(db: Db, ig: Instagram, limit_total: int = 1000) -> dict:
    new = skipped = 0
    for item in ig.iter_media(limit_total=limit_total):
        c = media_to_content(item)
        if not c["original_url"] or db.content_url_exists(c["original_url"]):
            skipped += 1
            continue
        db.add_content("instagram", "da_classificare", "instagram_api",
                       verified_at=time.strftime("%Y-%m-%d"), **c)
        new += 1
    return {"nuovi": new, "gia_presenti": skipped}


def main() -> int:
    cfg = cfgmod.load()
    token, uid = cfg.ig_token, cfg.ig_user_id
    if not token or not uid:
        print("META_IG_TOKEN / META_IG_USER_ID mancanti")
        return 2
    db = Db(cfg.data_dir)
    ig = Instagram(token, uid, cfg.graph_version)
    try:
        prof = ig.profile()
        db.set("ig_profile_snapshot", f"{prof.get('username')} follower={prof.get('followers_count')} "
                                      f"media={prof.get('media_count')} al {time.strftime('%Y-%m-%d')}")
        res = import_media(db, ig)
    except IgError as e:
        db.audit("sistema", "audit_instagram_errore", str(e))
        print(f"errore: {e}")
        return 1
    db.audit("sistema", "audit_instagram", str(res))
    print(f"profilo: {prof.get('username')} follower={prof.get('followers_count')} media={prof.get('media_count')}")
    print(f"importazione: {res}")
    print(f"archivio: {db.content_summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
