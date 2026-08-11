"""Anthropic Claude Messages API provider."""
from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .base import AIProvider, AIProviderError, AIResult

_logger = logging.getLogger(__name__)


class ClaudeProvider(AIProvider):
    key = "claude"
    label = "Anthropic Claude"
    system_as_param = True

    def default_base_url(self) -> str:
        return "https://api.anthropic.com/v1"

    def default_model(self) -> str:
        return "claude-sonnet-5"

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
        if json_mode:
            system += (
                "\n\nRespond with a single valid JSON object and nothing else."
            )
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [
                {"role": m["role"], "content": m["content"]} for m in convo
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.options.get(
                "anthropic_version", "2023-06-01"
            ),
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                f"{self.base_url.rstrip('/')}/messages",
                headers=headers,
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
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        usage = data.get("usage") or {}
        return AIResult(
            text=text,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            model=data.get("model", self.model),
            raw=data,
        )
