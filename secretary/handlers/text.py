from secretary.memory import MemoryManager
from shared.llm.chat import ChatClient

SYSTEM_TEMPLATE = """Eres el secretario virtual de {name}.
Eres profesional, conciso y útil.
Respondes siempre en el idioma en que te escribe {name}.

{context}"""


async def handle_text(
    message: str,
    employee_name: str,
    memory: MemoryManager,
    chat: ChatClient,
) -> str:
    context = await memory.build_context(message)
    system = SYSTEM_TEMPLATE.format(name=employee_name, context=context)
    return await chat.complete(
        messages=[{"role": "user", "content": message}],
        system=system,
    )
