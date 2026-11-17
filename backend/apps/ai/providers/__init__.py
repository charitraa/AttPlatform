"""
Provider registry. AI_PROVIDER selects the primary; AI_FALLBACKS lists presets tried in order when
the primary is unavailable (timeouts, rate limits, outages, unusable output). Business code only
calls the AI client, which walks `get_providers()`.
"""

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


# OpenAI-compatible presets usable as fallbacks: name -> (base URL, API-key setting, model setting, default model)
PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "gemini-2.5-flash",
    ),
    "nvidia": (
        "https://integrate.api.nvidia.com/v1",
        "NVIDIA_API_KEY",
        "NVIDIA_MODEL",
        "nvidia/nemotron-3-ultra-550b-a55b",
    ),
}


def preset_provider(name: str) -> AIProvider:
    from .openai_compatible import OpenAICompatibleProvider

    if name not in PRESETS:
        raise ProviderConfigError(f"Unknown AI fallback '{name}'. Choose from: {', '.join(PRESETS)}.")
    base_url, key_setting, model_setting, default_model = PRESETS[name]
    key = getattr(settings, key_setting, "")
    if not key:
        raise ProviderConfigError(f"{key_setting} is not set.")
    return OpenAICompatibleProvider(
        api_key=key, model=getattr(settings, model_setting, "") or default_model, base_url=base_url, label=name
    )


def get_providers() -> list[AIProvider]:
    """The primary provider followed by each configured fallback (fallbacks without a key are skipped)."""
    providers = [get_provider()]
    for name in settings.AI_FALLBACKS:
        try:
            providers.append(preset_provider(name.strip()))
        except ProviderConfigError:
            continue
    return providers
