import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv

from secretary.agent import SecretaryAgent
from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient
from shared.tools import SSHStore, ToolExecutor

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


async def main(employee_id_str: str) -> None:
    employee_id = UUID(employee_id_str)
    app_dsn = os.environ.get("APP_DB_URL", os.environ["DATABASE_URL"])

    raw_conn = await asyncpg.connect(app_dsn)
    row = await raw_conn.fetchrow(
        "SELECT name, telegram_chat_id FROM employees WHERE id = $1",
        employee_id,
    )
    await raw_conn.close()

    if not row:
        print(f"ERROR: employee {employee_id} not found")
        sys.exit(1)

    employee_name = row["name"]
    telegram_chat_id = row["telegram_chat_id"]

    raw_conn = await asyncpg.connect(app_dsn)
    async with raw_conn.transaction():
        await raw_conn.execute(
            "SELECT set_config('app.current_employee_id', $1, true)",
            str(employee_id),
        )
        enc_token = await raw_conn.fetchval(
            (
                "SELECT encrypted FROM credentials "
                "WHERE employee_id=$1 AND service_type='telegram_token'"
            ),
            employee_id,
        )
    await raw_conn.close()

    fernet_key = os.environ["FERNET_KEY"].encode()
    store = CredentialStore(fernet_key)
    bot_token = store.decrypt(enc_token)

    raw_conn2 = await asyncpg.connect(app_dsn)
    async with raw_conn2.transaction():
        await raw_conn2.execute(
            "SELECT set_config('app.current_employee_id', $1, true)",
            str(employee_id),
        )
        tools_enc = await raw_conn2.fetchval(
            "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='tools_enabled'",
            employee_id,
        )
    await raw_conn2.close()
    tools_enabled = tools_enc is not None and store.decrypt(tools_enc) == "true"

    raw_conn3 = await asyncpg.connect(app_dsn)
    async with raw_conn3.transaction():
        await raw_conn3.execute(
            "SELECT set_config('app.current_employee_id', $1, true)",
            str(employee_id),
        )
        calendar_provider_enc = await raw_conn3.fetchval(
            "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='calendar_provider'",
            employee_id,
        )
    await raw_conn3.close()

    calendar_client = None
    if calendar_provider_enc is not None:
        from shared.calendar.client import make_calendar_client
        provider = store.decrypt(calendar_provider_enc)
        raw_conn4 = await asyncpg.connect(app_dsn)
        async with raw_conn4.transaction():
            await raw_conn4.execute(
                "SELECT set_config('app.current_employee_id', $1, true)",
                str(employee_id),
            )
            if provider == "google":
                token_enc = await raw_conn4.fetchval(
                    "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='calendar_google_token'",
                    employee_id,
                )
                creds = json.loads(store.decrypt(token_enc))
            else:
                caldav_enc = await raw_conn4.fetchval(
                    "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='calendar_caldav'",
                    employee_id,
                )
                creds = json.loads(store.decrypt(caldav_enc))
        await raw_conn4.close()
        try:
            calendar_client = make_calendar_client(provider, creds)
        except Exception as e:
            logging.warning("Failed to create calendar client: %s", e)

    pool = DatabasePool(app_dsn, employee_id)
    await pool.connect()

    executor: ToolExecutor | None = None
    if tools_enabled:
        ssh_store = SSHStore(pool=pool, employee_id=employee_id, store=store)
        executor = ToolExecutor(ssh_store=ssh_store, calendar_client=calendar_client)

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
        executor=executor,
        calendar_client=calendar_client,
        google_client_id=os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", ""),
        google_client_secret=os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", ""),
    )

    await agent.run(bot_token)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m secretary <employee_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
