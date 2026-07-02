import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from backend.config import settings

logger = logging.getLogger("loom.db.base")

# Database URL for async ORM
DATABASE_URL = settings.database_url

# Create Async Engine
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# Session factory for async transactions
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Declarative Base for models
Base = declarative_base()

async def get_db():
    """
    FastAPI dependency yielding async database sessions.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
