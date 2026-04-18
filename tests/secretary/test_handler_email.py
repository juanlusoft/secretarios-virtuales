from unittest.mock import AsyncMock

import pytest

from secretary.handlers.email import handle_check_email, handle_send_email
from shared.email.models import EmailMessage

pytestmark = pytest.mark.asyncio


async def test_check_email_returns_summary():
    email_client = AsyncMock()
    email_client.fetch_inbox = AsyncMock(return_value=[
        EmailMessage(uid="1", sender="jefe@emp.com", subject="Reunión",
                     body="Mañana a las 10", date="Mon, 1 Jan 2026"),
    ])
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="Tienes 1 email de jefe@emp.com sobre Reunión")

    result = await handle_check_email(
        email_client=email_client,
        chat=chat,
        employee_name="Ana",
    )

    assert "email" in result.lower() or "Tienes" in result


async def test_send_email_confirms():
    email_client = AsyncMock()
    email_client.send = AsyncMock()

    result = await handle_send_email(
        email_client=email_client,
        to="dest@emp.com",
        subject="Hola",
        body="Mensaje de prueba",
    )

    email_client.send.assert_called_once_with(
        to="dest@emp.com", subject="Hola", body="Mensaje de prueba"
    )
    assert "enviado" in result.lower()
