import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from secretary.handlers.document import handle_document

pytestmark = pytest.mark.asyncio


async def test_saves_document_and_confirms(tmp_path):
    employee_id = uuid4()
    repo = AsyncMock()
    repo.save_document = AsyncMock(return_value=uuid4())
    embed = AsyncMock()
    embed.embed = AsyncMock(return_value=[0.1] * 1024)

    with patch("secretary.handlers.document._extract_text", return_value="texto del doc"):
        response = await handle_document(
            file_bytes=b"%PDF fake content",
            filename="contrato.pdf",
            mime_type="application/pdf",
            employee_id=employee_id,
            documents_dir=tmp_path,
            repo=repo,
            embed=embed,
        )

    assert "contrato.pdf" in response
    saved_path = tmp_path / str(employee_id) / "contrato.pdf"
    assert saved_path.exists()
    repo.save_document.assert_called_once()


async def test_creates_employee_directory(tmp_path):
    employee_id = uuid4()
    repo = AsyncMock()
    repo.save_document = AsyncMock(return_value=uuid4())
    embed = AsyncMock()
    embed.embed = AsyncMock(return_value=[0.1] * 1024)

    with patch("secretary.handlers.document._extract_text", return_value="texto"):
        await handle_document(
            file_bytes=b"content",
            filename="doc.txt",
            mime_type="text/plain",
            employee_id=employee_id,
            documents_dir=tmp_path,
            repo=repo,
            embed=embed,
        )

    assert (tmp_path / str(employee_id)).is_dir()
