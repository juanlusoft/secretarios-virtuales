# Obsidian RAG Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sincronizar vaults de Obsidian con pgvector para que los secretarios consulten notas relevantes automáticamente al responder.

**Architecture:** Un servicio `obsidian-sync` (systemd) escanea vaults cada 15 min, parsea `.md`, genera embeddings y hace upsert en `vault_notes`. El `MemoryManager` busca en paralelo en `documents` y `vault_notes` al construir el contexto del LLM.

**Tech Stack:** Python 3.11+, python-frontmatter, asyncpg, pgvector (vector 1024 dims), systemd, pytest-asyncio.

---

## File Map

| Fichero | Acción | Responsabilidad |
|---------|--------|----------------|
| `infrastructure/db/migrations/002_vault_notes.sql` | Crear | SQL de migración standalone |
| `infrastructure/db/init.sql` | Modificar | Añadir vault_notes + RLS al schema de inicio |
| `shared/db/models.py` | Modificar | Añadir dataclass `VaultNote` |
| `pyproject.toml` | Modificar | Añadir `python-frontmatter` |
| `shared/vault/__init__.py` | Crear | Exports del paquete |
| `shared/vault/parser.py` | Crear | `NoteData` + `parse_note(path) -> NoteData` |
| `shared/vault/syncer.py` | Crear | `SyncResult` + `VaultSyncer` |
| `shared/vault/cron.py` | Crear | Entry point del servicio systemd |
| `shared/db/repository.py` | Modificar | Añadir métodos vault_notes |
| `secretary/memory.py` | Modificar | `build_context` incluye vault_notes |
| `infrastructure/systemd/obsidian-sync.service` | Crear | Servicio systemd |
| `tests/vault/__init__.py` | Crear | Vacío |
| `tests/vault/test_parser.py` | Crear | Tests de parse_note |
| `tests/vault/test_syncer.py` | Crear | Tests de VaultSyncer (mocks) |
| `tests/secretary/test_memory.py` | Crear | Tests de build_context con vault_notes |

---

## Task 1: DB schema + VaultNote model + dependencia

**Files:**
- Create: `infrastructure/db/migrations/002_vault_notes.sql`
- Modify: `infrastructure/db/init.sql`
- Modify: `shared/db/models.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Crear `infrastructure/db/migrations/002_vault_notes.sql`**

```sql
CREATE TABLE IF NOT EXISTS vault_notes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    source       TEXT NOT NULL CHECK (source IN ('shared', 'personal')),
    vault_path   TEXT NOT NULL,
    title        TEXT,
    tags         TEXT[],
    content_text TEXT,
    embedding    vector(1024),
    modified_at  TIMESTAMPTZ NOT NULL,
    indexed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS vault_notes_employee_source_path
    ON vault_notes(employee_id, source, vault_path);
CREATE INDEX IF NOT EXISTS vault_notes_employee_id
    ON vault_notes(employee_id);

ALTER TABLE vault_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE vault_notes FORCE ROW LEVEL SECURITY;

