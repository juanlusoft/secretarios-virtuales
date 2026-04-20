"""Versioned migration runner. Run with: python -m shared.db.migrate"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "infrastructure" / "db" / "migrations"


async def run_migrations(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        applied = {row["version"] for row in await conn.fetch("SELECT version FROM schema_migrations")}

        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not sql_files:
            logger.info("No migration files found in %s", MIGRATIONS_DIR)
            return

        for sql_file in sql_files:
            version = sql_file.name
            if version in applied:
                logger.info("Migration %s already applied, skipping", version)
                continue

            logger.info("Applying migration %s...", version)
            sql = sql_file.read_text(encoding="utf-8")
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version) VALUES ($1)", version
            )
            logger.info("Migration %s applied", version)

    finally:
        await conn.close()


async def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    dsn = os.environ["DATABASE_URL"]
    await run_migrations(dsn)


if __name__ == "__main__":
    asyncio.run(main())
