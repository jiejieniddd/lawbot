from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet_from_secret(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def get_fernet(encryption_key: str | None = None, jwt_secret: str | None = None) -> Fernet:
    """Prefer ENCRYPTION_KEY (Fernet key or passphrase); else derive from JWT_SECRET."""
    raw = encryption_key or os.getenv("ENCRYPTION_KEY") or ""
    if raw:
        try:
            # Already a url-safe Fernet key
            return Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
        except (ValueError, TypeError, Exception):
            return _fernet_from_secret(raw)
    secret = jwt_secret or os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "dev-secret-change-me"
    return _fernet_from_secret(secret)


def encrypt_secret(plaintext: str, *, encryption_key: str | None = None, jwt_secret: str | None = None) -> str:
    token = get_fernet(encryption_key, jwt_secret).encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str, *, encryption_key: str | None = None, jwt_secret: str | None = None) -> str:
    try:
        return get_fernet(encryption_key, jwt_secret).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("failed to decrypt secret") from exc


def mask_api_key(plaintext: str | None) -> str:
    if not plaintext:
        return "****"
    if len(plaintext) <= 4:
        return "****"
    if len(plaintext) <= 8:
        return plaintext[:2] + "****"
    return plaintext[:2] + "****" + plaintext[-2:]
