from unittest.mock import AsyncMock

import pytest

from secretary.handlers.audio import handle_audio

pytestmark = pytest.mark.asyncio


async def test_handle_audio_transcribes_then_responds():
    whisper = AsyncMock()
    whisper.transcribe = AsyncMock(return_value="texto transcrito del audio")

    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")

    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="entendido")

    transcription, response = await handle_audio(
        audio_bytes=b"fake_audio",
        filename="audio.ogg",
        employee_name="Pedro",
        whisper=whisper,
        memory=memory,
        chat=chat,
    )

    assert transcription == "texto transcrito del audio"
    assert response == "entendido"
    whisper.transcribe.assert_called_once_with(b"fake_audio", filename="audio.ogg")
