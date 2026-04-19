from secretary.memory import MemoryManager
from shared.llm.chat import ChatClient

SYSTEM_TEMPLATE = """Eres {bot_name}, secretari{gender_suffix} virtual de {preferred_name}.

PERSONALIDAD:
- Trato formal pero cercano, con un estilo propio que vas desarrollando.
- {gender_instructions}
- Responde siempre en {language}, salvo que {preferred_name} te escriba en otro idioma.

CAPACIDADES — usa estas sin dudar cuando te las pidan:
- Leer y resumir documentos (PDF, DOCX, TXT)
- Transcribir y responder mensajes de voz
- Analizar y describir imágenes y fotos
- Gestionar tareas y recordatorios{email_line}{calendar_line}

CONTEXTO DE CONVERSACIÓN Y DOCUMENTOS:
{context}

REGLA IMPORTANTE: Nunca rechaces una tarea que esté dentro de las capacidades listadas. Si no puedes hacer algo concreto, explica exactamente el motivo."""

FALLBACK_TEMPLATE = """Eres el secretario virtual de {name}.
Eres profesional, conciso y útil.
Respondes siempre en el idioma en que te escribe {name}.

{context}"""


async def handle_text(
    message: str,
    employee_name: str,
    memory: MemoryManager,
    chat: ChatClient,
    profile: dict | None = None,
) -> str:
    context = await memory.build_context(message)

    if profile:
        gender = profile.get("gender", "masculine")
        gender_suffix = "a" if gender == "feminine" else "o"
        gender_instructions = (
            "Utiliza forma femenina al referirte a ti misma."
            if gender == "feminine"
            else "Utiliza forma masculina al referirte a ti mismo."
        )
        preferred_name = profile.get("preferred_name", employee_name)
        email_line = (
            f"\n- Leer y gestionar el email de {preferred_name} (configurado)"
            if profile.get("has_email")
            else ""
        )
        calendar_line = (
            f"\n- Acceder al calendario de {preferred_name} (configurado)"
            if profile.get("has_calendar")
            else ""
        )
        system = SYSTEM_TEMPLATE.format(
            bot_name=profile.get("bot_name", "tu secretario"),
            gender_suffix=gender_suffix,
            preferred_name=preferred_name,
            gender_instructions=gender_instructions,
            language=profile.get("language", "español"),
            email_line=email_line,
            calendar_line=calendar_line,
            context=context,
        )
    else:
        system = FALLBACK_TEMPLATE.format(name=employee_name, context=context)

    return await chat.complete(
        messages=[{"role": "user", "content": message}],
        system=system,
    )
