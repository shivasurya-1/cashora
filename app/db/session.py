from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings
import ssl

# 1. Clean the URL: asyncpg doesn't like 'sslmode' or 'channel_binding' in the string
db_url = settings.DATABASE_URL
if "?" in db_url:
    # We strip the query parameters and handle them in connect_args instead
    db_url = db_url.split("?")[0]

# 2. Create a healthy engine using an SSLContext and pool pre-ping so closed connections are detected
# Use ssl.create_default_context() (asyncpg accepts an SSLContext) instead of bare True
ssl_ctx = ssl.create_default_context()

engine = create_async_engine(
    db_url,
    echo=True,
    pool_pre_ping=True,  # check connection health before using a connection from the pool
    pool_size=5,
    max_overflow=10,
    connect_args={
        "ssl": ssl_ctx,
        "statement_cache_size": 0,  # disable asyncpg prepared statement cache to avoid stale plans after migrations
        "server_settings": {
            "jit": "off", # Recommended for Neon/serverless performance
        }
    }
)

async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_db():
    async with async_session() as session:
        yield session