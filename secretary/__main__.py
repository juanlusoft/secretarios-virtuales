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
from secretary.agent import SecretaryAgent


async def main(employee_id_str: str) -> None:
    employee_id = UUID(employee_id_str)

    raw_conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    row = await raw_conn.fetchrow(
        "SELECT name, telegram_chat_id FROM employees WHERE id = $1", employee_id
    )
    await raw_conn.close()

    if not row:
        print(f"ERROR: employee {employee_id} not found")
        sys.exit(1)

    employee_name = row["name"]
    telegram_chat_id = row["telegram_chat_id"]

    raw_conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await raw_conn.execute(
        "SELECT set_config('app.current_employee_id', $1, true)", str(employee_id)
    )
    enc_token = await raw_conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='telegram_token'",
        employee_id,
    )
    await raw_conn.close()

    fernet_key = os.environ["FERNET_KEY"].encode()
    store = CredentialStore(fernet_key)
    bot_token = store.decrypt(enc_token)

    pool = DatabasePool(os.environ["DATABASE_URL"], employee_id)
    await pool.connect()

    agent = SecretaryAgent(
        employee_id=employee_id,
        employee_name=employee_name,
        allowed_chat_id=telegram_chat_id,
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
    )

    await agent.run(bot_token)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m secretary <employee_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
