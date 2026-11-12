"""Provider registry. Selected by AI_PROVIDER; business code calls `get_provider()` only."""

from django.conf import settings

from .base import AIProvider, ProviderConfigError


def get_provider() -> AIProvider:
    name = settings.AI_PROVIDER
    if name == "mock":
        from .mock import MockProvider

        return MockProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.AI_API_KEY, model=settings.AI_MODEL, base_url=settings.AI_BASE_URL)
    if name == "openai_compatible":
        from .openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            api_key=settings.AI_API_KEY, model=settings.AI_MODEL, base_url=settings.AI_BASE_URL
        )
    raise ProviderConfigError(f"Unknown AI_PROVIDER '{name}'.")
