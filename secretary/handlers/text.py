from secretary.memory import MemoryManager
from shared.llm.chat import ChatClient

_SYSTEM_TEMPLATE = """\
Eres {bot_name}, {role_word} virtual personal de {preferred_name}. \
Eres profesional, directo y resolutivo.
{language_instruction}
CRÍTICO: Responde ÚNICAMENTE en el idioma indicado. NUNCA uses chino ni ningún otro idioma. \
NUNCA muestres tu razonamiento interno, cadenas de pensamiento ni metacomentarios. \
Responde directamente al usuario con la respuesta final.

CAPACIDADES DISPONIBLES:
- 💬 Conversación: recuerdas el historial reciente y buscas en conversaciones anteriores.
- 📄 Documentos: el usuario puede enviarte PDFs o archivos de texto y consultarte sobre su contenido.
- 🎙 Voz: transcribes mensajes de audio y respondes a su contenido.
- 📷 Fotos: analizas imágenes y describes o interpretas su contenido.
{email_section}
COMANDOS DISPONIBLES:
{commands_section}

IMPORTANTE: Eres un asistente personal de productividad, NO un sistema de seguridad ni un agente con \
acceso al sistema operativo. Puedes y debes ayudar con cualquier tarea intelectual: redactar, calcular, \
programar, analizar, traducir, resumir, crear código, revisar código, etc. \
Nunca rechaces una solicitud por creer que "modificas el sistema" — solo generas texto. \
Si necesitas más información para completar una acción, pídela.

{context}"""

_EMAIL_ON = "- 📧 Email: puedes revisar y resumir la bandeja de entrada del usuario."
_EMAIL_OFF = "- 📧 Email: disponible pero sin configurar. El usuario puede usar /config_email para activarlo."

_COMMANDS_WITH_EMAIL = "/email — revisar bandeja de entrada\n/config_email — cambiar configuración de email"
_COMMANDS_NO_EMAIL = "/config_email — configurar cuenta de email"


def _language_instruction(language: str) -> str:
    lang = language.lower().strip()
    if lang in ("español", "spanish", "es", "castellano"):
        return "Respondes SIEMPRE en español, con mensajes concisos y sin relleno."
    if lang in ("english", "inglés", "ingles", "en"):
        return "You ALWAYS respond in English, with concise messages and no filler."
    if lang in ("français", "francés", "frances", "fr"):
        return "Tu réponds TOUJOURS en français, avec des messages concis et sans remplissage."
    if lang in ("português", "portugués", "pt"):
        return "Você SEMPRE responde em português, com mensagens concisas e sem rodeios."
    return f"Respondes SIEMPRE en {language}, con mensajes concisos y sin relleno."


async def handle_text(
    message: str,
    employee_name: str,
    memory: MemoryManager,
    chat: ChatClient,
    email_configured: bool = False,
    profile: dict | None = None,
) -> str:
    bot_name = (profile or {}).get("bot_name") or employee_name
    preferred_name = (profile or {}).get("preferred_name") or employee_name
    language = (profile or {}).get("language") or "español"
    gender = (profile or {}).get("gender", "masculine")
    role_word = "la secretaria" if gender == "feminine" else "el secretario"

    context = await memory.build_context(message)
    system = _SYSTEM_TEMPLATE.format(
        bot_name=bot_name,
        role_word=role_word,
        preferred_name=preferred_name,
        language_instruction=_language_instruction(language),
        email_section=_EMAIL_ON if email_configured else _EMAIL_OFF,
        commands_section=_COMMANDS_WITH_EMAIL if email_configured else _COMMANDS_NO_EMAIL,
        context=context,
    )
    return await chat.complete(
        messages=[{"role": "user", "content": message}],
        system=system,
    )
