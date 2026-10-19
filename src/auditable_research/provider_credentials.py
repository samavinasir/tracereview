"""Encrypted user credentials and per-workflow API-key context."""

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

PROVIDER_KEY_FIELDS = {
    "groq_api_key": "GROQ_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "ncbi_api_key": "NCBI_API_KEY",
    "semantic_scholar_api_key": "SEMANTIC_SCHOLAR_API_KEY",
}

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


@contextmanager
def use_provider_keys(keys: dict[str, str]) -> Iterator[None]:
    token: Token[dict[str, str] | None] = _workflow_keys.set(keys)
    try:
        yield
    finally:
        _workflow_keys.reset(token)
