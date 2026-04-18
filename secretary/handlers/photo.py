import base64

from secretary.memory import MemoryManager
from shared.llm.chat import ChatClient


async def handle_photo(
    photo_bytes: bytes,
    caption: str | None,
    employee_name: str,
    chat: ChatClient,
    memory: MemoryManager,
) -> str:
    context = await memory.build_context(caption or "imagen")
    b64 = base64.b64encode(photo_bytes).decode()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                },
                {
                    "type": "text",
                    "text": caption or "Describe esta imagen.",
                },
            ],
        }
    ]

    system = (
        f"Eres el secretario virtual de {employee_name}. "
        f"Analiza la imagen y responde útilmente.\n\n{context}"
    )
    return await chat.complete(messages=messages, system=system)  # type: ignore[arg-type]
