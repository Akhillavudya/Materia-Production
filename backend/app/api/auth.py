"""Authentication endpoints (signup, login, google, me)."""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.database.db import get_db
from app.database.models import User
from app.repositories import user_repository
from app.schemas.auth import (
    GoogleAuthRequest,
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _invite_code_ok(code: str | None) -> bool:
    """Constant-time match of a submitted code against the configured codes."""
    if not code:
        return False
    code = code.strip()
    # compare against every configured code so timing doesn't leak which matched
    return any(secrets.compare_digest(code, valid) for valid in settings.invite_codes)


def _enforce_signup_allowed(invite_code: str | None) -> None:
    """Apply the SIGNUP_MODE gate (Step 5). Raises HTTPException when blocked."""
    mode = settings.signup_mode
    if mode == "closed":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signups are disabled. Contact the administrator for an account.",
        )
    if mode == "invite" and not _invite_code_ok(invite_code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid invite code is required to sign up.",
        )


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token({"sub": str(user.id)}),
        user=_user_out(user),
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def signup(request: Request, body: SignupRequest, db: AsyncSession = Depends(get_db)):
    _enforce_signup_allowed(body.invite_code)

    email = _normalize_email(body.email)
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")

    if await user_repository.get_by_email(db, email) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await user_repository.create(
        db,
        email=email,
        full_name=body.full_name.strip() if body.full_name else None,
        hashed_password=get_password_hash(body.password),
    )
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = _normalize_email(body.email)
    user = await user_repository.get_by_email(db, email)

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")

    return _token_response(user)


def _verify_google_credential(credential: str) -> dict:
    """Verify a Google ID token and return its claims, or raise HTTPException.

    Uses google-auth to check the signature against Google's public keys, the
    audience (our GOOGLE_CLIENT_ID) and the issuer/expiry. We never trust the
    token's contents until this passes.
    """
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this server.",
        )
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        claims = google_id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError as exc:
        # Bad signature, wrong audience, expired, malformed — all surface here.
        logger.warning("Google credential verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not verify Google sign-in. Please try again.",
        ) from exc

    if not claims.get("email"):
        raise HTTPException(status_code=401, detail="Google account has no email.")
    if claims.get("email_verified") is False:
        raise HTTPException(
            status_code=403,
            detail="Your Google email is not verified. Verify it with Google first.",
        )
    return claims


@router.post("/google", response_model=TokenResponse)
@limiter.limit("10/minute")
async def google_login(
    request: Request,
    body: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """Sign in (or register) with a Google ID token.

    Existing users are always signed in. A brand-new Google user is created only
    when SIGNUP_MODE='open' — so an invite-only/closed production server still
    requires the admin to provision accounts, matching email/password signup.
    """
    claims = _verify_google_credential(body.credential)
    email = _normalize_email(claims["email"])

    user = await user_repository.get_by_email(db, email)
    if user is None:
        if settings.signup_mode != "open":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No account exists for this Google email. "
                "Ask the administrator to create one.",
            )
        # New OAuth user: no password to log in with, so store an unusable random
        # hash (keeps the NOT NULL column valid without a schema change).
        user = await user_repository.create(
            db,
            email=email,
            full_name=(claims.get("name") or "").strip() or None,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")

    return _token_response(user)


@router.get("/config")
async def auth_config():
    """Public, unauthenticated hint so the auth UI can adapt to the gate.

    Returns only the signup mode and the *public* Google client ID (never the
    invite codes or any secret).
    """
    return {
        "signup_mode": settings.signup_mode,
        "google_enabled": bool(settings.google_client_id),
        "google_client_id": settings.google_client_id,
        # Whether the heavy ML-potential simulation tools run on this server. On the
        # lite web edition this is false: the UI keeps the tools visible but tells
        # users to install the desktop app when they try to run one.
        "heavy_tools_enabled": settings.enable_heavy_tools,
    }


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the signed-in user's editable profile fields (display name)."""
    full_name = body.full_name.strip() if body.full_name else None
    user = await user_repository.update(db, current_user, full_name=full_name or None)
    return _user_out(user)
