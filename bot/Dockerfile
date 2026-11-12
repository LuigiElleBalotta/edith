# Un solo contenitore per tutti gli account: bot Telegram + (facoltativo) browser Chromium, avviato solo quando serve.
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive
# git + ssh: archivio di conoscenza (repository). chromium: lettura di pagine web e grafici (a riposo non occupa memoria).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client chromium fonts-liberation \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -r -u 10001 -m manager \
 && mkdir -p /data /config/accounts && chown manager /data /config/accounts
WORKDIR /srv
COPY app ./app
USER manager
VOLUME ["/data", "/config/accounts"]
CMD ["python", "-m", "app.main"]