CREATE POLICY vault_notes_isolation ON vault_notes
    USING (
        source = 'shared'
        OR employee_id = current_setting('app.current_employee_id', true)::uuid
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON vault_notes TO svapp;
```

- [ ] **Step 2: Añadir vault_notes al final de `infrastructure/db/init.sql`**

Añadir al final del fichero (después del bloque de FORCE ROW LEVEL SECURITY):

```sql
CREATE TABLE vault_notes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    source       TEXT NOT NULL CHECK (source IN ('shared', 'personal')),
    vault_path   TEXT NOT NULL,
    title        TEXT,
    tags         TEXT[],
    content_text TEXT,
    embedding    vector(1024),
    modified_at  TIMESTAMPTZ NOT NULL,
    indexed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX ON vault_notes(employee_id, source, vault_path);
CREATE INDEX ON vault_notes(employee_id);

ALTER TABLE vault_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE vault_notes FORCE ROW LEVEL SECURITY;

CREATE POLICY vault_notes_isolation ON vault_notes
    USING (
        source = 'shared'
        OR employee_id = current_setting('app.current_employee_id', true)::uuid
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON vault_notes TO svapp;
```

- [ ] **Step 3: Añadir `VaultNote` a `shared/db/models.py`**

Añadir al final del fichero:

```python
@dataclass
class VaultNote:
    id: UUID
    employee_id: UUID
    source: str
    vault_path: str
    title: str | None
    tags: list[str]
    content_text: str | None
    modified_at: datetime
    indexed_at: datetime
```

- [ ] **Step 4: Añadir `python-frontmatter` a `pyproject.toml`**

En la sección `dependencies`, añadir después de `"asyncssh>=2.14,<3"`:
```toml
    "python-frontmatter>=1.1,<2",
```

- [ ] **Step 5: Instalar dependencias**

```bash
cd ~/secretarios-virtuales
uv pip install -e ".[dev]"
```

Expected: `python-frontmatter` instalado sin errores.

- [ ] **Step 6: Commit**

```bash
git add infrastructure/db/migrations/002_vault_notes.sql infrastructure/db/init.sql shared/db/models.py pyproject.toml
git commit -m "feat: add vault_notes table schema and VaultNote model"
```

---

## Task 2: `shared/vault/parser.py` — parseo de notas Obsidian

**Files:**
- Create: `tests/vault/__init__.py`
- Create: `tests/vault/test_parser.py`
- Create: `shared/vault/parser.py`

- [ ] **Step 1: Crear `tests/vault/__init__.py`** (vacío)

- [ ] **Step 2: Crear `tests/vault/test_parser.py`**

```python
from pathlib import Path
from datetime import datetime, timezone

import pytest

from shared.vault.parser import NoteData, parse_note


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_plain_note(tmp_path):
    p = _write(tmp_path, "hola.md", "# Hola\n\nEsto es una nota.")
    note = parse_note(p, vault_root=tmp_path)
    assert note.vault_path == "hola.md"
    assert note.title == "hola"
    assert note.content_text == "# Hola\n\nEsto es una nota."
    assert note.tags == []
    assert isinstance(note.modified_at, datetime)


def test_parse_frontmatter(tmp_path):
    content = "---\ntitle: Mi nota\ntags: [trabajo, urgente]\n---\n\nContenido aquí."
    p = _write(tmp_path, "nota.md", content)
    note = parse_note(p, vault_root=tmp_path)
    assert note.title == "Mi nota"
    assert note.tags == ["trabajo", "urgente"]
    assert note.content_text == "Contenido aquí."


def test_cleans_wikilinks(tmp_path):
    p = _write(tmp_path, "wikilinks.md", "Habla con [[Pedro Sánchez]] sobre [[reunión|la reunión]].")
    note = parse_note(p, vault_root=tmp_path)
    assert "[[" not in note.content_text
    assert "Pedro Sánchez" in note.content_text
    assert "la reunión" in note.content_text


def test_cleans_hashtags(tmp_path):
    p = _write(tmp_path, "tags.md", "Este es un texto con #trabajo y #urgente como etiquetas.")
    note = parse_note(p, vault_root=tmp_path)
    assert "#trabajo" not in note.content_text
    assert "#urgente" not in note.content_text
    assert "Este es un texto con" in note.content_text


def test_subdirectory_vault_path(tmp_path):
    subdir = tmp_path / "proyectos"
    subdir.mkdir()
    p = _write(subdir, "web.md", "Proyecto web.")
    note = parse_note(p, vault_root=tmp_path)
    assert note.vault_path == "proyectos/web.md"


def test_frontmatter_tags_string(tmp_path):
    content = "---\ntitle: Test\ntags: trabajo, urgente\n---\nContenido."
    p = _write(tmp_path, "t.md", content)
    note = parse_note(p, vault_root=tmp_path)
    assert "trabajo" in note.tags
    assert "urgente" in note.tags
```

- [ ] **Step 3: Ejecutar tests — verificar que fallan**

```bash
python -m pytest tests/vault/test_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'shared.vault'`

- [ ] **Step 4: Crear `shared/vault/parser.py`**

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

_WIKILINK_ALIAS_RE = re.compile(r"\[\[([^\|\]]+)\|([^\]]+)\]\]")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_HASHTAG_RE = re.compile(r"\B#\w+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


@dataclass
class NoteData:
    vault_path: str
    title: str
    tags: list[str] = field(default_factory=list)
    content_text: str = ""
    modified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def parse_note(path: Path, vault_root: Path) -> NoteData:
    vault_path = str(path.relative_to(vault_root))
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    post = frontmatter.loads(path.read_text(encoding="utf-8", errors="replace"))

    title: str = post.get("title") or path.stem

    raw_tags = post.get("tags", [])
    if isinstance(raw_tags, str):
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    elif isinstance(raw_tags, list):
        tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    else:
        tags = []

    body: str = post.content
    body = _WIKILINK_ALIAS_RE.sub(r"\2", body)
    body = _WIKILINK_RE.sub(r"\1", body)
    body = _HASHTAG_RE.sub("", body)
    body = _BLANK_LINES_RE.sub("\n\n", body).strip()

    return NoteData(
        vault_path=vault_path,
        title=title,
        tags=tags,
        content_text=body,
        modified_at=mtime,
    )
```

- [ ] **Step 5: Ejecutar tests — verificar que pasan**

```bash
python -m pytest tests/vault/test_parser.py -v
```

Expected: 6 PASSED

- [ ] **Step 6: Commit**

```bash
git add shared/vault/parser.py tests/vault/__init__.py tests/vault/test_parser.py
git commit -m "feat: add Obsidian note parser with frontmatter and wikilink cleaning"
```

---

## Task 3: `shared/db/repository.py` — métodos vault_notes

**Files:**
- Modify: `shared/db/repository.py`
- Create: `tests/shared/db/test_vault_repository.py`

Los tres métodos necesarios:
- `get_vault_note_mtimes(source) -> dict[str, datetime]` — carga todos los `{vault_path: modified_at}` del employee+source en una sola query
- `upsert_vault_note(source, vault_path, title, tags, content_text, embedding, modified_at)` — insert o update
- `delete_vault_notes_not_in(source, vault_paths)` — elimina notas borradas
- `search_vault_notes(embedding, limit=3) -> list[VaultNote]` — búsqueda por similaridad

- [ ] **Step 1: Crear `tests/shared/db/test_vault_repository.py`**

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from shared.db.models import VaultNote
from shared.db.repository import Repository

EMPLOYEE_ID = uuid4()
NOW = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)


def _make_repo(conn):
    return Repository(conn, EMPLOYEE_ID)


async def test_get_vault_note_mtimes_empty():
    conn = AsyncMock()
    conn.fetch.return_value = []
    repo = _make_repo(conn)
    result = await repo.get_vault_note_mtimes("shared")
    assert result == {}
    conn.fetch.assert_called_once()


async def test_get_vault_note_mtimes_returns_dict():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {"vault_path": "a.md", "modified_at": NOW},
        {"vault_path": "b.md", "modified_at": NOW},
    ]
    repo = _make_repo(conn)
    result = await repo.get_vault_note_mtimes("personal")
    assert result == {"a.md": NOW, "b.md": NOW}


