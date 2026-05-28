from __future__ import annotations

import hashlib
import json
import os
import secrets
from typing import Any

import redis as redis_lib


_TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    parts = stored_hash.split(":")
    if len(parts) != 2:
        return False
    try:
        salt = bytes.fromhex(parts[0])
        expected = bytes.fromhex(parts[1])
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return secrets.compare_digest(dk, expected)


def create_token(
    redis_client: redis_lib.Redis,
    user_id: str,
    username: str,
    display_name: str,
) -> str:
    token = secrets.token_urlsafe(32)
    payload = json.dumps({"user_id": user_id, "username": username, "display_name": display_name})
    redis_client.set(f"auth_session:{token}", payload, ex=_TOKEN_TTL_SECONDS)
    return token


def get_session(redis_client: redis_lib.Redis, token: str) -> dict[str, Any] | None:
    raw = redis_client.get(f"auth_session:{token}")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def revoke_token(redis_client: redis_lib.Redis, token: str) -> None:
    redis_client.delete(f"auth_session:{token}")


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None
