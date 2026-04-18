from shared.email.client import EmailClient
from shared.llm.chat import ChatClient


async def handle_check_email(
    email_client: EmailClient,
    chat: ChatClient,
    employee_name: str,
    limit: int = 5,
) -> str:
    messages = await email_client.fetch_inbox(limit=limit)
    if not messages:
        return "No tienes emails nuevos."

    summary_input = "\n".join(
        f"De: {m.sender} | Asunto: {m.subject} | {m.body[:200]}"
        for m in messages
    )
    return await chat.complete(
        messages=[
            {
                "role": "user",
                "content": (
                    f"Resume estos emails de {employee_name} de forma clara:\n{summary_input}"
                ),
            }
        ]
    )


async def handle_send_email(
    email_client: EmailClient,
    to: str,
    subject: str,
    body: str,
) -> str:
    await email_client.send(to=to, subject=subject, body=body)
    return f"✅ Email enviado a {to}."
