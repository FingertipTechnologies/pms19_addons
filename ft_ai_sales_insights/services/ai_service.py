"""AIService — a single façade over every AI provider.

Business code never imports a concrete provider. It builds an :class:`AIService`
from the stored configuration and calls :meth:`generate`. Registering a new
provider is a one-line addition to :data:`PROVIDERS` — no caller changes.
"""
from __future__ import annotations

import logging
from typing import Any

from .providers.base import AIProvider, AIProviderError, AIResult
from .providers.openai_provider import AzureOpenAIProvider, OpenAIProvider
from .providers.claude_provider import ClaudeProvider
from .providers.gemini_provider import GeminiProvider
from .providers.ollama_provider import OllamaProvider

_logger = logging.getLogger(__name__)

#: provider key -> provider class. Extend this to add a vendor.
PROVIDERS: dict[str, type[AIProvider]] = {
    p.key: p
    for p in (
        OpenAIProvider,
        ClaudeProvider,
        GeminiProvider,
        AzureOpenAIProvider,
        OllamaProvider,
    )
}


def provider_selection() -> list[tuple[str, str]]:
    """Selection field options for the config model."""
    return [(cls.key, cls.label) for cls in PROVIDERS.values()]


class AIService:
    """Instantiate the configured provider and expose a uniform ``generate``."""

    def __init__(
        self,
        provider_key: str,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 60,
        **options: Any,
    ) -> None:
        provider_cls = PROVIDERS.get(provider_key)
        if not provider_cls:
            raise AIProviderError(f"Unknown AI provider '{provider_key}'.")
        self.provider_key = provider_key
        self.provider = provider_cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            **options,
        )

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.4,
        max_tokens: int = 1500,
        json_mode: bool = True,
        **kwargs: Any,
    ) -> AIResult:
        _logger.debug(
            "AIService.generate provider=%s model=%s messages=%d",
            self.provider_key,
            self.provider.model,
            len(messages),
        )
        return self.provider.generate(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            **kwargs,
        )
