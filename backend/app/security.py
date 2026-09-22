"""Password hashing (scrypt, stdlib), JWT access/refresh tokens, and at-rest token encryption."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from .config import Settings
from .core.timeutil import utcnow

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(dk_b64)
    except ValueError:
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return hmac.compare_digest(actual, expected)


class TokenError(Exception):
    pass


def _epoch(naive_utc) -> int:
    # naive-UTC datetimes must be tagged as UTC first, otherwise .timestamp() assumes local time
    return int(naive_utc.replace(tzinfo=timezone.utc).timestamp())


def make_token(settings: Settings, user_id: str, kind: str) -> tuple[str, str, datetime]:
    """Return (jwt, jti, expires_at_naive_utc)."""
    ttl = timedelta(minutes=settings.access_ttl_minutes) if kind == "access" else timedelta(days=settings.refresh_ttl_days)
    now = utcnow()
    jti = uuid.uuid4().hex
    exp = now + ttl
    payload = {"sub": user_id, "typ": kind, "jti": jti, "iat": _epoch(now), "exp": _epoch(exp)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), jti, exp


def decode_token(settings: Settings, token: str, kind: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as e:
        raise TokenError(str(e)) from e
    if payload.get("typ") != kind:
        raise TokenError("wrong token type")
    return payload


def _fernet(settings: Settings):
    from cryptography.fernet import Fernet

    key = settings.token_encryption_key
    if not key:  # dev fallback: derive a stable key from the JWT secret
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest()).decode()
    return Fernet(key)


def encrypt_secret(settings: Settings, value: str | None) -> str | None:
    return None if value is None else _fernet(settings).encrypt(value.encode()).decode()


def decrypt_secret(settings: Settings, value: str | None) -> str | None:
    return None if value is None else _fernet(settings).decrypt(value.encode()).decode()


def make_state(settings: Settings, features: list[str], user_id: str | None) -> str:
    """Short-lived signed OAuth `state` (CSRF protection + carries what the flow was for)."""
    exp = utcnow() + timedelta(minutes=10)
    return jwt.encode({"typ": "oauth_state", "features": features, "uid": user_id, "exp": _epoch(exp)},
                      settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_state(settings: Settings, state: str) -> dict:
    return decode_token(settings, state, "oauth_state")
