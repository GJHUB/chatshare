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


async def ensure_schema():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_audit (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
                username VARCHAR(255) NOT NULL,
                ip VARCHAR(64),
                user_agent TEXT,
                login_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_login_audit_login_at ON login_audit(login_at DESC)
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_login_audit_user_id ON login_audit(user_id)
            """
        )


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
