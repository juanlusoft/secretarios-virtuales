from typing import cast
from uuid import UUID

import asyncpg

from .models import Conversation, Document, Task


class Repository:
    def __init__(self, conn: asyncpg.Connection, employee_id: UUID) -> None:
        self._conn = conn
        self._employee_id = employee_id

    async def save_conversation(
        self, role: str, content: str, source: str = "telegram"
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO conversations (employee_id, role, content, source)
            VALUES ($1, $2, $3, $4)
            """,
            self._employee_id, role, content, source,
        )

    async def get_recent_conversations(self, limit: int = 10) -> list[Conversation]:
        rows = await self._conn.fetch(
            """
            SELECT id, employee_id, role, content, source, created_at
            FROM conversations
            WHERE employee_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            self._employee_id, limit,
        )
        return [
            Conversation(
                id=r["id"],
                employee_id=r["employee_id"],
                role=r["role"],
                content=r["content"],
                source=r["source"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def save_document(
        self,
        filename: str,
        filepath: str,
        content_text: str,
        embedding: list[float],
        mime_type: str,
    ) -> UUID:
        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        row = await self._conn.fetchrow(
            """
            INSERT INTO documents
                (employee_id, filename, filepath, content_text, embedding, mime_type)
            VALUES ($1, $2, $3, $4, $5::vector, $6)
            RETURNING id
            """,
            self._employee_id, filename, filepath, content_text, vec_str, mime_type,
        )
        if row is None:
            raise RuntimeError("Failed to save document")
        return cast(UUID, row["id"])

    async def search_documents(
        self, embedding: list[float], limit: int = 5
    ) -> list[Document]:
        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        rows = await self._conn.fetch(
            """
            SELECT id, employee_id, filename, filepath, content_text, mime_type, created_at
            FROM documents
            WHERE employee_id = $1
            ORDER BY embedding <=> $2::vector
            LIMIT $3
            """,
            self._employee_id, vec_str, limit,
        )
        return [
            Document(
                id=r["id"],
                employee_id=r["employee_id"],
                filename=r["filename"],
                filepath=r["filepath"],
                content_text=r["content_text"],
                mime_type=r["mime_type"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def get_employee_by_chat_id(self, telegram_chat_id: str) -> UUID | None:
        row = await self._conn.fetchrow(
            """
            SELECT id FROM employees
            WHERE telegram_chat_id = $1 AND is_active = true
            """,
            telegram_chat_id,
        )
        return row["id"] if row else None

    async def save_credential(self, service_type: str, encrypted: str) -> None:
        await self._conn.execute(
            """
            INSERT INTO credentials (employee_id, service_type, encrypted)
            VALUES ($1, $2, $3)
            ON CONFLICT (employee_id, service_type) DO UPDATE SET encrypted = $3
            """,
            self._employee_id, service_type, encrypted,
        )

    async def get_credential(self, service_type: str) -> str | None:
        row = await self._conn.fetchrow(
            """
            SELECT encrypted FROM credentials
            WHERE employee_id = $1 AND service_type = $2
            """,
            self._employee_id, service_type,
        )
        return row["encrypted"] if row else None

    async def save_task(self, title: str, description: str | None = None) -> UUID:
        row = await self._conn.fetchrow(
            """
            INSERT INTO tasks (employee_id, title, description)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            self._employee_id, title, description,
        )
        if row is None:
            raise RuntimeError("Failed to save task")
        return cast(UUID, row["id"])

    async def get_pending_tasks(self) -> list[Task]:
        rows = await self._conn.fetch(
            """
            SELECT id, employee_id, title, description, status, created_at
            FROM tasks
            WHERE employee_id = $1 AND status = 'pending'
            ORDER BY created_at ASC
            """,
            self._employee_id,
        )
        return [
            Task(
                id=r["id"],
                employee_id=r["employee_id"],
                title=r["title"],
                description=r["description"],
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def get_credentials_by_prefix(self, prefix: str) -> list[tuple[str, str]]:
        """Returns (service_type, encrypted) for all credentials with the given prefix."""
        rows = await self._conn.fetch(
            """
            SELECT service_type, encrypted FROM credentials
            WHERE employee_id = $1 AND service_type LIKE $2
            """,
            self._employee_id,
            f"{prefix}%",
        )
        return [(r["service_type"], r["encrypted"]) for r in rows]

    async def get_vault_note_mtimes(self, source: str) -> dict[str, "datetime"]:
        from datetime import datetime
        rows = await self._conn.fetch(
            """
            SELECT vault_path, modified_at FROM vault_notes
            WHERE employee_id = $1 AND source = $2
            """,
            self._employee_id, source,
        )
        return {r["vault_path"]: r["modified_at"] for r in rows}

    async def upsert_vault_note(
        self,
        source: str,
        vault_path: str,
        title: str | None,
        tags: list[str],
        content_text: str,
        embedding: list[float],
        modified_at: "datetime",
    ) -> None:
        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        await self._conn.execute(
            """
            INSERT INTO vault_notes
                (employee_id, source, vault_path, title, tags, content_text, embedding, modified_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::vector, $8)
            ON CONFLICT (employee_id, source, vault_path)
            DO UPDATE SET
                title = EXCLUDED.title,
                tags = EXCLUDED.tags,
                content_text = EXCLUDED.content_text,
                embedding = EXCLUDED.embedding,
                modified_at = EXCLUDED.modified_at,
                indexed_at = NOW()
            WHERE vault_notes.modified_at < EXCLUDED.modified_at
            """,
            self._employee_id, source, vault_path, title, tags,
            content_text, vec_str, modified_at,
        )

    async def delete_vault_notes_not_in(
        self, source: str, vault_paths: list[str]
    ) -> None:
        await self._conn.execute(
            """
            DELETE FROM vault_notes
            WHERE employee_id = $1 AND source = $2
              AND NOT (vault_path = ANY($3))
            """,
            self._employee_id, source, vault_paths,
        )

    async def search_vault_notes(
        self, embedding: list[float], limit: int = 3
    ) -> list["VaultNote"]:
        from shared.db.models import VaultNote
        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        rows = await self._conn.fetch(
            """
            SELECT id, employee_id, source, vault_path, title, tags,
                   content_text, modified_at, indexed_at
            FROM vault_notes
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_str, limit,
        )
        return [
            VaultNote(
                id=r["id"],
                employee_id=r["employee_id"],
                source=r["source"],
                vault_path=r["vault_path"],
                title=r["title"],
                tags=list(r["tags"] or []),
                content_text=r["content_text"],
                modified_at=r["modified_at"],
                indexed_at=r["indexed_at"],
            )
            for r in rows
        ]
