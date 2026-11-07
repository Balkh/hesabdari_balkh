"""RFC 6238 TOTP and single-use recovery-code primitives.

Persistence, enrollment state, rate limiting and account/session policy are
owned by the W0-2C domain services; this module contains deterministic,
side-effect-free cryptographic primitives only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import struct
import time

from django.contrib.auth.hashers import check_password, make_password


TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
TOTP_VALID_WINDOW = 1
TOTP_SECRET_BYTES = 20
RECOVERY_CODE_COUNT = 10


def generate_totp_secret() -> str:
    """Return a 160-bit CSPRNG secret encoded as unpadded Base32."""
    return base64.b32encode(os.urandom(TOTP_SECRET_BYTES)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    if not isinstance(secret, str) or not secret:
        raise ValueError("TOTP secret is required")
    normalized = secret.strip().upper()
    if not re.fullmatch(r"[A-Z2-7]+", normalized):
        raise ValueError("TOTP secret encoding is invalid")
    padded = normalized + ("=" * ((8 - len(normalized) % 8) % 8))
    try:
        decoded = base64.b32decode(padded, casefold=False)
    except Exception:
        raise ValueError("TOTP secret encoding is invalid") from None
    if len(decoded) < 16:
        raise ValueError("TOTP secret is too short")
    return decoded


def totp_code(secret: str, *, timestamp: float | None = None) -> str:
    """Compute a six-digit SHA-1 TOTP value for the supplied clock instant."""
    key = _decode_secret(secret)
    instant = time.time() if timestamp is None else float(timestamp)
    counter = int(instant // TOTP_PERIOD_SECONDS)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp(
    secret: str,
    code: str,
    *,
    timestamp: float | None = None,
    valid_window: int = TOTP_VALID_WINDOW,
) -> bool:
    """Constant-time comparison over the approved ±1 time-step window."""
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        return False
    if not isinstance(valid_window, int) or valid_window < 0 or valid_window > 1:
        raise ValueError("only the approved TOTP verification window is supported")
    instant = time.time() if timestamp is None else float(timestamp)
    for offset in range(-valid_window, valid_window + 1):
        candidate = totp_code(
            secret,
            timestamp=instant + (offset * TOTP_PERIOD_SECONDS),
        )
        if hmac.compare_digest(candidate, code):
            return True
    return False


def generate_recovery_codes() -> list[str]:
    """Generate exactly ten high-entropy, one-time recovery codes."""
    return [
        base64.b32encode(os.urandom(10)).decode("ascii").rstrip("=")
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def hash_recovery_code(code: str) -> str:
    """Return a salted Django password hash; never store a raw recovery code."""
    if not isinstance(code, str) or not code:
        raise ValueError("recovery code is required")
    return make_password(code)


def verify_recovery_code(code: str, encoded_hash: str) -> bool:
    """Verify a submitted code against its salted password hash."""
    if not isinstance(code, str) or not isinstance(encoded_hash, str):
        return False
    return check_password(code, encoded_hash)
