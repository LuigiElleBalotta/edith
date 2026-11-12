"""Accesso all'IA, separato dalla logica del manager.

Parla con qualunque endpoint compatibile OpenAI (OmniRoute). Per cambiare provider
basta cambiare OMNIROUTE_BASE_URL / modelli: il resto dell'app non cambia.
"""
import json
import urllib.error
import urllib.request


class AiError(Exception):
    pass


class Ai:
    def __init__(self, base_url: str, api_key: str, timeout: int = 120):
        self.base = base_url
        self._key = api_key
        self.timeout = timeout

    def chat(self, model: str, messages: list, max_tokens: int = 1200) -> str:
        return (self._post(model, messages, max_tokens).get("content") or "").strip() or self._empty()

    def chat_tools(self, model: str, messages: list, tools: list, max_tokens: int = 8000) -> dict:
        """Come chat(), ma il modello può chiedere di usare strumenti. Ritorna il messaggio completo."""
        return self._post(model, messages, max_tokens, tools)

    @staticmethod
    def _empty():
        raise AiError("Risposta IA vuota")

    def _post(self, model: str, messages: list, max_tokens: int, tools=None) -> dict:
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            payload["tools"] = tools
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            # Non includere mai header/chiave nei messaggi d'errore.
            raise AiError(f"IA ha risposto con errore HTTP {e.code}") from None
        except Exception as e:  # rete, timeout, JSON
            raise AiError(f"IA non raggiungibile: {type(e).__name__}") from None
        try:
            ch = data["choices"][0]
            msg = dict(ch["message"])
            msg["_finish"] = ch.get("finish_reason")  # "length" = risposta tagliata dal limite
            return msg
        except Exception:
            raise AiError("Risposta IA in formato inatteso") from None
