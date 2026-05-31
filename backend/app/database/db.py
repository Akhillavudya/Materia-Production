import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.database.models import Base

# materia.db will be created in your project root automatically
DB_PATH = os.getenv('DB_PATH', 'materia.db')
DATABASE_URL = f'sqlite+aiosqlite:///{DB_PATH}'

# echo=False means SQLAlchemy won't print every SQL query to the terminal
# change to echo=True temporarily if you want to debug what's being stored
engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # keeps objects readable after commit
)

async def init_db():
    '''Create all tables if they don't exist yet. Called once on startup.'''
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    '''
    FastAPI dependency — yields a database session to each route,
    then closes it automatically when the route finishes.
    Usage in a route: db: AsyncSession = Depends(get_db)
    '''
    async with AsyncSessionLocal() as session:
        yield session