async def test_upsert_vault_note_calls_execute():
    conn = AsyncMock()
    repo = _make_repo(conn)
    await repo.upsert_vault_note(
        source="shared",
        vault_path="nota.md",
        title="Mi nota",
        tags=["tag1"],
        content_text="Contenido",
        embedding=[0.1] * 1024,
        modified_at=NOW,
    )
    conn.execute.assert_called_once()
    sql, *args = conn.execute.call_args[0]
    assert "INSERT INTO vault_notes" in sql
    assert "ON CONFLICT" in sql


async def test_delete_vault_notes_not_in():
    conn = AsyncMock()
    repo = _make_repo(conn)
    await repo.delete_vault_notes_not_in("shared", ["a.md", "b.md"])
    conn.execute.assert_called_once()
    sql, *args = conn.execute.call_args[0]
    assert "DELETE FROM vault_notes" in sql


async def test_search_vault_notes_returns_list():
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "id": uuid4(),
            "employee_id": EMPLOYEE_ID,
            "source": "shared",
            "vault_path": "nota.md",
            "title": "Nota",
            "tags": ["tag1"],
            "content_text": "Contenido",
            "modified_at": NOW,
            "indexed_at": NOW,
        }
    ]
    repo = _make_repo(conn)
    result = await repo.search_vault_notes([0.1] * 1024, limit=3)
    assert len(result) == 1
    assert isinstance(result[0], VaultNote)
    assert result[0].vault_path == "nota.md"
