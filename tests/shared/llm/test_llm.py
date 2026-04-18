import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient

pytestmark = pytest.mark.asyncio


async def test_chat_returns_content():
    client = ChatClient(
        base_url="http://localhost:8000/v1",
        api_key="sk-test",
        model="test-model",
    )
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "respuesta de prueba"

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ):
        result = await client.complete(
            messages=[{"role": "user", "content": "hola"}],
            system="Eres un asistente.",
        )

    assert result == "respuesta de prueba"


async def test_chat_without_system():
    client = ChatClient(
        base_url="http://localhost:8000/v1",
        api_key="sk-test",
        model="test-model",
    )
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"

    with patch.object(
        client._client.chat.completions, "create", new=AsyncMock(return_value=mock_response)
    ) as mock_create:
        await client.complete(messages=[{"role": "user", "content": "test"}])
        call_args = mock_create.call_args[1]["messages"]
        assert call_args[0]["role"] == "user"


async def test_embed_returns_vector():
    client = EmbeddingClient(
        base_url="http://localhost:8001/v1",
        api_key="sk-test",
        model="bge-m3",
    )
    mock_response = MagicMock()
    mock_response.data[0].embedding = [0.1, 0.2, 0.3]

    with patch.object(
        client._client.embeddings, "create", new=AsyncMock(return_value=mock_response)
    ):
        result = await client.embed("texto de prueba")

    assert result == [0.1, 0.2, 0.3]
