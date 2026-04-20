from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.embeddings import EmbeddingClient
from shared.vault.syncer import VaultSyncer

load_dotenv()
logger = logging.getLogger(__name__)


async def _fetch_active_employees(dsn: str) -> list[dict]:
    conn = await asyncpg.connect(dsn)
    rows = await conn.fetch(
        "SELECT id, name FROM employees WHERE is_active = true AND is_orchestrator = false"
    )
    await conn.close()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


async def run_once(
    dsn: str,
    embed: EmbeddingClient,
    vaults_dir: Path,
) -> None:
    employees = await _fetch_active_employees(dsn)
    for emp in employees:
        pool = DatabasePool(dsn, emp["id"])
        await pool.connect()
        try:
            syncer = VaultSyncer(
                pool=pool,
                employee_id=emp["id"],
                employee_name=emp["name"],
                embed=embed,
                vaults_dir=vaults_dir,
            )
            result = await syncer.sync()
            logger.info(
                "Vault sync %s: +%d ~%d -%d skip%d",
                emp["name"], result.added, result.updated, result.deleted, result.skipped,
            )
        except Exception:
            logger.exception("Vault sync failed for employee %s", emp["name"])
        finally:
            await pool.disconnect()


async def main() -> None:
    vaults_dir_str = os.environ.get("OBSIDIAN_VAULTS_DIR")
    if not vaults_dir_str:
        logger.warning("OBSIDIAN_VAULTS_DIR not set — obsidian-sync not running")
        return

    vaults_dir = Path(vaults_dir_str)
    interval = int(os.environ.get("OBSIDIAN_SYNC_INTERVAL", "900"))
    dsn = os.environ.get("APP_DB_URL", os.environ["DATABASE_URL"])

    embed = EmbeddingClient(
        base_url=os.environ["VLLM_EMBED_URL"],
        api_key=os.environ["VLLM_API_KEY"],
        model=os.environ["EMBEDDING_MODEL"],
    )

    logger.info("obsidian-sync starting, interval=%ds, vaults=%s", interval, vaults_dir)
    while True:
        try:
            await run_once(dsn, embed, vaults_dir)
        except Exception:
            logger.exception("run_once failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(main())
