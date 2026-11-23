"""Password hashing and JWT token utilities.

* Passwords are hashed with bcrypt (salted, adaptive cost). bcrypt only uses the
  first 72 bytes of input, so longer passwords are pre-hashed with SHA-256 to
  avoid silent truncation.
* Access tokens are signed JWTs carrying ``sub`` (user id), ``role`` and a
  unique ``jti`` so individual tokens can be revoked on logout.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import AuthenticationError


def _prepare(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raw = base64.b64encode(hashlib.sha256(raw).digest())
    return raw


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time password verification."""
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Decoded, validated access-token claims."""

    user_id: uuid.UUID
    role: str
    jti: str
    expires_at: datetime


def create_access_token(user_id: uuid.UUID, role: str, settings: Settings) -> tuple[str, int]:
    """Create a signed access token. Returns ``(token, expires_in_seconds)``."""
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "role": role,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "type": "access",
    }
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str, settings: Settings) -> TokenPayload:
    """Validate a token's signature/expiry and return its claims."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "jti"]},
        )
        if claims.get("type") != "access":
            raise AuthenticationError("Invalid token type")
        return TokenPayload(
            user_id=uuid.UUID(claims["sub"]),
            role=str(claims.get("role", "user")),
            jti=str(claims["jti"]),
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired") from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise AuthenticationError("Invalid authentication token") from exc
