"""Browser headless minimale per il manager. POST /content {"url": ...} -> HTML della pagina; POST /png {"svg": ...} -> immagine.
Può girare dentro il processo del bot (127.0.0.1, token casuale) o come servizio separato: python -m app.browser_service.

- Chromium parte SOLO quando serve (nessuna memoria occupata a riposo) e un profilo nuovo per ogni richiesta,
  cancellato subito dopo: nessun cookie, nessun login, nessuna traccia.
- Una pagina alla volta.
- Accetta solo http/https verso indirizzi pubblici e solo con il token condiviso.
"""
import hmac
import ipaddress
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("BROWSER_TOKEN", "")  # nel servizio separato; in modalità interna lo imposta serve()
MAX_OUT = 2_500_000
LOCK = threading.Lock()


def public(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def render(url: str) -> str:
    prof = tempfile.mkdtemp(prefix="prof-", dir="/tmp")
    cmd = ["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
           "--disable-extensions", "--disable-crash-reporter", "--no-first-run", "--mute-audio",
           f"--user-data-dir={prof}", "--virtual-time-budget=9000", "--window-size=1280,2000",
           "--dump-dom", url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
                            env={"HOME": prof, "PATH": os.environ.get("PATH", "")})
    try:
        out, _ = proc.communicate(timeout=50)
        return out[:MAX_OUT].decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    finally:
        shutil.rmtree(prof, ignore_errors=True)


BAD_SVG = ("<script", "javascript:", "foreignobject", "<image", "href", "url(", "<iframe", "<use", "onload", "onerror", "@import")


def render_png(svg: str, w: int = 900, h: int = 560) -> bytes:
    """SVG (solo forme e testo, creato dal bot) -> PNG a doppia risoluzione. Nessuna rete, profilo nuovo e cancellato."""
    low = svg.lower()
    if not low.startswith("<svg") or any(b in low for b in BAD_SVG) or len(svg) > 200_000:
        raise ValueError("svg non ammesso")
    work = tempfile.mkdtemp(prefix="png-", dir="/tmp")
    try:
        page = os.path.join(work, "c.html")
        out = os.path.join(work, "o.png")
        with open(page, "w", encoding="utf-8") as f:
            f.write('<!doctype html><meta charset="utf-8"><body style="margin:0;background:#14161c">' + svg + "</body>")
        cmd = ["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
               "--disable-extensions", "--disable-crash-reporter", "--no-first-run", "--hide-scrollbars",
               f"--user-data-dir={os.path.join(work, 'prof')}", "--force-device-scale-factor=2",
               f"--window-size={w},{h}", f"--screenshot={out}", "file://" + page]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                                env={"HOME": work, "PATH": os.environ.get("PATH", "")})
        try:
            proc.communicate(timeout=40)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise
        with open(out, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(work, ignore_errors=True)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # niente URL nei log
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, "ok") if self.path == "/health" else self._send(404, "no")

    def do_POST(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        path = urllib.parse.urlparse(self.path).path
        if path not in ("/content", "/png"):
            return self._send(404, "no")
        if not TOKEN or not hmac.compare_digest(q.get("token", [""])[0], TOKEN):
            return self._send(403, "token")
        if path == "/png":
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 210_000)
                svg = json.loads(self.rfile.read(n)).get("svg", "")
                if not LOCK.acquire(timeout=5):
                    return self._send(429, "occupato")
            except Exception:
                return self._send(400, "richiesta non valida")
            try:
                png = render_png(svg)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.end_headers()
                self.wfile.write(png)
            except ValueError:
                self._send(400, "svg non ammesso")
            except Exception:
                self._send(504, "immagine non creata")
            finally:
                LOCK.release()
            return
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 4096)
            url = json.loads(self.rfile.read(n)).get("url", "")
        except Exception:
            return self._send(400, "richiesta non valida")
        if not public(url):
            return self._send(400, "indirizzo non valido o non pubblico")
        if not LOCK.acquire(timeout=5):
            return self._send(429, "occupato")
        try:
            self._send(200, render(url), "text/html; charset=utf-8")
        except Exception:
            self._send(504, "pagina non letta")
        finally:
            LOCK.release()


def serve(host: str = "127.0.0.1", port: int = 3000, token: str = None, background: bool = True):
    """Avvia il servizio. Con background=True parte in un thread e ritorna il server (modalità interna)."""
    global TOKEN
    if token is not None:
        TOKEN = token
    srv = ThreadingHTTPServer((host, port), H)
    if background:
        threading.Thread(target=srv.serve_forever, name="browser", daemon=True).start()
    else:
        srv.serve_forever()
    return srv


if __name__ == "__main__":
    serve("0.0.0.0", 3000, background=False)
