"""Authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import ContainerDep, CurrentUser, SessionDep, auth_rate_limit, get_token_payload
from app.core.security import TokenPayload, create_access_token
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.schemas.common import MessageResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(auth_rate_limit)])
async def register(body: RegisterRequest, session: SessionDep, container: ContainerDep) -> UserResponse:
    """Create an account. Emails listed in ``ADMIN_EMAILS`` receive the admin role."""
    user = await auth_service.register_user(
        session, container.settings, email=body.email, password=body.password, full_name=body.full_name
    )
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(auth_rate_limit)])
async def login(body: LoginRequest, session: SessionDep, container: ContainerDep) -> TokenResponse:
    """Exchange email + password for a JWT access token."""
    user = await auth_service.authenticate(session, email=body.email, password=body.password)
    token, expires = create_access_token(user.id, user.role.value, container.settings)
    return TokenResponse(access_token=token, expires_in=expires)


@router.post("/token", response_model=TokenResponse, include_in_schema=True,
             dependencies=[Depends(auth_rate_limit)], summary="OAuth2 form login (used by Swagger 'Authorize')")
async def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep,
                container: ContainerDep) -> TokenResponse:
    user = await auth_service.authenticate(session, email=form.username, password=form.password)
    access, expires = create_access_token(user.id, user.role.value, container.settings)
    return TokenResponse(access_token=access, expires_in=expires)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: Annotated[TokenPayload, Depends(get_token_payload)], container: ContainerDep) -> MessageResponse:
    """Revoke the current token (its ``jti`` is deny-listed in Redis until it expires)."""
    ttl = int((payload.expires_at - datetime.now(UTC)).total_seconds())
    await container.cache.revoke_token(payload.jti, ttl)
    return MessageResponse(message="Logged out")
