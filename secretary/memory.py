import asyncio

from shared.db.repository import Repository
from shared.llm.embeddings import EmbeddingClient


class MemoryManager:
    def __init__(self, repo: Repository, embed_client: EmbeddingClient) -> None:
        self._repo = repo
        self._embed = embed_client

    async def build_context(self, query: str, conv_limit: int = 8, doc_limit: int = 3) -> str:
        embedding = await self._embed.embed(query)
        conversations, documents, vault_notes = await asyncio.gather(
            self._repo.get_recent_conversations(limit=conv_limit),
            self._repo.search_documents(embedding=embedding, limit=doc_limit),
            self._repo.search_vault_notes(embedding=embedding, limit=doc_limit),
        )

        parts: list[str] = []

        if conversations:
            history = "\n".join(
                f"{c.role.upper()}: {c.content}"
                for c in reversed(conversations)
            )
            parts.append(f"=== Conversación reciente ===\n{history}")

        if documents:
            docs_text = "\n---\n".join(
                f"[{d.filename}]: {d.content_text or ''}"
                for d in documents
            )
            parts.append(f"=== Documentos relevantes ===\n{docs_text}")

        if vault_notes:
            notes_text = "\n---\n".join(
                f"[{'Base de conocimiento' if n.source == 'shared' else 'Notas personales'}] "
                f"{n.title or n.vault_path}\n{n.content_text or ''}"
                for n in vault_notes
            )
            parts.append(f"=== Notas ===\n{notes_text}")

        return "\n\n".join(parts)

    async def save_turn(self, user_msg: str, assistant_msg: str) -> None:
        await self._repo.save_conversation("user", user_msg)
        await self._repo.save_conversation("assistant", assistant_msg)
