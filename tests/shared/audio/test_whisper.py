import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from shared.audio.whisper import WhisperClient

pytestmark = pytest.mark.asyncio


async def test_transcribe_returns_text():
    client = WhisperClient(base_url="http://localhost:9000")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"text": "hola mundo"}

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
        result = await client.transcribe(b"audio_bytes", filename="audio.ogg")

    assert result == "hola mundo"


async def test_transcribe_raises_on_error():
    client = WhisperClient(base_url="http://localhost:9000")
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
        with pytest.raises(RuntimeError, match="Whisper error"):
            await client.transcribe(b"audio_bytes", filename="audio.ogg")
