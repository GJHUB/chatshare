import os
import asyncpg
import logging

logger = logging.getLogger(__name__)

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://chatshare:chatshare2026@100.87.204.122:5432/chatshare_db"
)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DB_DSN, min_size=2, max_size=10)
        logger.info("Database pool created")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