```

- [ ] **Step 2: Ejecutar tests — verificar que fallan**

```bash
python -m pytest tests/shared/db/test_vault_repository.py -v
```

Expected: `AttributeError: 'Repository' object has no attribute 'get_vault_note_mtimes'`

- [ ] **Step 3: Añadir métodos a `shared/db/repository.py`**

Añadir al final de la clase `Repository` (después de `get_credentials_by_prefix`):

```python
    async def get_vault_note_mtimes(self, source: str) -> dict[str, datetime]:
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
```

- [ ] **Step 4: Ejecutar tests — verificar que pasan**

```bash
python -m pytest tests/shared/db/test_vault_repository.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add shared/db/repository.py shared/db/models.py tests/shared/db/test_vault_repository.py
git commit -m "feat: add vault_notes repository methods (upsert, delete, search)"
```

---

## Task 4: `shared/vault/syncer.py` — VaultSyncer

**Files:**
- Create: `shared/vault/syncer.py`
- Create: `tests/vault/test_syncer.py`

- [ ] **Step 1: Crear `tests/vault/test_syncer.py`**

```python
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from shared.vault.syncer import SyncResult, VaultSyncer

EMPLOYEE_ID = uuid4()
OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)
NEW = datetime(2026, 4, 20, tzinfo=timezone.utc)


def _make_syncer(tmp_path: Path, pool, embed) -> VaultSyncer:
    return VaultSyncer(
        pool=pool,
        employee_id=EMPLOYEE_ID,
        employee_name="Maria",
        embed=embed,
        vaults_dir=tmp_path,
    )


def _make_pool(conn):
    pool = MagicMock()
    @asynccontextmanager
    async def acquire():
        yield conn
    pool.acquire = acquire
    return pool


async def test_sync_adds_new_note(tmp_path):
    vault = tmp_path / "shared"
    vault.mkdir()
    (vault / "nota.md").write_text("# Hola\nContenido.", encoding="utf-8")

    conn = AsyncMock()
    conn.fetch.return_value = []  # no existing notes
    conn.execute = AsyncMock()

    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024

    syncer = _make_syncer(tmp_path, _make_pool(conn), embed)
    result = await syncer.sync()

    assert result.added == 1
    assert result.skipped == 0
    embed.embed.assert_called_once()
    conn.execute.assert_called()


async def test_sync_skips_unchanged_note(tmp_path):
    vault = tmp_path / "shared"
    vault.mkdir()
    note_path = vault / "nota.md"
    note_path.write_text("# Hola\nContenido.", encoding="utf-8")

    # mtime is now — we fake a DB modified_at in the future so it's "newer"
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    conn = AsyncMock()
    conn.fetch.return_value = [{"vault_path": "nota.md", "modified_at": future}]
    conn.execute = AsyncMock()

    embed = AsyncMock()

    syncer = _make_syncer(tmp_path, _make_pool(conn), embed)
    result = await syncer.sync()

    assert result.skipped == 1
    assert result.added == 0
    embed.embed.assert_not_called()


async def test_sync_deletes_removed_note(tmp_path):
    vault = tmp_path / "shared"
    vault.mkdir()
    # vault is empty, but DB has a stale note

    conn = AsyncMock()
    # get_vault_note_mtimes returns one note that no longer exists on disk
    conn.fetch.return_value = [{"vault_path": "vieja.md", "modified_at": OLD}]
    conn.execute = AsyncMock()

    embed = AsyncMock()

    syncer = _make_syncer(tmp_path, _make_pool(conn), embed)
    result = await syncer.sync()

    assert result.deleted == 1
    # delete_vault_notes_not_in was called
    delete_calls = [
        call for call in conn.execute.call_args_list
        if "DELETE" in str(call)
    ]
    assert len(delete_calls) >= 1


