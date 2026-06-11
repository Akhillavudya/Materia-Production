"""FastAPI application factory and startup."""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import configure_logging, get_logger
from app.api.auth import router as auth_router
from app.api.catalog import router as catalog_router
from app.api.chat import router as chat_router
from app.api.files import router as files_router
from app.api.keys import router as keys_router
from app.api.upload import router as upload_router
from app.database.db import init_db

configure_logging()
logger = get_logger(__name__)

app = FastAPI(title=settings.app_name)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(keys_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(catalog_router, prefix="/api")


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("Materia backend started — %s", settings.app_name)


@app.get("/")
def root():
    return {"message": "Materia backend is running"}
