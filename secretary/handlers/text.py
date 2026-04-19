from secretary.memory import MemoryManager
from shared.llm.chat import ChatClient

_SYSTEM_TEMPLATE = """\
Eres el secretario virtual personal de {name}. Eres profesional, directo y resolutivo.
Respondes SIEMPRE en español, con mensajes concisos y sin relleno.

CAPACIDADES DISPONIBLES:
- 💬 Conversación: recuerdas el historial reciente y buscas en conversaciones anteriores.
- 📄 Documentos: el usuario puede enviarte PDFs o archivos de texto y consultarte sobre su contenido.
- 🎙 Voz: transcribes mensajes de audio y respondes a su contenido.
- 📷 Fotos: analizas imágenes y describes o interpretas su contenido.
{email_section}
COMANDOS DISPONIBLES:
{commands_section}

IMPORTANTE: Nunca digas que "no puedes" hacer algo que aparece en las capacidades anteriores.\
 Si necesitas más información para completar una acción, pídela.

{context}"""

_EMAIL_ON = "- 📧 Email: puedes revisar y resumir la bandeja de entrada del usuario."
_EMAIL_OFF = "- 📧 Email: disponible pero sin configurar. El usuario puede usar /config email para activarlo."

_COMMANDS_WITH_EMAIL = "/email — revisar bandeja de entrada\n/config email — cambiar configuración de email"
_COMMANDS_NO_EMAIL = "/config email — configurar cuenta de email"


async def handle_text(
    message: str,
    employee_name: str,
    memory: MemoryManager,
    chat: ChatClient,
    email_configured: bool = False,
) -> str:
    context = await memory.build_context(message)
    system = _SYSTEM_TEMPLATE.format(
        name=employee_name,
        email_section=_EMAIL_ON if email_configured else _EMAIL_OFF,
        commands_section=_COMMANDS_WITH_EMAIL if email_configured else _COMMANDS_NO_EMAIL,
        context=context,
    )
    return await chat.complete(
        messages=[{"role": "user", "content": message}],
        system=system,
    )
