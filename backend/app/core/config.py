"""Centralized application configuration.

Single source of truth for all *startup* configuration, loaded once from the
environment (and an optional `.env`). Per-user secrets such as Materials Project
or OpenAI keys are intentionally NOT held here — those are user-scoped and are
injected into `os.environ` at request time by `services.key_service`.
"""

import os
from functools import lru_cache

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


def _split_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _split_csv(raw: str) -> list[str]:
    """Split a comma-separated env value into a clean list (case preserved)."""
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


# Secrets that must never be used in production — placeholders / known defaults.
_WEAK_SECRETS = {"", "my-super-secret-key", "change-me-to-a-long-random-secret",
                 "changeme", "secret", "dev", "test"}


def _is_strong_secret(value: str | None) -> bool:
    """A login secret is acceptable only if it is non-default and long enough."""
    return bool(value) and value not in _WEAK_SECRETS and len(value) >= 32


def _valid_fernet(value: str | None) -> bool:
    """True when `value` is a usable Fernet key (encrypts BYOK keys at rest)."""
    if not value:
        return False
    try:
        Fernet(value.encode())
        return True
    except Exception:
        return False


class Settings(BaseModel):
    """Immutable, validated view of the runtime environment."""

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "Materia Production Backend"
    # Deployment environment. "production"/"prod" turns on fail-fast secret checks
    # (see `get_settings`). Anything else (default) keeps local dev frictionless.
    env: str = "development"

    # ── Auth / security ──────────────────────────────────────────────────────
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    field_encryption_key: str = ""

    # ── Google sign-in (OAuth via Google Identity Services) ──────────────────
    # The OAuth 2.0 *Web* client ID from Google Cloud Console. When set, the UI
    # shows a working "Continue with Google" button: the browser obtains a Google
    # ID token which the backend verifies against this client ID before issuing a
    # Materia session. Left unset → the Google button stays disabled (email/password
    # still works). This is a public value; safe to expose to the frontend.
    google_client_id: str | None = None

    # ── Signup gating (Step 5 — invite-only lab access) ──────────────────────
    # signup_mode: "open"   — anyone may register (dev default)
    #              "invite" — registration requires a code from `invite_codes`
    #              "closed" — registration disabled entirely (admin-created only)
    # In production the mode defaults to "invite" (see `get_settings`) so a public
    # URL is never accidentally open. `invite_codes` is a list of accepted codes
    # (one shared, or one-per-student so individuals can be revoked).
    signup_mode: str = "open"
    invite_codes: list[str] = Field(default_factory=list)

    # ── CORS ─────────────────────────────────────────────────────────────────
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )

    # ── Database ─────────────────────────────────────────────────────────────
    # Production: set DATABASE_URL to a PostgreSQL DSN, e.g.
    #   postgresql://user:pass@host:5432/materia
    # When unset, falls back to the local SQLite file at `db_path` so the app
    # still boots for dev without a running Postgres.
    database_url_env: str | None = None
    db_path: str = "materia.db"

    # ── Job system (redesign §11) ────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    job_backend: str = "celery"            # celery | inline (inline = dev/no-broker)
    max_job_wallclock_s: int = 86400       # hard cap before a job is failed

    # ── Compute caps & quotas (Step 4) ───────────────────────────────────────
    # Protect a small/free server from runaway simulations and job spam. All are
    # env-overridable so a bigger deployment can raise them.
    max_opt_steps: int = 5000              # ceiling for an optimization run
    max_md_steps: int = 50000              # ceiling for MD steps (nsw)
    max_atoms: int = 512                   # reject structures larger than this
    max_active_jobs_per_user: int = 3      # queued+running jobs allowed per user
    max_upload_mb: int = 25                # per-file upload size limit

    # ── Storage / compute ────────────────────────────────────────────────────
    # Optional overrides; storage defaults to app/storage/runs (file_service).
    storage_root: str | None = None
    # NCORE for generated INCARs. Left unset (None) → omitted so VASP auto-parallelises
    # rather than hardcoding a value that mis-parallelises on other machines (§9).
    vasp_ncore: int | None = None
    # Licensed VASP PAW potential directory (POT_GGA_PAW_PBE/...). When set, a real
    # POTCAR is assembled and authoritative ENMAX is read from it; otherwise only a
    # POTCAR.spec (labels + recommended ENMAX) is emitted. POTCARs are never shipped.
    pmg_vasp_psp_dir: str | None = None
    # Which PAW functional folder to read from the PSP dir. pymatgen maps this to a
    # subdir, e.g. "PBE_54" → POT_GGA_PAW_PBE_54, "PBE" → POT_GGA_PAW_PBE. Set this to
    # match the library you mount (default PBE_54).
    pmg_vasp_functional: str = "PBE_54"

    # ── LLM provider ─────────────────────────────────────────────────────────
    # The agent uses native function-calling (redesign §15). `model_provider`
    # selects the backend: "gemini" (hosted default), "groq", or "ollama"
    # (offline/local). When unset it auto-resolves in order of available keys:
    # gemini → groq → ollama. Gemini is primary because its free tier is
    # request-metered (not token-metered), so the ~8k-token tool schema sent on
    # every call doesn't drain its quota the way it drains Groq's daily token cap;
    # T4 also showed gemini-2.5-flash at 100% tool-selection vs Groq's judgment
    # misses. Whichever is primary falls through the others at runtime
    # (see agent/llm.py) on quota/429/connection errors.
    model_provider: str | None = None
    # Groq (free hosted tier — OpenAI-compatible, native tool calling, fast)
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    # Gemini (Google AI Studio free tier — native function calling)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # Ollama (local fallback; qwen3 supports native tools)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"

    @property
    def resolved_provider(self) -> str:
        """The effective LLM provider after auto-detection."""
        if self.model_provider:
            return self.model_provider.lower().strip()
        if self.gemini_api_key or os.getenv("GEMINI_API_KEY"):
            return "gemini"
        if self.groq_api_key or os.getenv("GROQ_API_KEY"):
            return "groq"
        return "ollama"

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL (asyncpg for Postgres, aiosqlite for SQLite)."""
        if self.database_url_env:
            return _as_async_url(self.database_url_env)
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def database_url_sync(self) -> str:
        """Sync SQLAlchemy URL — used by the Celery worker for progress writes."""
        if self.database_url_env:
            return _as_sync_url(self.database_url_env)
        return f"sqlite:///{self.db_path}"

    @property
    def is_postgres(self) -> bool:
        return bool(self.database_url_env) and "postgres" in self.database_url_env

    @property
    def is_production(self) -> bool:
        return self.env.lower().strip() in {"production", "prod"}


def _as_async_url(raw: str) -> str:
    """Normalise a DSN to an async driver (postgresql+asyncpg / sqlite+aiosqlite)."""
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        return "postgresql+asyncpg://" + raw[len("postgresql://"):]
    if raw.startswith("sqlite://") and "+aiosqlite" not in raw:
        return "sqlite+aiosqlite://" + raw[len("sqlite://"):]
    return raw


def _as_sync_url(raw: str) -> str:
    """Normalise a DSN to a sync driver (postgresql+psycopg2 / sqlite)."""
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg2://" + raw[len("postgresql://"):]
    # strip any async driver suffixes
    return raw.replace("+asyncpg", "").replace("+aiosqlite", "")


def _validate_production(s: "Settings") -> None:
    """Refuse to run in production with weak/missing secrets (fail-fast).

    Only enforced when ENV=production, so local dev and tests are unaffected.
    """
    problems: list[str] = []
    if not _is_strong_secret(s.jwt_secret_key):
        problems.append(
            "JWT_SECRET_KEY is missing, a known placeholder, or shorter than 32 chars. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    if not _valid_fernet(s.field_encryption_key):
        problems.append(
            "FIELD_ENCRYPTION_KEY is missing or not a valid Fernet key, so user API keys "
            "would be stored UNENCRYPTED. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    if not s.database_url_env:
        problems.append(
            "DATABASE_URL is not set. Production requires PostgreSQL — the SQLite fallback is "
            "unsafe with separate api + worker processes. Set DATABASE_URL=postgresql://..."
        )
    elif not s.is_postgres:
        problems.append(
            "DATABASE_URL must point to PostgreSQL in production (SQLite is single-writer and "
            "corrupts under the concurrent api + worker access)."
        )
    if not s.allowed_origins or "*" in s.allowed_origins:
        problems.append(
            "ALLOWED_ORIGINS must list your exact site origin(s) in production "
            "(e.g. https://materia.example.com). A wildcard '*' is rejected — it "
            "exposes the API to every site and is incompatible with credentialed CORS."
        )
    if s.signup_mode not in {"open", "invite", "closed"}:
        problems.append(
            f"SIGNUP_MODE='{s.signup_mode}' is invalid. Use 'open', 'invite', or 'closed'."
        )
    if s.signup_mode == "invite" and not s.invite_codes:
        problems.append(
            "SIGNUP_MODE=invite but INVITE_CODES is empty — nobody could register. Set "
            "INVITE_CODES=code1,code2 (share with your lab), or use SIGNUP_MODE=closed."
        )
    if problems:
        raise RuntimeError(
            "Refusing to start in production (ENV=production):\n  - "
            + "\n  - ".join(problems)
        )


@lru_cache
def get_settings() -> Settings:
    """Return the cached `Settings` instance built from the environment."""
    env = os.getenv("ENV", "development")
    is_prod = env.lower().strip() in {"production", "prod"}
    # Default to invite-only in production so a public URL is never open by accident;
    # dev stays "open" for frictionless local testing. Either is overridable via env.
    signup_mode = (os.getenv("SIGNUP_MODE") or ("invite" if is_prod else "open")).lower().strip()

    s = Settings(
        env=env,
        signup_mode=signup_mode,
        invite_codes=_split_csv(os.getenv("INVITE_CODES", "")),
        jwt_secret_key=os.getenv("JWT_SECRET_KEY"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")),
        field_encryption_key=os.getenv("FIELD_ENCRYPTION_KEY", ""),
        google_client_id=(os.getenv("GOOGLE_CLIENT_ID") or "").strip() or None,
        allowed_origins=_split_origins(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
        ),
        database_url_env=os.getenv("DATABASE_URL"),
        db_path=os.getenv("DB_PATH", "materia.db"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        job_backend=os.getenv("JOB_BACKEND", "celery"),
        max_job_wallclock_s=int(os.getenv("MAX_JOB_WALLCLOCK_S", "86400")),
        max_opt_steps=int(os.getenv("MAX_OPT_STEPS", "5000")),
        max_md_steps=int(os.getenv("MAX_MD_STEPS", "50000")),
        max_atoms=int(os.getenv("MAX_ATOMS", "512")),
        max_active_jobs_per_user=int(os.getenv("MAX_ACTIVE_JOBS_PER_USER", "3")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "25")),
        storage_root=os.getenv("STORAGE_ROOT"),
        vasp_ncore=(int(os.environ["VASP_NCORE"]) if os.getenv("VASP_NCORE") else None),
        pmg_vasp_psp_dir=os.getenv("PMG_VASP_PSP_DIR"),
        pmg_vasp_functional=os.getenv("PMG_VASP_FUNCTIONAL", "PBE_54"),
        model_provider=os.getenv("MODEL_PROVIDER"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:14b"),
    )
    if s.is_production:
        _validate_production(s)
    return s


settings = get_settings()