async def test_sync_personal_vault(tmp_path):
    personal = tmp_path / "maria"
    personal.mkdir()
    (personal / "privada.md").write_text("Nota privada.", encoding="utf-8")

    conn = AsyncMock()
    conn.fetch.return_value = []
    conn.execute = AsyncMock()

    embed = AsyncMock()
    embed.embed.return_value = [0.2] * 1024

    syncer = _make_syncer(tmp_path, _make_pool(conn), embed)
    result = await syncer.sync()

    assert result.added == 1
```

- [ ] **Step 2: Ejecutar tests — verificar que fallan**

```bash
python -m pytest tests/vault/test_syncer.py -v
```

Expected: `ModuleNotFoundError: No module named 'shared.vault.syncer'`

- [ ] **Step 3: Crear `shared/vault/syncer.py`**

```python
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from shared.db.repository import Repository
from shared.llm.embeddings import EmbeddingClient
from shared.vault.parser import parse_note

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0


class VaultSyncer:
    def __init__(
        self,
        pool,
        employee_id: UUID,
        employee_name: str,
        embed: EmbeddingClient,
        vaults_dir: Path,
    ) -> None:
        self._pool = pool
        self._employee_id = employee_id
        self._employee_name = employee_name
        self._embed = embed
        self._vaults_dir = Path(vaults_dir)

    async def sync(self) -> SyncResult:
        result = SyncResult()
        for source, vault_dir in self._vault_dirs():
            await self._sync_source(source, vault_dir, result)
        return result

    def _vault_dirs(self) -> list[tuple[str, Path]]:
        dirs = []
        shared = self._vaults_dir / "shared"
        if shared.is_dir():
            dirs.append(("shared", shared))
        personal = self._vaults_dir / self._employee_name.lower()
        if personal.is_dir():
            dirs.append(("personal", personal))
        return dirs

    async def _sync_source(
        self, source: str, vault_dir: Path, result: SyncResult
    ) -> None:
        md_files = list(vault_dir.rglob("*.md"))

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            existing = await repo.get_vault_note_mtimes(source)

            disk_paths: list[str] = []
            for path in md_files:
                note = parse_note(path, vault_root=vault_dir)
                disk_paths.append(note.vault_path)

                db_mtime = existing.get(note.vault_path)
                if db_mtime is not None:
                    note_mtime = note.modified_at
                    if db_mtime.tzinfo is None:
                        db_mtime = db_mtime.replace(tzinfo=timezone.utc)
                    if note_mtime <= db_mtime:
                        result.skipped += 1
                        continue
                    is_update = True
                else:
                    is_update = False

                embedding = await self._embed.embed(note.content_text or note.title)
                await repo.upsert_vault_note(
                    source=source,
                    vault_path=note.vault_path,
                    title=note.title,
                    tags=note.tags,
                    content_text=note.content_text,
                    embedding=embedding,
                    modified_at=note.modified_at,
                )
                if is_update:
                    result.updated += 1
                else:
                    result.added += 1

            stale = [p for p in existing if p not in disk_paths]
            if stale:
                await repo.delete_vault_notes_not_in(source, disk_paths)
                result.deleted += len(stale)
