#!/usr/bin/env bash
# Prima installazione: prepara le cartelle, le impostazioni comuni e avvia il contenitore. Poi guida a creare il primo account.
#   ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Serve Docker: https://docs.docker.com/engine/install/"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Serve Docker Compose (plugin 'docker compose')."; exit 1; }

mkdir -p data accounts
chmod 700 accounts

# scrive CHIAVE=valore nel .env senza interpretare caratteri speciali (|, &, \ ...)
setenv() { K="$1" V="$2" awk 'BEGIN{FS=OFS="="; k=ENVIRON["K"]; v=ENVIRON["V"]} $1==k{print k"="v; f=1; next} {print} END{if(!f)print k"="v}' .env > .env.tmp && mv .env.tmp .env && chmod 600 .env; }

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "== Impostazioni comuni =="
  echo "Serve un servizio IA compatibile OpenAI (es. OmniRoute, o un provider con endpoint /v1)."
  read -r -p "Indirizzo del servizio (es. https://ai.miodominio.it/v1): " BASE
  read -r -s -p "Chiave del servizio (invio per scegliere una chiave per ogni account): " KEY; echo
  setenv OMNIROUTE_BASE_URL "$BASE"
  [ -n "$KEY" ] && setenv OMNIROUTE_API_KEY "$KEY"
  unset KEY
fi
if ! grep -q '^PANEL_PASSWORD=.\{12,\}' .env; then
  PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 20)"
  setenv PANEL_PASSWORD "$PW"
  NEWPW="$PW"; unset PW
fi
setenv MANAGER_UID "$(id -u)"
setenv MANAGER_GID "$(id -g)"

echo "== Avvio =="
docker compose pull --quiet 2>/dev/null || docker compose build
docker compose up -d
sleep 3
echo
echo "Il contenitore è attivo. Creo il primo account:"
docker compose exec -it manager python -m app.accounts add
echo
if [ -n "${NEWPW:-}" ]; then
  echo
  echo "Pannello web (facoltativo): http://localhost:8787  (da un altro computer: ssh -L 8787:localhost:8787 utente@server)"
  echo "Password del pannello: $NEWPW   (è anche in .env: cambiala lì quando vuoi)"
fi
echo "Fatto. Comandi utili: ./manager list | ./manager add | ./manager check | ./manager logs | ./manager update"
