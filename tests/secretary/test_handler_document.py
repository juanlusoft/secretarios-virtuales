from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

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


@pytest.mark.parametrize("bad_filename", ["", ".", ".."])
async def test_rejects_path_traversal_filenames(tmp_path, bad_filename):
    employee_id = uuid4()
    repo = AsyncMock()
    embed = AsyncMock()

    with pytest.raises(ValueError, match="Invalid filename"):
        await handle_document(
            file_bytes=b"malicious content",
            filename=bad_filename,
            mime_type="text/plain",
            employee_id=employee_id,
            documents_dir=tmp_path,
            repo=repo,
            embed=embed,
        )


async def test_rejects_empty_filename(tmp_path):
    employee_id = uuid4()
    repo = AsyncMock()
    embed = AsyncMock()

    with pytest.raises(ValueError, match="Invalid filename"):
        await handle_document(
            file_bytes=b"content",
            filename="",
            mime_type="text/plain",
            employee_id=employee_id,
            documents_dir=tmp_path,
            repo=repo,
            embed=embed,
        )


@pytest.mark.parametrize(
    "input_name, expected_name",
    [
        ("../../etc/passwd", "passwd"),
        ("../secret.txt", "secret.txt"),
        ("/etc/passwd", "passwd"),
    ],
)
async def test_strips_directory_prefix_and_saves_safely(
    tmp_path, input_name, expected_name
):
    """A traversal filename like ../../evil.txt has its directory stripped;
    the resulting bare name "evil.txt" is saved inside employee_dir normally."""
    employee_id = uuid4()
    repo = AsyncMock()
    repo.save_document = AsyncMock(return_value=uuid4())
    embed = AsyncMock()
    embed.embed = AsyncMock(return_value=[0.1] * 1024)

    with patch("secretary.handlers.document._extract_text", return_value=""):
        response = await handle_document(
            file_bytes=b"safe content",
            filename=input_name,
            mime_type="text/plain",
            employee_id=employee_id,
            documents_dir=tmp_path,
            repo=repo,
            embed=embed,
        )

    saved_path = tmp_path / str(employee_id) / expected_name
    assert saved_path.exists()
    assert expected_name in response
