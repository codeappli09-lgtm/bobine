"""Appel du modèle (Qwen via Ollama en local, ou une API compatible OpenAI)."""
from __future__ import annotations

import json
import re

import requests

from . import config


class LLMError(RuntimeError):
    pass


def status() -> dict:
    """Dit si l'IA est joignable, pour l'afficher dans l'interface."""
    if config.LLM_PROVIDER == "ollama":
        try:
            r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return {"ok": False, "provider": "ollama", "model": config.LLM_MODEL,
                    "message": "Ollama ne répond pas : lance ./start.sh"}
        wanted = config.LLM_MODEL
        found = any(m == wanted or m.split(":")[0] == wanted for m in models)
        if not found:
            return {"ok": False, "provider": "ollama", "model": wanted,
                    "message": f"Modèle absent : lance « ollama pull {wanted} »"}
        return {"ok": True, "provider": "ollama", "model": wanted, "message": "Qwen en local"}
    if not config.LLM_API_KEY:
        return {"ok": False, "provider": "api", "model": config.LLM_MODEL,
                "message": "LLM_API_KEY manquante dans .env"}
    return {"ok": True, "provider": "api", "model": config.LLM_MODEL, "message": "API distante"}


def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def chat(system: str, user: str, temperature: float = 0.8, want_json: bool = True) -> str:
    if config.LLM_PROVIDER == "ollama":
        payload = {
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_ctx": 8192},
        }
        if want_json:
            payload["format"] = "json"
        try:
            r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload,
                              timeout=config.LLM_TIMEOUT)
            if r.status_code == 400 and "think" in r.text.lower():
                payload.pop("think", None)  # modèle sans mode réflexion
                r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload,
                                  timeout=config.LLM_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"Ollama : {exc}") from exc
        return _strip_thinking(r.json().get("message", {}).get("content", ""))

    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}",
               "Content-Type": "application/json"}
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if want_json:
        payload["response_format"] = {"type": "json_object"}
    try:
        r = requests.post(f"{config.LLM_BASE_URL}/chat/completions", json=payload,
                          headers=headers, timeout=config.LLM_TIMEOUT)
        if r.status_code == 400 and "response_format" in r.text:
            payload.pop("response_format")
            r = requests.post(f"{config.LLM_BASE_URL}/chat/completions", json=payload,
                              headers=headers, timeout=config.LLM_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise LLMError(f"API : {exc}") from exc
    return _strip_thinking(r.json()["choices"][0]["message"]["content"] or "")


def parse_json(text: str) -> dict:
    """Récupère l'objet JSON même si le modèle a ajouté du texte autour."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        chunk = text[start:end + 1]
        chunk = re.sub(r",\s*([}\]])", r"\1", chunk)  # virgules en trop
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            pass
    raise LLMError("Le modèle n'a pas renvoyé un JSON lisible.")