```

- [ ] **Step 4: Ejecutar tests — verificar que pasan**

```bash
python -m pytest tests/vault/test_syncer.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add shared/vault/syncer.py tests/vault/test_syncer.py
git commit -m "feat: implement VaultSyncer with upsert, skip-on-unchanged, and delete-stale logic"
```

---

## Task 5: `secretary/memory.py` — incluir vault_notes en contexto

**Files:**
- Modify: `secretary/memory.py`
- Create: `tests/secretary/test_memory.py`

- [ ] **Step 1: Crear `tests/secretary/test_memory.py`**

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from shared.db.models import Conversation, Document, VaultNote
from secretary.memory import MemoryManager

EMPLOYEE_ID = uuid4()
NOW = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)


def _make_note(source: str, title: str, content: str) -> VaultNote:
    return VaultNote(
        id=uuid4(),
        employee_id=EMPLOYEE_ID,
        source=source,
        vault_path=f"{title}.md",
        title=title,
        tags=[],
        content_text=content,
        modified_at=NOW,
        indexed_at=NOW,
    )


async def test_build_context_includes_vault_notes():
    repo = AsyncMock()
    repo.get_recent_conversations.return_value = []
    repo.search_documents.return_value = []
    repo.search_vault_notes.return_value = [
        _make_note("shared", "Política empresa", "No usar redes sociales en horario laboral."),
    ]
    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024

    memory = MemoryManager(repo=repo, embed_client=embed)
    context = await memory.build_context("política de empresa")

    assert "Base de conocimiento" in context
    assert "Política empresa" in context
    assert "No usar redes sociales" in context


async def test_build_context_personal_notes_labeled():
    repo = AsyncMock()
    repo.get_recent_conversations.return_value = []
    repo.search_documents.return_value = []
    repo.search_vault_notes.return_value = [
        _make_note("personal", "Notas reunión", "Reunión el lunes a las 10h."),
    ]
    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024

    memory = MemoryManager(repo=repo, embed_client=embed)
    context = await memory.build_context("reunión")

    assert "Notas personales" in context
    assert "Notas reunión" in context


async def test_build_context_empty_vault_notes_no_section():
    repo = AsyncMock()
    repo.get_recent_conversations.return_value = []
    repo.search_documents.return_value = []
    repo.search_vault_notes.return_value = []
    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024

    memory = MemoryManager(repo=repo, embed_client=embed)
    context = await memory.build_context("algo")

    assert context == ""
```

- [ ] **Step 2: Ejecutar tests — verificar que fallan**

```bash
python -m pytest tests/secretary/test_memory.py -v
```

Expected: `FAILED` — `search_vault_notes` no está llamado en `build_context`

- [ ] **Step 3: Modificar `secretary/memory.py`**

Reemplazar el fichero completo:

```python
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
```

- [ ] **Step 4: Ejecutar tests — verificar que pasan**

```bash
python -m pytest tests/secretary/test_memory.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add secretary/memory.py tests/secretary/test_memory.py
git commit -m "feat: extend MemoryManager to include vault_notes in RAG context"
```

---

## Task 6: `shared/vault/cron.py` + `__init__.py` + servicio systemd

**Files:**
- Create: `shared/vault/__init__.py`
- Create: `shared/vault/cron.py`
- Create: `infrastructure/systemd/obsidian-sync.service`

- [ ] **Step 1: Crear `shared/vault/__init__.py`**

```python
from shared.vault.parser import NoteData, parse_note
from shared.vault.syncer import SyncResult, VaultSyncer

__all__ = ["NoteData", "parse_note", "SyncResult", "VaultSyncer"]
```

- [ ] **Step 2: Crear `shared/vault/cron.py`**

