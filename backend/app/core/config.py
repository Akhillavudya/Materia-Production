"""Centralized application configuration.

Single source of truth for all *startup* configuration, loaded once from the
environment (and an optional `.env`). Per-user secrets such as Materials Project
or OpenAI keys are intentionally NOT held here — those are user-scoped and are
injected into `os.environ` at request time by `services.key_service`.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


def _split_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


class Settings(BaseModel):
    """Immutable, validated view of the runtime environment."""

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "Materia Production Backend"

    # ── Auth / security ──────────────────────────────────────────────────────
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    field_encryption_key: str = ""

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

    # ── LLM provider ─────────────────────────────────────────────────────────
    model_provider: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"

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


@lru_cache
def get_settings() -> Settings:
    """Return the cached `Settings` instance built from the environment."""
    return Settings(
        jwt_secret_key=os.getenv("JWT_SECRET_KEY"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")),
        field_encryption_key=os.getenv("FIELD_ENCRYPTION_KEY", ""),
        allowed_origins=_split_origins(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
        ),
        database_url_env=os.getenv("DATABASE_URL"),
        db_path=os.getenv("DB_PATH", "materia.db"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        job_backend=os.getenv("JOB_BACKEND", "celery"),
        max_job_wallclock_s=int(os.getenv("MAX_JOB_WALLCLOCK_S", "86400")),
        storage_root=os.getenv("STORAGE_ROOT"),
        vasp_ncore=(int(os.environ["VASP_NCORE"]) if os.getenv("VASP_NCORE") else None),
        pmg_vasp_psp_dir=os.getenv("PMG_VASP_PSP_DIR"),
        model_provider=os.getenv("MODEL_PROVIDER"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:14b"),
    )


settings = get_settings()
