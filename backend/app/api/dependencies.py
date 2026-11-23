"""FastAPI dependencies: container, DB session, current user, rate limiting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError, RateLimitError
from app.core.logging import user_id_ctx
from app.core.security import TokenPayload, decode_access_token
from app.models.user import User, UserRole
from app.services.container import AppContainer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_settings_dep(container: Annotated[AppContainer, Depends(get_container)]) -> Settings:
    return container.settings


async def get_session(container: Annotated[AppContainer, Depends(get_container)]) -> AsyncIterator[AsyncSession]:
    async for session in container.db.session():
        yield session


ContainerDep = Annotated[AppContainer, Depends(get_container)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_token_payload(
    container: ContainerDep, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> TokenPayload:
    if not token:
        raise AuthenticationError("Not authenticated")
    payload = decode_access_token(token, container.settings)
    if await container.cache.is_token_revoked(payload.jti):
        raise AuthenticationError("Token has been revoked")
    return payload


async def get_current_user(
    session: SessionDep, payload: Annotated[TokenPayload, Depends(get_token_payload)]
) -> User:
    user = await session.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    user_id_ctx.set(str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Administrator role required")
    return user


async def rate_limit(request: Request, container: ContainerDep, user: CurrentUser) -> None:
    """Per-user fixed-window limit on authenticated endpoints."""
    limit = container.settings.rate_limit_per_minute
    if await container.cache.hit_rate_limit(f"user:{user.id}", limit):
        raise RateLimitError("Too many requests. Please slow down.", details={"limit_per_minute": limit})


async def auth_rate_limit(request: Request, container: ContainerDep) -> None:
    """Per-IP limit on credential endpoints (brute-force protection)."""
    ip = request.client.host if request.client else "unknown"
    limit = container.settings.auth_rate_limit_per_minute
    if await container.cache.hit_rate_limit(f"auth:{ip}", limit):
        raise RateLimitError("Too many authentication attempts. Try again in a minute.")


RateLimited = Depends(rate_limit)