```python
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.embeddings import EmbeddingClient
from shared.vault.syncer import VaultSyncer

load_dotenv()
logger = logging.getLogger(__name__)


async def _fetch_active_employees(dsn: str) -> list[dict]:
    conn = await asyncpg.connect(dsn)
    rows = await conn.fetch(
        "SELECT id, name FROM employees WHERE is_active = true AND is_orchestrator = false"
    )
    await conn.close()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


async def run_once(
    dsn: str,
    embed: EmbeddingClient,
    store: CredentialStore,
    vaults_dir: Path,
) -> None:
    employees = await _fetch_active_employees(dsn)
    for emp in employees:
        pool = DatabasePool(dsn, emp["id"])
        await pool.connect()
        try:
            syncer = VaultSyncer(
                pool=pool,
                employee_id=emp["id"],
                employee_name=emp["name"],
                embed=embed,
                vaults_dir=vaults_dir,
            )
            result = await syncer.sync()
            logger.info(
                "Vault sync %s: +%d ~%d -%d skip%d",
                emp["name"], result.added, result.updated, result.deleted, result.skipped,
            )
        except Exception:
            logger.exception("Vault sync failed for employee %s", emp["name"])
        finally:
            await pool.disconnect()


async def main() -> None:
    vaults_dir_str = os.environ.get("OBSIDIAN_VAULTS_DIR")
    if not vaults_dir_str:
        logger.warning("OBSIDIAN_VAULTS_DIR not set — obsidian-sync not running")
        return

    vaults_dir = Path(vaults_dir_str)
    interval = int(os.environ.get("OBSIDIAN_SYNC_INTERVAL", "900"))
    dsn = os.environ.get("APP_DB_URL", os.environ["DATABASE_URL"])
    fernet_key = os.environ["FERNET_KEY"].encode()
    store = CredentialStore(fernet_key)

    embed = EmbeddingClient(
        base_url=os.environ["VLLM_EMBED_URL"],
        api_key=os.environ["VLLM_API_KEY"],
        model=os.environ["EMBEDDING_MODEL"],
    )

    logger.info("obsidian-sync starting, interval=%ds, vaults=%s", interval, vaults_dir)
    while True:
        try:
            await run_once(dsn, embed, store, vaults_dir)
        except Exception:
            logger.exception("run_once failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(main())
```

- [ ] **Step 3: Verificar sintaxis**

```bash
python -c "from shared.vault.cron import main; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Crear `infrastructure/systemd/obsidian-sync.service`**

```ini
[Unit]
Description=Obsidian Vault Sync — secretarios-virtuales
After=network.target postgresql.service

[Service]
Type=simple
User=secretarios
WorkingDirectory=/opt/secretarios-virtuales
EnvironmentFile=/opt/secretarios-virtuales/.env
ExecStart=/opt/secretarios-virtuales/.venv/bin/python -m shared.vault.cron
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Commit**

```bash
git add shared/vault/__init__.py shared/vault/cron.py infrastructure/systemd/obsidian-sync.service
git commit -m "feat: add vault cron service and systemd unit for obsidian-sync"
```

---

## Task 7: Tests finales + push

**Files:** ninguno nuevo

- [ ] **Step 1: Ejecutar suite completa**

```bash
python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: todos PASSED (o solo los 5 skips pre-existentes de email real)

- [ ] **Step 2: Verificar imports del paquete**

```bash
python -c "
from shared.vault import NoteData, parse_note, SyncResult, VaultSyncer
from shared.db.models import VaultNote
from secretary.memory import MemoryManager
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Push**

```bash
git push
```

---

## Self-Review

**Spec coverage:**
- ✅ Tabla `vault_notes` con unique index `(employee_id, source, vault_path)` — Task 1
- ✅ `python-frontmatter` como dependencia — Task 1
- ✅ `NoteData` + `parse_note`: frontmatter, wikilinks, hashtags, título por defecto, tags string/list — Task 2
- ✅ `VaultSyncer`: skip por mtime, upsert, delete de notas borradas, shared + personal vault — Task 4
- ✅ `MemoryManager.build_context` busca en paralelo docs + vault_notes — Task 5
- ✅ Etiquetas `[Base de conocimiento]` y `[Notas personales]` en contexto — Task 5
- ✅ `cron.py`: itera employees activos, intervalo configurable, no falla si `OBSIDIAN_VAULTS_DIR` no está — Task 6
- ✅ Servicio systemd `obsidian-sync.service` — Task 6
- ✅ Política RLS: `source='shared'` visible para todos — Task 1
- ✅ `get_vault_note_mtimes` carga en bulk (evita N+1) — Task 3

**Consistencia de tipos:**
- `NoteData.modified_at: datetime` → `repo.upsert_vault_note(..., modified_at: datetime)` → columna `TIMESTAMPTZ` ✓
- `VaultNote.tags: list[str]` → `repo.search_vault_notes` hace `list(r["tags"] or [])` ✓
- `VaultSyncer.embed` recibe `EmbeddingClient` en producción y `AsyncMock` en tests ✓
