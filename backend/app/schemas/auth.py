from datetime import datetime

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=12, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    # Required only when the server runs in SIGNUP_MODE=invite (Step 5).
    invite_code: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class GoogleAuthRequest(BaseModel):
    # The ID token (a JWT "credential") issued by Google Identity Services in the
    # browser. Verified server-side against GOOGLE_CLIENT_ID.
    credential: str = Field(..., min_length=10, max_length=4096)


class UpdateProfileRequest(BaseModel):
    # Display name shown around the app. Empty string clears it back to null.
    full_name: str | None = Field(default=None, max_length=255)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None = None
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
