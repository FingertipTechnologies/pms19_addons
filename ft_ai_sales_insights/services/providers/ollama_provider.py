"""Ollama provider — local/self-hosted models, no API key required."""
from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .base import AIProvider, AIProviderError, AIResult

_logger = logging.getLogger(__name__)


class OllamaProvider(AIProvider):
    key = "ollama"
    label = "Ollama (self-hosted)"

    def default_base_url(self) -> str:
        return "http://localhost:11434"

    def default_model(self) -> str:
        return "llama3.1"

    def _require_key(self) -> None:  # Ollama needs no key.
        return

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.4,
        max_tokens: int = 1500,
        json_mode: bool = True,
        **kwargs: Any,
    ) -> AIResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            body["format"] = "json"
        try:
            resp = requests.post(
                f"{self.base_url.rstrip('/')}/api/chat",
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AIProviderError(f"{self.label} request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise AIProviderError(
                f"{self.label} HTTP {resp.status_code}: {resp.text[:500]}"
            )
        data = resp.json()
        text = (data.get("message") or {}).get("content", "")
        return AIResult(
            text=text,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            model=data.get("model", self.model),
            raw=data,
        )
