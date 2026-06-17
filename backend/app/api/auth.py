"""Authentication endpoints (signup, login, me)."""

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
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserOut

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


@router.get("/config")
async def auth_config():
    """Public, unauthenticated hint so the signup UI can adapt to the gate.

    Returns only the mode — never the invite codes themselves.
    """
    return {"signup_mode": settings.signup_mode}


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)
