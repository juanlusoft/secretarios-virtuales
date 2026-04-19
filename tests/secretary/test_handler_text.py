import pytest
from unittest.mock import AsyncMock
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


async def test_handle_text_uses_profile_bot_name():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    profile = {
        "bot_name": "Clara",
        "gender": "feminine",
        "preferred_name": "Francis",
        "language": "español",
        "has_email": False,
        "has_calendar": False,
    }

    await handle_text(
        message="test",
        employee_name="Francis",
        memory=memory,
        chat=chat,
        profile=profile,
    )

    call_kwargs = chat.complete.call_args[1]
    assert "Clara" in call_kwargs["system"]
    assert "Francis" in call_kwargs["system"]


async def test_handle_text_email_line_present_when_has_email():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    profile = {
        "bot_name": "Marcos",
        "gender": "masculine",
        "preferred_name": "Alejandro",
        "language": "español",
        "has_email": True,
        "has_calendar": False,
    }

    await handle_text(
        message="test",
        employee_name="Alejandro",
        memory=memory,
        chat=chat,
        profile=profile,
    )

    call_kwargs = chat.complete.call_args[1]
    assert "email" in call_kwargs["system"].lower()


async def test_handle_text_no_profile_fallback():
    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="ok")

    await handle_text(
        message="hola",
        employee_name="Test",
        memory=memory,
        chat=chat,
        profile=None,
    )

    call_kwargs = chat.complete.call_args[1]
    assert "Test" in call_kwargs["system"]
