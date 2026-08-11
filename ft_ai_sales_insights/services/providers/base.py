"""Abstract base for AI chat providers.

A provider is a thin, dependency-light adapter around one vendor's chat API.
It knows nothing about Odoo — it takes a normalized ``messages`` list and
returns a normalized :class:`AIResult`. This keeps the business layer
(prompt building, data collection, logging) completely provider-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class AIProviderError(Exception):
    """Raised for any provider-side failure (network, auth, bad response)."""


@dataclass
class AIResult:
    """Normalized result returned by every provider."""

    text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class AIProvider:
    """Base provider. Subclasses must set ``key`` and implement ``generate``."""

    key: str = "base"
    label: str = "Base"
    #: Whether this provider expects a top-level ``system`` message split out
    #: from the ``messages`` list (Anthropic/Gemini style) vs inline (OpenAI).
    system_as_param: bool = False

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 60,
        **options: Any,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip() or self.default_base_url()
        self.model = model or self.default_model()
        self.timeout = timeout or 60
        self.options = options

    # -- overridable defaults -------------------------------------------------
    def default_base_url(self) -> str:
        return ""

    def default_model(self) -> str:
        return ""

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def split_system(messages: list[dict]) -> tuple[str, list[dict]]:
        """Return (system_text, non_system_messages)."""
        system = "\n\n".join(
            m["content"] for m in messages if m.get("role") == "system"
        )
        rest = [m for m in messages if m.get("role") != "system"]
        return system, rest

    def _require_key(self) -> None:
        if not self.api_key:
            raise AIProviderError(
                f"No API key configured for provider '{self.key}'."
            )

    # -- contract -------------------------------------------------------------
    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.4,
        max_tokens: int = 1500,
        json_mode: bool = True,
        **kwargs: Any,
    ) -> AIResult:
        """Send ``messages`` and return an :class:`AIResult`.

        :param messages: list of ``{"role": "system|user|assistant",
            "content": str}``.
        :param json_mode: request a strict-JSON response when supported.
        """
        raise NotImplementedError
