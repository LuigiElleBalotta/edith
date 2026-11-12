"""Importa gli «esperti» da https://github.com/msitarzewski/agency-agents (licenza MIT) in bot/esperti/.

- scarica da un COMMIT FISSATO (non da «main»): gli stessi file ogni volta, niente sorprese;
- i file restano IDENTICI all'originale; l'impronta (sha256) di ognuno va in INDICE.json e viene
  ricontrollata a ogni uso (un file cambiato a mano o corrotto non si usa);
- si importa solo l'elenco scelto qui sotto (utile a EDITH: social, contenuti, vendite, PR, bandi),
  non tutti gli agenti del repository.

    python scripts/importa_esperti.py                 # usa il commit fissato qui sotto
    python scripts/importa_esperti.py <commit-sha>    # per aggiornare: poi rileggi i file e fai commit

Per aggiungere un esperto: aggiungi il percorso a SCELTI, rilancia, leggi il file importato PRIMA di committare.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.request

REPO = "msitarzewski/agency-agents"
COMMIT = "8ae6164602c95ca78828b148b9052460ee426885"  # 2026-11-09
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "bot", "esperti")

# Esclusi di proposito: gli agenti che pubblicano da soli o fanno scraping (carousel-growth-engine,
# multi-platform-publisher, ...). EDITH non pubblica e non fa scraping: vedi SECURITY.md.
SCELTI = [
    "marketing/marketing-social-media-strategist.md", "marketing/marketing-instagram-curator.md",
    "marketing/marketing-content-creator.md", "marketing/marketing-tiktok-strategist.md",
    "marketing/marketing-growth-hacker.md", "marketing/marketing-video-optimization-specialist.md",
    "marketing/marketing-short-video-editing-coach.md", "marketing/marketing-global-podcast-strategist.md",
    "marketing/marketing-email-strategist.md", "marketing/marketing-pr-communications-manager.md",
    "marketing/marketing-seo-specialist.md", "marketing/marketing-linkedin-content-creator.md",
    "marketing/marketing-reddit-community-builder.md",
    "design/design-brand-guardian.md", "design/design-visual-storyteller.md",
    "design/design-whimsy-injector.md", "design/design-image-prompt-engineer.md",
    "sales/sales-outbound-strategist.md", "sales/sales-proposal-strategist.md", "sales/sales-offer-lead-gen-strategist.md",
    "paid-media/paid-media-paid-social-strategist.md", "paid-media/paid-media-creative-strategist.md",
    "support/support-analytics-reporter.md", "support/support-executive-summary-generator.md",
    "support/support-legal-compliance-checker.md",
    "product/product-trend-researcher.md", "product/product-feedback-synthesizer.md",
    "research/research-synthesist.md",
    "specialized/grant-writer.md", "specialized/specialized-chief-of-staff.md", "specialized/business-strategist.md",
    "specialized/language-translator.md", "specialized/specialized-pricing-analyst.md",
    "specialized/specialized-cultural-intelligence-strategist.md", "specialized/customer-service.md",
]


def scarica(commit: str, path: str) -> bytes:
    url = f"https://raw.githubusercontent.com/{REPO}/{commit}/{path}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def frontmatter(raw: bytes) -> dict:
    t = raw.decode("utf-8").replace("\r\n", "\n")
    if not t.startswith("---\n") or "\n---" not in t[4:]:
        raise ValueError("manca l'intestazione")
    out = {}
    for ln in t[4:t.index("\n---", 4)].split("\n"):
        k, _, v = ln.partition(":")
        if _ and k.strip():
            out[k.strip()] = v.strip().strip('"')
    return out


def slug(path: str) -> str:
    div, nome = path.split("/")
    nome = nome[:-3]
    for pre in (div + "-", "marketing-", "specialized-"):
        if nome.startswith(pre):
            nome = nome[len(pre):]
            break
    return re.sub(r"[^a-z0-9]+", "_", nome.lower()).strip("_")


def main() -> int:
    commit = sys.argv[1] if len(sys.argv) > 1 else COMMIT
    os.makedirs(OUT, exist_ok=True)
    for vecchio in os.listdir(OUT):
        if vecchio.endswith(".md"):
            os.remove(os.path.join(OUT, vecchio))
    esperti, visti = {}, set()
    for path in SCELTI:
        raw = scarica(commit, path)
        fm = frontmatter(raw)
        if not fm.get("name") or not fm.get("description"):
            raise SystemExit(f"{path}: servono 'name' e 'description'")
        eid = slug(path)
        if eid in visti or not re.match(r"^[a-z][a-z0-9_]{1,40}$", eid):
            raise SystemExit(f"id non valido o doppio: {eid}")
        visti.add(eid)
        with open(os.path.join(OUT, eid + ".md"), "wb") as f:
            f.write(raw)
        esperti[eid] = {"nome": fm["name"], "descrizione": fm["description"], "divisione": path.split("/")[0],
                        "file": eid + ".md", "origine": path, "sha256": hashlib.sha256(raw).hexdigest()}
    with open(os.path.join(OUT, "LICENSE-agency-agents.txt"), "wb") as f:
        f.write(scarica(commit, "LICENSE"))
    with open(os.path.join(OUT, "INDICE.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"_origine": {"repository": f"https://github.com/{REPO}", "commit": commit, "licenza": "MIT"},
                   "esperti": esperti}, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write(chr(10))
    tot = sum(os.path.getsize(os.path.join(OUT, e["file"])) for e in esperti.values())
    print(f"{len(esperti)} esperti importati dal commit {commit[:10]} ({tot // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
