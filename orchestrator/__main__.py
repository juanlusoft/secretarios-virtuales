import asyncio
import logging
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from orchestrator.agent import OrchestratorAgent
from shared.audio.whisper import WhisperClient
from shared.db.pool import DatabasePool
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


async def main() -> None:
    bot_token = os.environ["ORCHESTRATOR_BOT_TOKEN"]
    _raw_ids = os.environ["ORCHESTRATOR_CHAT_ID"]
    _extra = os.environ.get("ORCHESTRATOR_EXTRA_CHAT_IDS", "")
    if _extra:
        _raw_ids = f"{_raw_ids},{_extra}"
    chat_id = _raw_ids  # may be comma-separated; first ID used as primary for DB
    dsn = os.environ.get("APP_DB_URL", os.environ["DATABASE_URL"])
    fernet_key = os.environ["FERNET_KEY"].encode()

    primary_chat_id = chat_id.split(",")[0].strip()

    conn = await asyncpg.connect(dsn)
    row = await conn.fetchrow(
        "SELECT id, name FROM employees WHERE is_orchestrator = true AND is_active = true"
    )
    if not row:
        employee_id = await conn.fetchval(
            """
            INSERT INTO employees (name, telegram_chat_id, is_orchestrator)
            VALUES ('Orquestador', $1, true)
            RETURNING id
            """,
            primary_chat_id,
        )
        employee_name = "Orquestador"
    else:
        employee_id = row["id"]
        employee_name = row["name"]
    await conn.close()

    pool = DatabasePool(dsn, employee_id)
    await pool.connect()

    agent = OrchestratorAgent(
        employee_id=employee_id,
        employee_name=employee_name,
        allowed_chat_id=chat_id,
        db_pool=pool,
        chat=ChatClient(
            base_url=os.environ["VLLM_CHAT_URL"],
            api_key=os.environ["VLLM_API_KEY"],
            model=os.environ["CHAT_MODEL"],
        ),
        vision=ChatClient(
            base_url=os.environ["VLLM_CHAT_URL"],
            api_key=os.environ["VLLM_API_KEY"],
            model=os.environ.get("VISION_MODEL", os.environ["CHAT_MODEL"]),
        ) if os.environ.get("VISION_MODEL") else None,
        embed=EmbeddingClient(
            base_url=os.environ["VLLM_EMBED_URL"],
            api_key=os.environ["VLLM_API_KEY"],
            model=os.environ["EMBEDDING_MODEL"],
        ),
        whisper=WhisperClient(base_url=os.environ["WHISPER_URL"]),
        documents_dir=Path(os.environ.get("DOCUMENTS_DIR", "./data/documents")),
        fernet_key=fernet_key,
        redis_url=os.environ["REDIS_URL"],
        dsn=dsn,
    )

    await agent.run(bot_token)


if __name__ == "__main__":
    asyncio.run(main())
