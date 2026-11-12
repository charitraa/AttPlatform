"""
Encryption at rest for tenant integration secrets.

`FIELD_ENCRYPTION_KEYS` is a comma-separated list of Fernet keys, newest first.
New values are encrypted with the first key; any listed key can decrypt, so a key
is rotated by prepending a new one and running `rotate_integration_secrets`.
Without a key nothing secret can be stored: we refuse rather than fall back to
plaintext.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SecretUnavailable(Exception):
    """A stored secret can't be decrypted with any configured key."""


@lru_cache(maxsize=4)
def _fernet(keys: tuple[str, ...]) -> MultiFernet:
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS is not set, so integration secrets can't be stored. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except ValueError as exc:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS contains an invalid Fernet key.") from exc


def _current() -> MultiFernet:
    return _fernet(tuple(k.strip() for k in settings.FIELD_ENCRYPTION_KEYS if k.strip()))


def encryption_configured() -> bool:
    try:
        _current()
    except ImproperlyConfigured:
        return False
    return True


def encrypt(value: str) -> str:
    return _current().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _current().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretUnavailable("Stored secret can't be decrypted with the configured keys.") from exc


def rotate(token: str) -> str:
    """Re-encrypt with the newest key (no-op for values already on it)."""
    return _current().rotate(token.encode()).decode()


def hint(value: str) -> str:
    """What the API may show about a secret: at most the last 4 characters."""
    return f"…{value[-4:]}" if len(value) >= 12 else "…"
