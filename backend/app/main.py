"""FastAPI application factory and startup."""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import configure_logging, get_logger, get_request_id
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.api.auth import router as auth_router
from app.api.catalog import router as catalog_router
from app.api.chat import router as chat_router
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.keys import router as keys_router
from app.api.models import router as models_router
from app.api.upload import router as upload_router
from app.database.db import init_db

configure_logging()
logger = get_logger(__name__)

# Step 6: hide the interactive API explorer (/docs, /redoc, /openapi.json) in
# production so the full route map + schemas aren't published to the world.
_docs_kwargs: dict = {}
if settings.is_production:
    _docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(title=settings.app_name, **_docs_kwargs)
app.state.limiter = limiter

# Middleware order matters: the LAST one added runs OUTERMOST. We want the
# request-context net (request id + catch-all 500) to wrap everything, so it is
# added last. Security headers sit just inside it; CORS + rate limiting inside that.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)

app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Step 6: global error handling ────────────────────────────────────────────
# Known, expected errors keep their status + message (they don't leak internals).
# Anything truly unexpected is caught by RequestContextMiddleware → generic 500.

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": get_request_id()},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # 422s are safe to surface (they describe the client's own bad input).
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "request_id": get_request_id()},
    )


# Health/readiness mounted at root so the container HEALTHCHECK and uptime
# monitors hit /health and /ready directly (Caddy also forwards them).
app.include_router(health_router)

app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(keys_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(catalog_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(models_router, prefix="/api")


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("Materia backend started — %s", settings.app_name)


@app.get("/")
def root():
    return {"message": "Materia backend is running"}
