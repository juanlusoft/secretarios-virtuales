"""Weekly summary job — runs Monday 8:00 via systemd timer."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
from dotenv import load_dotenv

from shared.crypto import CredentialStore
from shared.llm.chat import ChatClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "Eres un asistente que genera resúmenes semanales concisos en español. "
    "Dado el historial de conversaciones y tareas de una persona, genera un resumen "
    "de máximo 300 palabras: qué se trató esta semana, tareas pendientes importantes, "
    "y cualquier información destacable. Sé amigable y directo."
)


async def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


async def summarize_employee(
    conn: asyncpg.Connection,
    employee_id,
    employee_name: str,
    chat_id: str,
    store: CredentialStore,
    chat: ChatClient,
) -> None:
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    rows = await conn.fetch(
        """
        SELECT role, content, created_at FROM conversations
        WHERE employee_id = $1 AND created_at >= $2
        ORDER BY created_at ASC
        LIMIT 50
        """,
        employee_id, week_ago,
    )
    conv_lines = [f"[{r['created_at'].strftime('%d/%m %H:%M')}] {r['role']}: {r['content'][:200]}" for r in rows]

    task_rows = await conn.fetch(
        "SELECT title, description, status FROM tasks WHERE employee_id = $1 ORDER BY status, created_at",
        employee_id,
    )
    task_lines = [f"- [{t['status']}] {t['title']}" + (f": {t['description'][:100]}" if t['description'] else "") for t in task_rows]

    if not conv_lines and not task_lines:
        logger.info("No data for employee %s this week, skipping", employee_name)
        return

    user_content = "Conversaciones de esta semana:\n" + "\n".join(conv_lines or ["(ninguna)"])
    user_content += "\n\nTareas:\n" + "\n".join(task_lines or ["(ninguna)"])

    summary, _ = await chat.complete_with_tools(
        messages=[{"role": "user", "content": user_content}],
        system=_SUMMARY_SYSTEM,
        tools=[],
    )

    enc_token = await conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id = $1 AND service_type = 'telegram_token'",
        employee_id,
    )
    if not enc_token:
        logger.warning("No telegram token for employee %s", employee_name)
        return

    bot_token = store.decrypt(enc_token)
    text = f"📊 *Resumen semanal — {datetime.now().strftime('%d/%m/%Y')}*\n\n{summary}"
    await _send_telegram(bot_token, chat_id, text)
    logger.info("Weekly summary sent to %s", employee_name)


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    fernet_key = os.environ["FERNET_KEY"].encode()
    store = CredentialStore(fernet_key)
    chat = ChatClient(
        base_url=os.environ["VLLM_CHAT_URL"],
        api_key=os.environ["VLLM_API_KEY"],
        model=os.environ["CHAT_MODEL"],
    )

    conn = await asyncpg.connect(dsn)
    try:
        employees = await conn.fetch(
            "SELECT id, name, telegram_chat_id FROM employees "
            "WHERE is_active = true AND is_orchestrator = false AND telegram_chat_id IS NOT NULL"
        )
        for emp in employees:
            try:
                await summarize_employee(
                    conn=conn,
                    employee_id=emp["id"],
                    employee_name=emp["name"],
                    chat_id=emp["telegram_chat_id"],
                    store=store,
                    chat=chat,
                )
            except Exception:
                logger.exception("Error summarizing employee %s", emp["name"])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
