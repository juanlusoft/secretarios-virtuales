from unittest.mock import AsyncMock

import pytest

from secretary.handlers.text import handle_text

pytestmark = pytest.mark.asyncio


async def test_handle_text_returns_llm_response():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="contexto de prueba")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="respuesta del LLM")

    result = await handle_text(
        message="hola",
        employee_name="Alejandro",
        memory=memory,
        chat=chat,
    )

    assert result == "respuesta del LLM"
    memory.build_context.assert_called_once_with("hola")
    chat.complete.assert_called_once()


async def test_handle_text_includes_name_in_system():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    await handle_text(
        message="test",
        employee_name="María",
        memory=memory,
        chat=chat,
    )

    call_kwargs = chat.complete.call_args[1]
    assert "María" in call_kwargs["system"]


async def test_system_prompt_shows_email_configured():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    await handle_text(
        message="test",
        employee_name="Juan",
        memory=memory,
        chat=chat,
        email_configured=True,
    )

    system = chat.complete.call_args[1]["system"]
    assert "/email" in system
    assert "bandeja" in system


async def test_system_prompt_shows_email_not_configured():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    await handle_text(
        message="test",
        employee_name="Juan",
        memory=memory,
        chat=chat,
        email_configured=False,
    )

    system = chat.complete.call_args[1]["system"]
    assert "/config_email" in system
    assert "sin configurar" in system
