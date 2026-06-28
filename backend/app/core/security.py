"""Security primitives: API key generation and HMAC-SHA256 signing for
outgoing webhook payloads (§3.6.6, §3.6.7, §3.13.6).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

# API keys must be at least 32 chars (§3.13.6). We generate 40 chars of
# URL-safe entropy and prefix it so logs are easy to grep.
_API_KEY_PREFIX = "fa_"
_API_KEY_BYTES = 32  # 32 bytes → ~43 base64 chars; comfortably above the floor.


def generate_api_key() -> str:
    """Return a new cryptographically random API key string (plaintext).

    The caller stores only the SHA-256 hash in the database and shows the
    plaintext exactly once to the operator.
    """
    return _API_KEY_PREFIX + secrets.token_urlsafe(_API_KEY_BYTES)


def hash_api_key(plaintext: str) -> str:
    """One-way SHA-256 hash of an API key for database storage."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def hmac_sha256_hex(secret: str, body: bytes) -> str:
    """Return the lowercase hex HMAC-SHA256 of `body` keyed by `secret`.

    This is the value placed in the `X-Signature: sha256=<hex>` header
    of every outgoing webhook request.
    """
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
