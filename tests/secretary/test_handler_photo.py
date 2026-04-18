from unittest.mock import AsyncMock

import pytest

from secretary.handlers.photo import handle_photo

pytestmark = pytest.mark.asyncio


async def test_describes_photo_and_responds():
    chat = AsyncMock()
    chat.complete = AsyncMock(return_value="Veo una factura de 150€")

    memory = AsyncMock()
    memory.build_context = AsyncMock(return_value="")

    result = await handle_photo(
        photo_bytes=b"fake_image",
        caption="¿qué dice esta factura?",
        employee_name="Laura",
        chat=chat,
        memory=memory,
    )

    assert "Veo una factura" in result
