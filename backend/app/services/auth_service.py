"""User registration and authentication."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole

# Pre-computed hash used to equalise timing when the email does not exist
# (prevents user enumeration via response-time differences).
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password-1")


async def register_user(session: AsyncSession, settings: Settings, *, email: str, password: str,
                        full_name: str | None) -> User:
    email = email.strip().lower()
    role = UserRole.ADMIN if email in {e.lower() for e in settings.admin_emails} else UserRole.USER
    user = User(email=email, hashed_password=hash_password(password), full_name=full_name, role=role)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("An account with this email already exists") from exc
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    stmt = select(User).where(func.lower(User.email) == email.strip().lower())
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthenticationError("Invalid email or password")
    if not verify_password(password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")
    if not user.is_active:
        raise AuthenticationError("Account is disabled")
    return user
