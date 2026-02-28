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

        await conn.execute(
            """
            ALTER TABLE chat_messages
            ADD COLUMN IF NOT EXISTS attachments JSONB
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES chat_users(id) ON DELETE CASCADE,
                name VARCHAR(128) NOT NULL DEFAULT 'default',
                key_hash VARCHAR(128) NOT NULL UNIQUE,
                scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
                model_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
                qps_limit INTEGER,
                rpm_limit INTEGER,
                tpm_limit INTEGER,
                status VARCHAR(32) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_requests (
                id VARCHAR(64) PRIMARY KEY,
                api_key VARCHAR(255),
                user_id INTEGER,
                endpoint VARCHAR(255) NOT NULL,
                model VARCHAR(128),
                status_code INTEGER,
                latency_ms INTEGER,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                error_code VARCHAR(64),
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_requests_created_at ON api_requests(created_at DESC)
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_api_requests_api_key ON api_requests(api_key)
            """
        )


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
