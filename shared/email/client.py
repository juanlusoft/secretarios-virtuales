import email as email_lib
from email.mime.text import MIMEText

import aioimaplib
import aiosmtplib

from .models import EmailConfig, EmailMessage


class EmailClient:
    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    async def send(self, to: str, subject: str, body: str) -> None:
        message = MIMEText(body, "plain", "utf-8")
        message["From"] = self._config.username
        message["To"] = to
        message["Subject"] = subject

        await aiosmtplib.send(
            message,
            hostname=self._config.smtp_host,
            port=self._config.smtp_port,
            username=self._config.username,
            password=self._config.password,
            start_tls=True,
        )

    async def fetch_inbox(self, limit: int = 10) -> list[EmailMessage]:
        messages: list[EmailMessage] = []
        imap = aioimaplib.IMAP4_SSL(
            host=self._config.imap_host, port=self._config.imap_port
        )
        await imap.wait_hello_from_server()
        try:
            status, data = await imap.login(self._config.username, self._config.password)
            if status != "OK":
                raise ValueError(f"IMAP login failed: {data}")
            await imap.select("INBOX")
            _, data = await imap.search("UNSEEN")
            uids = data[0].decode().split() if data[0] else []
            for uid in uids[-limit:]:
                _, msg_data = await imap.fetch(uid, "(RFC822)")
                raw = msg_data[0][1] if msg_data else b""
                parsed = email_lib.message_from_bytes(raw)
                body = ""
                if parsed.is_multipart():
                    for part in parsed.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if isinstance(payload, bytes):
                                body = payload.decode(errors="replace")
                            break
                else:
                    payload = parsed.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body = payload.decode(errors="replace")

                messages.append(
                    EmailMessage(
                        uid=uid,
                        sender=parsed.get("From", ""),
                        subject=parsed.get("Subject", ""),
                        body=body,
                        date=parsed.get("Date", ""),
                    )
                )
        finally:
            await imap.logout()
        return messages
