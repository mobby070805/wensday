from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as sc
from app.config import Settings
from app.core.timeutil import utcnow
from app.db import get_session
from app.deps import current_user, get_settings_dep, rate_limit, user_from_token
from app.integrations.google import GoogleError, GoogleOAuth, store_tokens
from app.models import OAuthAccount, RefreshToken, User
from app.security import TokenError, decode_token, hash_password, make_state, make_token, read_state, verify_password

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(rate_limit)])
_optional_bearer = HTTPBearer(auto_error=False)


async def issue_tokens(session: AsyncSession, settings: Settings, user: User) -> sc.TokenPair:
    access, _, _ = make_token(settings, user.id, "access")
    refresh, jti, exp = make_token(settings, user.id, "refresh")
    session.add(RefreshToken(jti=jti, user_id=user.id, expires_at=exp))
    await session.flush()
    return sc.TokenPair(access_token=access, refresh_token=refresh)


@router.post("/register", response_model=sc.TokenPair, status_code=201)
async def register(body: sc.RegisterIn, settings: Settings = Depends(get_settings_dep), session: AsyncSession = Depends(get_session)):
    email = body.email.strip().lower()
    if (await session.execute(select(User.id).where(User.email == email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password), timezone=settings.default_timezone)
    session.add(user)
    await session.flush()
    return await issue_tokens(session, settings, user)


@router.post("/login", response_model=sc.TokenPair)
async def login(body: sc.LoginIn, settings: Settings = Depends(get_settings_dep), session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).where(User.email == body.email.strip().lower(), User.deleted_at.is_(None)))).scalars().first()
    # same error for unknown user and wrong password: no account enumeration
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    return await issue_tokens(session, settings, user)


@router.post("/refresh", response_model=sc.TokenPair)
async def refresh(body: sc.RefreshIn, settings: Settings = Depends(get_settings_dep), session: AsyncSession = Depends(get_session)):
    try:
        payload = decode_token(settings, body.refresh_token, "refresh")
    except TokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from e
    row = await session.get(RefreshToken, payload["jti"])
    if row is None or row.expires_at < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    if row.revoked:
        # a rotated token was replayed: assume theft and kill every session for this user
        await session.execute(update(RefreshToken).where(RefreshToken.user_id == row.user_id).values(revoked=True))
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token reuse detected; please sign in again")
    user = await session.get(User, row.user_id)
    if not user or user.deleted_at:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    row.revoked = True
    return await issue_tokens(session, settings, user)


@router.post("/logout", status_code=204)
async def logout(body: sc.RefreshIn, settings: Settings = Depends(get_settings_dep), session: AsyncSession = Depends(get_session)):
    try:
        row = await session.get(RefreshToken, decode_token(settings, body.refresh_token, "refresh")["jti"])
    except TokenError:
        return
    if row:
        row.revoked = True


@router.get("/me", response_model=sc.UserOut)
async def me(user: User = Depends(current_user)):
    return user


@router.patch("/me", response_model=sc.UserOut)
async def update_me(body: sc.UserUpdate, user: User = Depends(current_user)):
    data = body.model_dump(exclude_unset=True)
    if "timezone" in data:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(data["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise HTTPException(422, "unknown timezone") from e
    for k, v in data.items():
        setattr(user, k, v)
    return user


# ------------------------------------------------------------------ Google OAuth
def _oauth(request: Request) -> GoogleOAuth:
    oauth: GoogleOAuth = request.app.state.google
    if not oauth.configured:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Google OAuth is not configured")
    return oauth


@router.get("/google/login")
async def google_login(request: Request, features: str = Query("", description="comma list: calendar,gmail_send,gmail_read"),
                       creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
                       settings: Settings = Depends(get_settings_dep), session: AsyncSession = Depends(get_session)):
    """Returns the Google consent URL. If the caller is signed in, the flow *connects* Google to that account."""
    oauth = _oauth(request)
    uid = (await user_from_token(session, settings, creds.credentials)).id if creds else None
    feats = [f for f in features.split(",") if f]
    return {"url": oauth.auth_url(make_state(settings, feats, uid), feats)}


@router.get("/google/callback")
async def google_callback(request: Request, code: str, state: str, settings: Settings = Depends(get_settings_dep),
                          session: AsyncSession = Depends(get_session)):
    oauth = _oauth(request)
    try:
        st = read_state(settings, state)
    except TokenError as e:
        raise HTTPException(400, "invalid or expired OAuth state") from e
    try:
        tok = await oauth.exchange_code(code)
        info = await oauth.userinfo(tok["access_token"])
    except (GoogleError, KeyError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Google sign-in failed") from e

    acct = (await session.execute(select(OAuthAccount).where(OAuthAccount.provider == "google", OAuthAccount.subject == info["sub"]))).scalars().first()
    if st.get("uid"):
        user = await session.get(User, st["uid"])
    elif acct:
        user = await session.get(User, acct.user_id)
    else:
        email = (info.get("email") or "").lower()
        user = (await session.execute(select(User).where(User.email == email))).scalars().first() if email else None
        if user is None:
            if not info.get("email_verified", False):
                raise HTTPException(400, "Google account email is not verified")
            user = User(email=email, name=info.get("name", ""), timezone=settings.default_timezone)
            session.add(user)
            await session.flush()
    await store_tokens(session, settings, user.id, info["sub"], tok)
    pair = await issue_tokens(session, settings, user)
    frag = urlencode({"access_token": pair.access_token, "refresh_token": pair.refresh_token})
    return RedirectResponse(f"{settings.web_origin}/auth/callback#{frag}")
