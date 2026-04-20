import email as email_lib
from datetime import datetime
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

        use_tls = self._config.smtp_port == 465
        await aiosmtplib.send(
            message,
            hostname=self._config.smtp_host,
            port=self._config.smtp_port,
            username=self._config.username,
            password=self._config.password,
            use_tls=use_tls,
            start_tls=not use_tls,
        )

    async def fetch_inbox(self, limit: int = 10, since_days: int = 2) -> list[EmailMessage]:
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
            _, data = await imap.search("ALL")
            # aioimaplib may return ints, bytes or strings depending on version
            raw_uids = data[0] if data else b""
            if isinstance(raw_uids, (bytes, bytearray)):
                uid_list = raw_uids.decode().split()
            elif isinstance(raw_uids, int):
                uid_list = [str(raw_uids)] if raw_uids else []
            else:
                uid_list = str(raw_uids).split() if raw_uids else []
            uids = uid_list[-limit:]
            for uid in uids:
                _, msg_data = await imap.fetch(str(uid), "(RFC822)")
                # aioimaplib fetch returns list of lines; find the raw bytes
                raw = b""
                for item in (msg_data or []):
                    if isinstance(item, (bytes, bytearray)) and len(item) > 100:
                        raw = bytes(item)
                        break
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
