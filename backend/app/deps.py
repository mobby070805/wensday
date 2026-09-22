from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import get_session
from .models import User
from .security import TokenError, decode_token

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


async def user_from_token(session: AsyncSession, settings: Settings, token: str) -> User:
    try:
        payload = decode_token(settings, token, "access")
    except TokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from e
    user = await session.get(User, payload["sub"])
    if not user or user.deleted_at:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return user


async def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    return await user_from_token(session, request.app.state.settings, creds.credentials)


async def rate_limit(request: Request) -> None:
    settings: Settings = request.app.state.settings
    ip = request.client.host if request.client else "anon"
    n = await request.app.state.cache.incr_window(f"rl:{ip}", 60)
    if n > settings.rate_limit_per_minute:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")
