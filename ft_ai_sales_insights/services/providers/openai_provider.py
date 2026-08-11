"""OpenAI Chat Completions provider (also the base for Azure OpenAI)."""
from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .base import AIProvider, AIProviderError, AIResult

_logger = logging.getLogger(__name__)


class OpenAIProvider(AIProvider):
    key = "openai"
    label = "OpenAI"

    def default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    def default_model(self) -> str:
        return "gpt-4o-mini"

    # -- request building (overridable by Azure) ------------------------------
    def _endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages, temperature, max_tokens, json_mode) -> dict:
        if json_mode:
            # OpenAI rejects ``response_format={"type": "json_object"}`` unless at
            # least one message literally contains the word "json". Guarantee it
            # so no caller can trip HTTP 400, without mutating the caller's list.
            if not any("json" in (m.get("content") or "").lower() for m in messages):
                messages = messages + [
                    {"role": "system", "content": "Respond with a single valid JSON object."}
                ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    # -- contract -------------------------------------------------------------
    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.4,
        max_tokens: int = 1500,
        json_mode: bool = True,
        **kwargs: Any,
    ) -> AIResult:
        self._require_key()
        try:
            resp = requests.post(
                self._endpoint(),
                headers=self._headers(),
                data=json.dumps(
                    self._payload(messages, temperature, max_tokens, json_mode)
                ),
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
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise AIProviderError(
                f"{self.label} returned an unexpected response shape."
            ) from exc
        usage = data.get("usage") or {}
        return AIResult(
            text=text,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self.model),
            raw=data,
        )


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI — same wire format, different auth header and URL.

    ``base_url`` must be the full deployment URL, e.g.::

        https://<resource>.openai.azure.com/openai/deployments/<deployment>

    The API version is passed via the ``azure_api_version`` option.
    """

    key = "azure"
    label = "Azure OpenAI"

    def default_base_url(self) -> str:
        return ""

    def _endpoint(self) -> str:
        version = self.options.get("azure_api_version", "2024-06-01")
        return f"{self.base_url.rstrip('/')}/chat/completions?api-version={version}"

    def _headers(self) -> dict:
        return {"api-key": self.api_key, "Content-Type": "application/json"}
