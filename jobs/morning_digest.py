"""Morning email digest job — runs daily at 08:00 via systemd timer."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime

import asyncpg
import httpx
from dotenv import load_dotenv

from shared.crypto import CredentialStore
from shared.email.client import EmailClient
from shared.email.models import EmailConfig
from shared.llm.chat import ChatClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_DIGEST_SYSTEM = (
    "Eres un asistente que resume emails en español de forma concisa. "
    "Dado una lista de emails recientes, genera un resumen breve de máximo 250 palabras: "
    "cuántos emails hay, los temas principales, y cuáles parecen urgentes o importantes. "
    "Usa formato amigable con emojis donde corresponda."
)


async def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


async def digest_employee(
    conn: asyncpg.Connection,
    employee_id,
    employee_name: str,
    chat_id: str,
    store: CredentialStore,
    chat: ChatClient,
) -> None:
    email_imap_enc = await conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id = $1 AND service_type = 'email_imap'",
        employee_id,
    )
    email_smtp_enc = await conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id = $1 AND service_type = 'email_smtp'",
        employee_id,
    )
    if not email_imap_enc or not email_smtp_enc:
        logger.debug("No email configured for employee %s", employee_name)
        return

    imap = json.loads(store.decrypt(email_imap_enc))
    smtp = json.loads(store.decrypt(email_smtp_enc))
    email_client = EmailClient(
        EmailConfig(
            imap_host=imap["host"],
            imap_port=int(imap["port"]),
            smtp_host=smtp["host"],
            smtp_port=int(smtp["port"]),
            username=imap["username"],
            password=imap["password"],
        )
    )

    try:
        messages = await asyncio.wait_for(
            email_client.fetch_inbox(limit=20, since_days=1),
            timeout=30.0,
        )
    except Exception as e:
        logger.warning("Failed to fetch email for %s: %s", employee_name, e)
        return

    if not messages:
        logger.info("No new emails for %s", employee_name)
        return

    email_lines = []
    for m in messages:
        snippet = m.body[:200].replace("\n", " ") if m.body else ""
        email_lines.append(f"De: {m.sender}\nAsunto: {m.subject}\n{snippet}")

    user_content = f"Emails recibidos en las últimas 24h ({len(messages)} total):\n\n" + "\n\n---\n\n".join(email_lines)

    summary, _ = await chat.complete_with_tools(
        messages=[{"role": "user", "content": user_content}],
        system=_DIGEST_SYSTEM,
        tools=[],
    )

    enc_token = await conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id = $1 AND service_type = 'telegram_token'",
        employee_id,
    )
    if not enc_token:
        return

    bot_token = store.decrypt(enc_token)
    text = f"📬 *Digest matutino — {datetime.now().strftime('%d/%m/%Y')}*\n\n{summary}"
    await _send_telegram(bot_token, chat_id, text)
    logger.info("Morning digest sent to %s", employee_name)


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
                await digest_employee(
                    conn=conn,
                    employee_id=emp["id"],
                    employee_name=emp["name"],
                    chat_id=emp["telegram_chat_id"],
                    store=store,
                    chat=chat,
                )
            except Exception:
                logger.exception("Error digesting email for employee %s", emp["name"])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
