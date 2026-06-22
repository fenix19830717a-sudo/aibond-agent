from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# Conditional engine args: SQLite needs check_same_thread=False, PostgreSQL does not
engine_args: dict = {}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}

# Disable echo in production to prevent SQL leakage in logs
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    **engine_args,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with async_session() as session:
        yield session
