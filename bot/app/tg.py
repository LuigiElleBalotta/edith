"""Client Telegram minimale (solo libreria standard, nessuna dipendenza)."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .fmt import md_to_html


class TgError(Exception):
    pass


def split_text(text: str, limit: int = 3800):
    """Spezza un messaggio lungo (Telegram accetta max 4096 caratteri)."""
    text = text or "(vuoto)"
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return parts


class Tg:
    def __init__(self, token: str):
        self._token = token

    def _clean(self, s: str) -> str:
        return s.replace(self._token, "***")

    def call(self, method: str, timeout: int = 40, **params):
        data = json.dumps(params).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self._token}/{method}", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.load(r)
        except urllib.error.HTTPError as e:
            raise TgError(self._clean(f"Telegram HTTP {e.code} su {method}")) from None
        except Exception as e:
            raise TgError(self._clean(f"Telegram errore {type(e).__name__} su {method}")) from None
        if not j.get("ok"):
            raise TgError(self._clean(f"Telegram rifiuta {method}: {j.get('description')}"))
        return j["result"]

    def get_updates(self, offset: int, poll: int = 30):
        """Long polling: il bot chiama Telegram, quindi non serve alcun proxy/porta aperta."""
        data = json.dumps({"offset": offset, "timeout": poll,
                           "allowed_updates": ["message", "callback_query"]}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self._token}/getUpdates", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=poll + 15) as r:
                j = json.load(r)
        except Exception as e:
            raise TgError(self._clean(f"Telegram polling: {type(e).__name__}")) from None
        if not j.get("ok"):
            raise TgError("Telegram polling rifiutato")
        return j["result"]

    def send(self, chat_id: int, text: str, silent: bool = False, plain: bool = False, reply_markup=None):
        """Invia con formattazione (HTML di Telegram). Se Telegram rifiuta la formattazione, rimanda il testo semplice.
        I bottoni (reply_markup) vanno sull'ultimo pezzo."""
        parts = split_text(text, 3500)
        for i, p in enumerate(parts):
            extra = {"disable_notification": True} if silent else {}
            if reply_markup and i == len(parts) - 1:
                extra["reply_markup"] = reply_markup
            if not plain:
                try:
                    self.call("sendMessage", chat_id=chat_id, text=md_to_html(p), parse_mode="HTML",
                              disable_web_page_preview=True, **extra)
                    continue
                except TgError as e:
                    if "parse" not in str(e).lower() and "entit" not in str(e).lower() and "400" not in str(e):
                        raise
            self.call("sendMessage", chat_id=chat_id, text=p, **extra)

    def send_photo(self, chat_id: int, png: bytes, caption: str = "", silent: bool = False):
        """Invia un'immagine PNG (multipart, solo libreria standard)."""
        import uuid
        b = uuid.uuid4().hex
        fields = {"chat_id": str(chat_id), "caption": caption[:900]}
        if silent:
            fields["disable_notification"] = "true"
        body = b""
        for k, v in fields.items():
            body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        body += (f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="grafico.png"\r\n'
                 f'Content-Type: image/png\r\n\r\n').encode() + png + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self._token}/sendPhoto", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.load(r)
        except Exception as e:
            raise TgError(self._clean(f"Telegram sendPhoto: {type(e).__name__}")) from None
        if not j.get("ok"):
            raise TgError(self._clean(f"Telegram rifiuta sendPhoto: {j.get('description')}"))

    def set_commands(self, commands: list):
        """Elenco comandi che compare quando si digita '/' (menu suggerimenti)."""
        self.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in commands])

    def typing(self, chat_id: int):
        try:
            self.call("sendChatAction", chat_id=chat_id, action="typing", timeout=10)
        except TgError:
            pass

    def download(self, file_id: str, max_bytes: int):
        """Scarica un file (limite 20 MB con Bot API cloud). Ritorna (bytes, nome_remoto)."""
        info = self.call("getFile", file_id=file_id)
        size = info.get("file_size") or 0
        if size and size > max_bytes:
            raise TgError(f"File troppo grande per il Bot API cloud ({size} byte)")
        url = f"https://api.telegram.org/file/bot{self._token}/{info['file_path']}"
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read(max_bytes + 1), info["file_path"]
        except Exception as e:
            raise TgError(self._clean(f"Download fallito: {type(e).__name__}")) from None
