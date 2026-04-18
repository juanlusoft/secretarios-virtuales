import io
from pathlib import Path
from uuid import UUID

import pypdf

from shared.db.repository import Repository
from shared.llm.embeddings import EmbeddingClient


def _extract_text(file_bytes: bytes, mime_type: str) -> str:
    if mime_type == "text/plain":
        return file_bytes.decode(errors="replace")
    if mime_type == "application/pdf":
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            return " ".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    return ""


async def handle_document(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    employee_id: UUID,
    documents_dir: Path,
    repo: Repository,
    embed: EmbeddingClient,
) -> str:
    employee_dir = documents_dir / str(employee_id)
    employee_dir.mkdir(parents=True, exist_ok=True)

    # Strip any directory components to prevent path traversal
    safe_name = Path(filename).name

    # Reject empty or dot-only names
    if not safe_name or safe_name.lstrip(".") == "":
        raise ValueError("Invalid filename")

    # Resolve the full path and verify it stays inside employee_dir
    employee_root = employee_dir.resolve()
    filepath = (employee_root / safe_name).resolve()
    if employee_root not in filepath.parents:
        raise ValueError("Invalid filename")

    filepath.write_bytes(file_bytes)

    content_text = _extract_text(file_bytes, mime_type)
    embedding = await embed.embed(content_text or safe_name)

    await repo.save_document(
        filename=safe_name,
        filepath=str(filepath),
        content_text=content_text,
        embedding=embedding,
        mime_type=mime_type,
    )

    return f"✅ Documento guardado: {safe_name}"
