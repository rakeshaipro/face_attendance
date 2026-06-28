"""Symmetric encryption for sensitive fields stored in the database,
notably the credentials embedded in the camera MJPEG URL (§3.13.9).

Uses Fernet (AES-128-CBC + HMAC-SHA256). The key is held in the
`FA_ENCRYPTION_KEY` environment variable.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CryptoError(Exception):
    """Raised when encryption/decryption cannot proceed."""


def _get_fernet() -> Fernet:
    key = settings.encryption_key.get_secret_value()
    if not key:
        raise CryptoError(
            "FA_ENCRYPTION_KEY is not set. Generate one with "
            "`python -m app.cli gen-encryption-key` and add it to your .env."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return _get_fernet()


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string, return a URL-safe base64 token string."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a previously encrypted token back to a UTF-8 string."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:  # pragma: no cover - operational
        raise CryptoError("Could not decrypt value — wrong key or corrupted data.") from exc
