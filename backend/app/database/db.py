from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.models import Base

# materia.db will be created in the backend working directory automatically
DATABASE_URL = settings.database_url

# echo=False means SQLAlchemy won't print every SQL query to the terminal
# change to echo=True temporarily if you want to debug what's being stored
_engine_kwargs: dict = {"echo": False}
if settings.is_postgres:
    # Keep pooled connections healthy across idle periods / DB restarts:
    #   pool_pre_ping  — test a connection before use, transparently replace dead ones
    #   pool_recycle   — drop connections older than 30 min (avoids server-side timeouts)
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=10,
    )
engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # keeps objects readable after commit
)


_KNOWN_TABLES = frozenset({'sessions', 'messages', 'api_keys', 'users'})


async def _sqlite_columns(conn, table_name: str) -> set[str]:
    if table_name not in _KNOWN_TABLES:
        raise ValueError(f"Unknown table: {table_name}")
    result = await conn.execute(text(f'PRAGMA table_info({table_name})'))
    return {row[1] for row in result.fetchall()}


async def _sqlite_table_exists(conn, table_name: str) -> bool:
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {'name': table_name},
    )
    return result.scalar_one_or_none() is not None


async def _run_safe_schema_updates(conn) -> None:
    """
    Apply additive dev migrations for auth ownership columns.

    Existing dev databases may already contain sessions/messages/api_keys from
    before auth existed. These updates do not delete data. Legacy rows keep a
    NULL user_id and are intentionally hidden from authenticated routes until a
    project-specific backfill or destructive reset assigns an owner.
    """
    if await _sqlite_table_exists(conn, 'sessions'):
        session_columns = await _sqlite_columns(conn, 'sessions')
        if 'user_id' not in session_columns:
            await conn.execute(text('ALTER TABLE sessions ADD COLUMN user_id INTEGER'))
        await conn.execute(text('CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id)'))
        await conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_sessions_user_id_created_at '
            'ON sessions (user_id, created_at)'
        ))

    if await _sqlite_table_exists(conn, 'messages'):
        await conn.execute(text('CREATE INDEX IF NOT EXISTS ix_messages_session_id ON messages (session_id)'))
        await conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_messages_session_id_id '
            'ON messages (session_id, id)'
        ))

    if await _sqlite_table_exists(conn, 'api_keys'):
        api_key_columns = await _sqlite_columns(conn, 'api_keys')
        if 'user_id' not in api_key_columns:
            await conn.execute(text('ALTER TABLE api_keys ADD COLUMN user_id INTEGER'))
        if 'created_at' not in api_key_columns:
            await conn.execute(text('ALTER TABLE api_keys ADD COLUMN created_at DATETIME'))
        if 'updated_at' not in api_key_columns:
            await conn.execute(text('ALTER TABLE api_keys ADD COLUMN updated_at DATETIME'))
        await conn.execute(text('CREATE INDEX IF NOT EXISTS ix_api_keys_user_id ON api_keys (user_id)'))
        await conn.execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_user_service '
            'ON api_keys (user_id, service) WHERE user_id IS NOT NULL'
        ))
        await conn.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_api_keys_user_id_service '
            'ON api_keys (user_id, service)'
        ))


async def init_db():
    '''Create all tables if they don't exist yet. Called once on startup.'''
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if DATABASE_URL.startswith('sqlite'):
            await _run_safe_schema_updates(conn)

async def get_db():
    '''
    FastAPI dependency — yields a database session to each route,
    then closes it automatically when the route finishes.
    Usage in a route: db: AsyncSession = Depends(get_db)
    '''
    async with AsyncSessionLocal() as session:
        yield session
