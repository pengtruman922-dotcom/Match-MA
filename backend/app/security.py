"""Password hashing (scrypt) and HMAC-SHA256 signed bearer tokens.

Standard-library only: hashlib.scrypt for password storage and a minimal
JWT-compatible HS256 implementation for access tokens, so no extra
dependencies are needed on deploy.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
_SALT_BYTES = 16
_KEY_LENGTH = 32


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAXMEM,
        dklen=_KEY_LENGTH,
    )
    return "$".join(
        [
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _b64url_encode(salt),
            _b64url_encode(key),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n_text, r_text, p_text, salt_text, key_text = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        salt = _b64url_decode(salt_text)
        expected_key = _b64url_decode(key_text)
        key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_text),
            r=int(r_text),
            p=int(p_text),
            maxmem=SCRYPT_MAXMEM,
            dklen=len(expected_key),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key, expected_key)


def _b64url_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64url_encode(raw)


def _signature(signing_input: str, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()


def create_access_token(
    *,
    secret: str,
    user_id: str,
    role: str,
    name: str,
    expires_in_seconds: int,
) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "role": role,
        "name": name,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    signing_input = f"{_b64url_json(header)}.{_b64url_json(payload)}"
    return f"{signing_input}.{_b64url_encode(_signature(signing_input, secret))}"


def decode_access_token(token: str, *, secret: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    signing_input = f"{parts[0]}.{parts[1]}"
    try:
        signature = _b64url_decode(parts[2])
        if not hmac.compare_digest(signature, _signature(signing_input, secret)):
            return None
        payload = json.loads(_b64url_decode(parts[1]))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int | float) or expires_at < time.time():
        return None
    return payload
