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
    db_path: str = "materia.db"

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
        return f"sqlite+aiosqlite:///{self.db_path}"


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
        db_path=os.getenv("DB_PATH", "materia.db"),
        storage_root=os.getenv("STORAGE_ROOT"),
        vasp_ncore=(int(os.environ["VASP_NCORE"]) if os.getenv("VASP_NCORE") else None),
        pmg_vasp_psp_dir=os.getenv("PMG_VASP_PSP_DIR"),
        model_provider=os.getenv("MODEL_PROVIDER"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:14b"),
    )


settings = get_settings()
