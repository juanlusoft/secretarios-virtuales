from secretary.handlers.text import handle_text
from secretary.memory import MemoryManager
from shared.audio.whisper import WhisperClient
from shared.llm.chat import ChatClient


async def handle_audio(
    audio_bytes: bytes,
    filename: str,
    employee_name: str,
    whisper: WhisperClient,
    memory: MemoryManager,
    chat: ChatClient,
    profile: dict | None = None,
) -> tuple[str, str]:
    transcription = await whisper.transcribe(audio_bytes, filename=filename)
    response = await handle_text(
        message=transcription,
        employee_name=employee_name,
        memory=memory,
        chat=chat,
        profile=profile,
    )
    return transcription, response
