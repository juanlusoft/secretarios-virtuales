import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient
from orchestrator.agent import OrchestratorAgent


async def main() -> None:
    bot_token = os.environ["ORCHESTRATOR_BOT_TOKEN"]
    chat_id = os.environ["ORCHESTRATOR_CHAT_ID"]
    dsn = os.environ["DATABASE_URL"]
    fernet_key = os.environ["FERNET_KEY"].encode()

    # Find or create orchestrator employee record
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
            chat_id,
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
