"""Google Gemini (Generative Language API) provider."""
from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .base import AIProvider, AIProviderError, AIResult

_logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    key = "gemini"
    label = "Google Gemini"
    system_as_param = True

    def default_base_url(self) -> str:
        return "https://generativelanguage.googleapis.com/v1beta"

    def default_model(self) -> str:
        return "gemini-1.5-flash"

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.4,
        max_tokens: int = 1500,
        json_mode: bool = True,
        **kwargs: Any,
    ) -> AIResult:
        self._require_key()
        system, convo = self.split_system(messages)
        contents = [
            {
                "role": "user" if m["role"] == "user" else "model",
                "parts": [{"text": m["content"]}],
            }
            for m in convo
        ]
        gen_cfg: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        body = {"contents": contents, "generationConfig": gen_cfg}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = (
            f"{self.base_url.rstrip('/')}/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        try:
            resp = requests.post(
                url,
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
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError):
            text = ""
        usage = data.get("usageMetadata") or {}
        return AIResult(
            text=text,
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            model=self.model,
            raw=data,
        )
