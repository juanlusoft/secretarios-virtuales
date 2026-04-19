from unittest.mock import AsyncMock, patch

import pytest

from shared.email.client import EmailClient
from shared.email.models import EmailConfig

pytestmark = pytest.mark.asyncio


@pytest.fixture
def config():
    return EmailConfig(
        imap_host="imap.example.com",
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="user@example.com",
        password="secret",
    )


async def test_send_email(config):
    client = EmailClient(config)
    with patch("aiosmtplib.send", new=AsyncMock()) as mock_send:
        await client.send(
            to="dest@example.com",
            subject="Test",
            body="Cuerpo del mensaje",
        )
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["hostname"] == "smtp.example.com"


async def test_fetch_inbox_returns_messages(config):
    client = EmailClient(config)
    mock_imap = AsyncMock()
    mock_imap.__aenter__ = AsyncMock(return_value=mock_imap)
    mock_imap.__aexit__ = AsyncMock(return_value=False)
    mock_imap.wait_hello_from_server = AsyncMock()
    mock_imap.login = AsyncMock(return_value=("OK", [b"LOGIN completed"]))
    mock_imap.select = AsyncMock(return_value=("OK", [b"5"]))
    mock_imap.search = AsyncMock(return_value=("OK", [b"1 2"]))
    _raw_email = b"From: a@b.com\r\nSubject: Asunto\r\n\r\n" + b"Cuerpo " * 20
    mock_imap.fetch = AsyncMock(
        return_value=(
            "OK",
            [b"1 (RFC822 {500}", _raw_email]
        )
    )
    mock_imap.logout = AsyncMock()

    with patch("aioimaplib.IMAP4_SSL", return_value=mock_imap):
        messages = await client.fetch_inbox(limit=5)

    assert isinstance(messages, list)
