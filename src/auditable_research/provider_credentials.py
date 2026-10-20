"""Encrypted user credentials and per-workflow API-key context."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

PROVIDER_KEY_FIELDS = {
    "groq_api_key": "GROQ_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "ncbi_api_key": "NCBI_API_KEY",
    "semantic_scholar_api_key": "SEMANTIC_SCHOLAR_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
}

PROVIDER_KEY_LABELS = {
    "groq_api_key": "Groq API key",
    "openrouter_api_key": "OpenRouter API key",
    "ncbi_api_key": "NCBI API key",
    "semantic_scholar_api_key": "Semantic Scholar API key",
    "anthropic_api_key": "Anthropic API key (Claude)",
    "gemini_api_key": "Gemini API key",
}
MODEL_PROVIDER_KEYS = {
    "groq": "groq_api_key",
    "anthropic": "anthropic_api_key",
    "gemini": "gemini_api_key",
}
MODEL_PROVIDER_LABELS = {"auto": "Automatic", "groq": "Groq", "anthropic": "Claude", "gemini": "Gemini"}
MODEL_PROVIDER_PREFERENCE_KEY = "_preferred_model_provider"

_workflow_keys: ContextVar[dict[str, str] | None] = ContextVar("workflow_provider_keys", default=None)


def _fernet() -> Fernet:
    key = settings.user_keys_encryption_key
    if not key:
        raise RuntimeError("USER_KEYS_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("USER_KEYS_ENCRYPTION_KEY must be a Fernet key") from exc


def encryption_is_configured() -> bool:
    try:
        _fernet()
    except RuntimeError:
        return False
    return True


def encrypt_provider_keys(keys: dict[str, str]) -> dict[str, str]:
    cipher = _fernet()
    return {
        name: cipher.encrypt(value.encode("utf-8")).decode("ascii")
        for name, value in keys.items()
        if name in PROVIDER_KEY_FIELDS and value
    }


def decrypt_provider_keys(encrypted: dict[str, str] | None) -> dict[str, str]:
    cipher = _fernet()
    try:
        return {
            name: cipher.decrypt(value.encode("ascii")).decode("utf-8")
            for name, value in (encrypted or {}).items()
            if name in PROVIDER_KEY_FIELDS and value
        }
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("Stored provider keys could not be decrypted") from exc


def provider_api_key(name: str) -> str:
    keys = _workflow_keys.get()
    if keys is not None:
        return keys.get(name, "")
    return str(getattr(settings, name, ""))


def selected_model_provider() -> str:
    """Return the user's selected configured model provider, or the first available one."""
    keys = _workflow_keys.get()
    preferred = keys.get(MODEL_PROVIDER_PREFERENCE_KEY, "auto") if keys is not None else "auto"
    if preferred in MODEL_PROVIDER_KEYS and provider_api_key(MODEL_PROVIDER_KEYS[preferred]):
        return preferred
    for provider in ("anthropic", "gemini", "groq"):
        if provider_api_key(MODEL_PROVIDER_KEYS[provider]):
            return provider
    raise RuntimeError("No model provider API key is configured for this research run")


def active_model_name(requested_model: str | None = None) -> str:
    """Resolve the configured model name for the active provider and workflow role."""
    provider = selected_model_provider()
    if provider == "groq":
        return requested_model or settings.groq_model
    is_fallback = requested_model in {settings.groq_fallback_model, settings.groq_screening_model}
    if provider == "anthropic":
        if requested_model in {settings.anthropic_model, settings.anthropic_fallback_model}:
            return requested_model
        return settings.anthropic_fallback_model if is_fallback else settings.anthropic_model
    if requested_model in {settings.gemini_model, settings.gemini_fallback_model}:
        return requested_model
    return settings.gemini_fallback_model if is_fallback else settings.gemini_model


@contextmanager
def use_provider_keys(keys: dict[str, str]) -> Iterator[None]:
    token: Token[dict[str, str] | None] = _workflow_keys.set(keys)
    try:
        yield
    finally:
        _workflow_keys.reset(token)
