# Extended Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 8 new capabilities to secretarios-virtuales: facts/preferences persistence, task tracking LLM tools, weekly summary, YouTube transcription, morning email digest, DuckDuckGo search, and GPS location search.

**Architecture:** New thin-client objects follow the existing calendar_client/email_client pattern. Each client wraps DB pool + employee_id. ToolExecutor gains new optional clients. Scheduled jobs are standalone scripts launched via systemd timers.

**Tech Stack:** asyncpg, httpx, yt-dlp (subprocess), existing WhisperClient, Nominatim API (free, no key), DuckDuckGo HTML (no key), python-telegram-bot for Telegram sends in jobs.

---

## File Map

**New files:**
- `infrastructure/db/migrations/003_facts.sql` — facts table with RLS
- `shared/facts/__init__.py`
- `shared/facts/client.py` — FactsClient wrapping pool + employee_id
- `shared/tasks/__init__.py`
- `shared/tasks/client.py` — TasksClient wrapping pool + employee_id
- `shared/search/__init__.py`
- `shared/search/duckduckgo.py` — DuckDuckGoClient using httpx
- `shared/youtube/__init__.py`
- `shared/youtube/transcriber.py` — YouTubeTranscriber (yt-dlp + whisper)
- `shared/location/__init__.py`
- `shared/location/nominatim.py` — NominatimClient (Overpass API)
- `secretary/handlers/location.py` — Telegram Location message handler
- `jobs/__init__.py`
- `jobs/weekly_summary.py` — Monday 8:00 summary per employee
- `jobs/morning_digest.py` — Daily 8:00 email digest per employee
- `infrastructure/systemd/weekly-summary.service`
- `infrastructure/systemd/weekly-summary.timer`
- `infrastructure/systemd/morning-digest.service`
- `infrastructure/systemd/morning-digest.timer`

**Modified files:**
- `shared/db/models.py` — add Fact dataclass
- `shared/db/repository.py` — add save_fact, list_facts, delete_fact, mark_task_done, update_task
- `shared/tools/definitions.py` — add 9 new tool definitions
- `shared/tools/executor.py` — add new handlers + new client params
- `shared/tools/__init__.py` — export new clients
- `secretary/agent.py` — add location handler registration
- `secretary/__main__.py` — wire up all new clients
- `pyproject.toml` — add jobs package

---

## Task 1: Facts DB migration + model + repository

**Files:**
- Create: `infrastructure/db/migrations/003_facts.sql`
- Modify: `shared/db/models.py`
- Modify: `shared/db/repository.py`

- [ ] **Step 1: Create migration file `infrastructure/db/migrations/003_facts.sql`**

```sql
CREATE TABLE IF NOT EXISTS facts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS facts_employee_key
    ON facts(employee_id, key);

CREATE INDEX IF NOT EXISTS facts_employee_category
    ON facts(employee_id, category);

ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE facts FORCE ROW LEVEL SECURITY;

CREATE POLICY facts_isolation ON facts
    USING (employee_id = current_setting('app.current_employee_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON facts TO svapp;
```

- [ ] **Step 2: Add Fact dataclass to `shared/db/models.py`**

Add after the `Task` dataclass (before VaultNote):

```python
@dataclass
class Fact:
    id: UUID
    employee_id: UUID
    key: str
    value: str
    category: str
    created_at: datetime
```

- [ ] **Step 3: Add fact methods + task completion methods to `shared/db/repository.py`**

Add these methods inside class `Repository`, after `get_pending_tasks`:

```python
async def save_fact(self, key: str, value: str, category: str = "general") -> None:
    await self._conn.execute(
        """
        INSERT INTO facts (employee_id, key, value, category)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (employee_id, key) DO UPDATE SET value = $3, category = $4
        """,
        self._employee_id, key, value, category,
    )

async def list_facts(self, category: str | None = None) -> list[Fact]:
    from shared.db.models import Fact
    if category:
        rows = await self._conn.fetch(
            "SELECT id, employee_id, key, value, category, created_at FROM facts "
            "WHERE employee_id = $1 AND category = $2 ORDER BY key",
            self._employee_id, category,
        )
    else:
        rows = await self._conn.fetch(
            "SELECT id, employee_id, key, value, category, created_at FROM facts "
            "WHERE employee_id = $1 ORDER BY category, key",
            self._employee_id,
        )
    return [
        Fact(id=r["id"], employee_id=r["employee_id"], key=r["key"],
             value=r["value"], category=r["category"], created_at=r["created_at"])
        for r in rows
    ]

async def delete_fact(self, key: str) -> bool:
    result = await self._conn.execute(
        "DELETE FROM facts WHERE employee_id = $1 AND key = $2",
        self._employee_id, key,
    )
    return result != "DELETE 0"

async def mark_task_done(self, task_id: str) -> bool:
    result = await self._conn.execute(
        "UPDATE tasks SET status = 'done' WHERE employee_id = $1 AND id = $2::uuid",
        self._employee_id, task_id,
    )
    return result != "UPDATE 0"

async def update_task(self, task_id: str, title: str | None = None, description: str | None = None) -> bool:
    if title is None and description is None:
        return False
    if title is not None and description is not None:
        result = await self._conn.execute(
            "UPDATE tasks SET title = $2, description = $3 WHERE employee_id = $1 AND id = $4::uuid",
            self._employee_id, title, description, task_id,
        )
    elif title is not None:
        result = await self._conn.execute(
            "UPDATE tasks SET title = $2 WHERE employee_id = $1 AND id = $3::uuid",
            self._employee_id, title, task_id,
        )
    else:
        result = await self._conn.execute(
            "UPDATE tasks SET description = $2 WHERE employee_id = $1 AND id = $3::uuid",
            self._employee_id, description, task_id,
        )
    return result != "UPDATE 0"

async def get_all_tasks(self) -> list[Task]:
    rows = await self._conn.fetch(
        "SELECT id, employee_id, title, description, status, created_at FROM tasks "
        "WHERE employee_id = $1 ORDER BY status, created_at ASC",
        self._employee_id,
    )
    return [
        Task(id=r["id"], employee_id=r["employee_id"], title=r["title"],
             description=r["description"], status=r["status"], created_at=r["created_at"])
        for r in rows
    ]
```

- [ ] **Step 4: Run migration to verify SQL is valid (on server, or just check syntax)**

```bash
# On the server:
psql "$DATABASE_URL" -f infrastructure/db/migrations/003_facts.sql
```

Expected: no errors, table created.

- [ ] **Step 5: Commit**

```bash
git add infrastructure/db/migrations/003_facts.sql shared/db/models.py shared/db/repository.py
git commit -m "feat(db): add facts table with RLS + repository methods for facts and task updates"
```

---

## Task 2: FactsClient + TasksClient thin wrappers

**Files:**
- Create: `shared/facts/__init__.py`, `shared/facts/client.py`
- Create: `shared/tasks/__init__.py`, `shared/tasks/client.py`

- [ ] **Step 1: Create `shared/facts/__init__.py`**

```python
from shared.facts.client import FactsClient

__all__ = ["FactsClient"]
```

- [ ] **Step 2: Create `shared/facts/client.py`**

```python
from __future__ import annotations

from uuid import UUID

from shared.db.models import Fact
from shared.db.pool import DatabasePool


class FactsClient:
    def __init__(self, pool: DatabasePool, employee_id: UUID) -> None:
        self._pool = pool
        self._employee_id = employee_id

    async def save(self, key: str, value: str, category: str = "general") -> None:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_fact(key=key, value=value, category=category)

    async def list_all(self, category: str | None = None) -> list[Fact]:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.list_facts(category=category)

    async def delete(self, key: str) -> bool:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.delete_fact(key=key)
```

- [ ] **Step 3: Create `shared/tasks/__init__.py`**

```python
from shared.tasks.client import TasksClient

__all__ = ["TasksClient"]
```

- [ ] **Step 4: Create `shared/tasks/client.py`**

```python
from __future__ import annotations

from uuid import UUID

from shared.db.models import Task
from shared.db.pool import DatabasePool


class TasksClient:
    def __init__(self, pool: DatabasePool, employee_id: UUID) -> None:
        self._pool = pool
        self._employee_id = employee_id

    async def create(self, title: str, description: str | None = None) -> str:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            task_id = await repo.save_task(title=title, description=description)
            return str(task_id)

    async def list_all(self) -> list[Task]:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.get_all_tasks()

    async def mark_done(self, task_id: str) -> bool:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.mark_task_done(task_id=task_id)

    async def update(self, task_id: str, title: str | None = None, description: str | None = None) -> bool:
        from shared.db.repository import Repository
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            return await repo.update_task(task_id=task_id, title=title, description=description)
```

- [ ] **Step 5: Commit**

```bash
git add shared/facts/ shared/tasks/
git commit -m "feat(shared): add FactsClient and TasksClient thin wrappers"
```

---

## Task 3: DuckDuckGo search + Nominatim clients

**Files:**
- Create: `shared/search/__init__.py`, `shared/search/duckduckgo.py`
- Create: `shared/location/__init__.py`, `shared/location/nominatim.py`

- [ ] **Step 1: Create `shared/search/__init__.py`**

```python
from shared.search.duckduckgo import DuckDuckGoClient

__all__ = ["DuckDuckGoClient"]
```

- [ ] **Step 2: Create `shared/search/duckduckgo.py`**

```python
from __future__ import annotations

import re

import httpx

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; secretarios-virtuales/1.0)",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
_MAX_RESULTS = 5


class DuckDuckGoClient:
    async def search(self, query: str, max_results: int = _MAX_RESULTS) -> str:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(_DDG_URL, data={"q": query}, headers=_HEADERS)
        if resp.status_code != 200:
            return f"Error buscando '{query}': HTTP {resp.status_code}"

        results = _parse_ddg_html(resp.text, max_results)
        if not results:
            return f"Sin resultados para '{query}'."
        lines = [f"Resultados para '{query}':"]
        for i, (title, snippet, url) in enumerate(results, 1):
            lines.append(f"\n{i}. **{title}**\n{snippet}\n🔗 {url}")
        return "\n".join(lines)


def _parse_ddg_html(html: str, max_results: int) -> list[tuple[str, str, str]]:
    results = []
    # Extract result blocks: title, snippet, URL
    title_pattern = re.compile(r'class="result__title"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</span>', re.DOTALL)

    titles = title_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for (url, raw_title), raw_snippet in zip(titles[:max_results], snippets[:max_results]):
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        snippet = re.sub(r"<[^>]+>", "", raw_snippet).strip()
        results.append((title, snippet, url))
    return results
```

- [ ] **Step 3: Create `shared/location/__init__.py`**

```python
from shared.location.nominatim import NominatimClient

__all__ = ["NominatimClient"]
```

- [ ] **Step 4: Create `shared/location/nominatim.py`**

```python
from __future__ import annotations

import httpx

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_HEADERS = {"User-Agent": "secretarios-virtuales/1.0 (contact@example.com)"}


class NominatimClient:
    async def reverse_geocode(self, lat: float, lon: float) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "json"},
                headers=_HEADERS,
            )
        if resp.status_code != 200:
            return f"Error geocodificando: HTTP {resp.status_code}"
        data = resp.json()
        return data.get("display_name", f"{lat},{lon}")

    async def nearby(self, lat: float, lon: float, query: str, radius_m: int = 1000) -> str:
        # Overpass query: find named amenities near point
        overpass_q = f"""
[out:json][timeout:15];
(
  node(around:{radius_m},{lat},{lon})[name][amenity];
  node(around:{radius_m},{lat},{lon})[name][shop];
  node(around:{radius_m},{lat},{lon})[name][tourism];
);
out body 20;
"""
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(_OVERPASS_URL, data={"data": overpass_q}, headers=_HEADERS)
        if resp.status_code != 200:
            return f"Error consultando Overpass: HTTP {resp.status_code}"
        data = resp.json()
        elements = data.get("elements", [])
        if not elements:
            return f"No encontré lugares cerca ({radius_m}m)."

        # Filter by query if provided
        q_lower = query.lower()
        if q_lower:
            filtered = [e for e in elements if q_lower in (e.get("tags", {}).get("name", "") + " " + e.get("tags", {}).get("amenity", "") + " " + e.get("tags", {}).get("shop", "")).lower()]
            elements = filtered or elements

        lines = [f"Lugares cercanos ({radius_m}m) a tu ubicación:"]
        for e in elements[:10]:
            tags = e.get("tags", {})
            name = tags.get("name", "Sin nombre")
            kind = tags.get("amenity") or tags.get("shop") or tags.get("tourism") or "lugar"
            e_lat = e.get("lat", lat)
            e_lon = e.get("lon", lon)
            lines.append(f"• **{name}** ({kind}) — maps.google.com/?q={e_lat},{e_lon}")
        return "\n".join(lines)
```

- [ ] **Step 5: Commit**

```bash
git add shared/search/ shared/location/
git commit -m "feat(shared): add DuckDuckGoClient and NominatimClient"
```

---

## Task 4: YouTube transcriber

**Files:**
- Create: `shared/youtube/__init__.py`, `shared/youtube/transcriber.py`

- [ ] **Step 1: Create `shared/youtube/__init__.py`**

```python
from shared.youtube.transcriber import YouTubeTranscriber

__all__ = ["YouTubeTranscriber"]
```

- [ ] **Step 2: Create `shared/youtube/transcriber.py`**

```python
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from shared.audio.whisper import WhisperClient

_MAX_DURATION_S = 7200  # 2 hours


class YouTubeTranscriber:
    def __init__(self, whisper: WhisperClient) -> None:
        self._whisper = whisper

    async def transcribe(self, url: str) -> str:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = await self._download_audio(url, tmpdir)
            audio_bytes = Path(audio_path).read_bytes()
        text = await self._whisper.transcribe(audio_bytes, filename="audio.mp3")
        return text

    async def _download_audio(self, url: str, output_dir: str) -> str:
        out_template = str(Path(output_dir) / "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "--max-filesize", "100M",
            "--no-playlist",
            "-o", out_template,
            "--print", "after_move:filepath",
            url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("yt-dlp tardó demasiado (>5min)")

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:500]
            raise RuntimeError(f"yt-dlp error: {err}")

        filepath = stdout.decode().strip().splitlines()[-1]
        if not filepath or not Path(filepath).exists():
            # Fallback: find downloaded file
            files = list(Path(output_dir).glob("*.mp3"))
            if not files:
                raise RuntimeError("No se pudo encontrar el audio descargado")
            filepath = str(files[0])
        return filepath
```

- [ ] **Step 3: Commit**

```bash
git add shared/youtube/
git commit -m "feat(shared): add YouTubeTranscriber using yt-dlp + whisper"
```

---

## Task 5: New tool definitions (9 new tools)

**Files:**
- Modify: `shared/tools/definitions.py`

- [ ] **Step 1: Add 9 new tool definitions to `shared/tools/definitions.py`**

Append before the closing `]` of `TOOL_DEFINITIONS`:

```python
    {
        "type": "function",
        "function": {
            "name": "fact_save",
            "description": "Guarda un dato personal importante del usuario para recordarlo siempre (ej: 'médico', 'Dr. García'; 'coche', 'Toyota Corolla 2020'). También úsalo para guardar preferencias detectadas en la conversación. La clave debe ser única y descriptiva.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Clave única del dato (ej: 'médico', 'coche', 'preferencia_idioma')"},
                    "value": {"type": "string", "description": "Valor del dato"},
                    "category": {"type": "string", "description": "Categoría: 'personal', 'preference', 'work', 'health', 'general'"},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fact_list",
            "description": "Lista los datos personales guardados del usuario. Úsalo para recordar información antes de responder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Filtrar por categoría (opcional): 'personal', 'preference', 'work', 'health', 'general'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_create",
            "description": "Crea una nueva tarea pendiente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título de la tarea"},
                    "description": {"type": "string", "description": "Descripción opcional de la tarea"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_list",
            "description": "Lista las tareas del usuario con su estado (pending/done).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_done",
            "description": "Marca una tarea como completada por su ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "UUID de la tarea"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_update",
            "description": "Actualiza el título o descripción de una tarea.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "UUID de la tarea"},
                    "title": {"type": "string", "description": "Nuevo título (opcional)"},
                    "description": {"type": "string", "description": "Nueva descripción (opcional)"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Busca información en la web usando DuckDuckGo. Úsalo para responder preguntas que requieren información actualizada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Consulta de búsqueda"},
                    "max_results": {"type": "integer", "description": "Número máximo de resultados (1-10, por defecto 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "youtube_transcribe",
            "description": "Descarga y transcribe un vídeo de YouTube o podcast. Guarda la transcripción en el vault del agente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL del vídeo de YouTube o podcast"},
                    "save_path": {"type": "string", "description": "Ruta donde guardar la transcripción (ej: 'transcripciones/podcast_2026-04-21.md')"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nearby_search",
            "description": "Busca lugares cercanos a la última ubicación GPS conocida del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Tipo de lugar a buscar (ej: 'farmacia', 'restaurante', 'supermercado')"},
                    "radius_m": {"type": "integer", "description": "Radio de búsqueda en metros (por defecto 1000)"},
                },
                "required": ["query"],
            },
        },
    },
```

- [ ] **Step 2: Commit**

```bash
git add shared/tools/definitions.py
git commit -m "feat(tools): add 9 new tool definitions: facts, tasks, web_search, youtube_transcribe, nearby_search"
```

---

## Task 6: ToolExecutor new handlers

**Files:**
- Modify: `shared/tools/executor.py`
- Modify: `shared/tools/__init__.py`

- [ ] **Step 1: Update `shared/tools/executor.py`**

Replace the entire file with this updated version that adds new clients and handlers:

```python
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from shared.tools.ssh_store import SSHStore

if TYPE_CHECKING:
    from shared.calendar.client import CalendarClient
    from shared.email.client import EmailClient
    from shared.facts.client import FactsClient
    from shared.tasks.client import TasksClient
    from shared.search.duckduckgo import DuckDuckGoClient
    from shared.location.nominatim import NominatimClient
    from shared.youtube.transcriber import YouTubeTranscriber

_MAX_OUTPUT = 4000
_MAX_FILE = 8000


class ToolExecutor:
    def __init__(
        self,
        ssh_store: SSHStore | None = None,
        calendar_client: CalendarClient | None = None,
        email_client: EmailClient | None = None,
        facts_client: FactsClient | None = None,
        tasks_client: TasksClient | None = None,
        search_client: DuckDuckGoClient | None = None,
        location_client: NominatimClient | None = None,
        youtube_client: YouTubeTranscriber | None = None,
        last_location: dict | None = None,
    ) -> None:
        self._ssh = ssh_store
        self._calendar = calendar_client
        self._email = email_client
        self._facts = facts_client
        self._tasks = tasks_client
        self._search = search_client
        self._location = location_client
        self._youtube = youtube_client
        self._last_location: dict | None = last_location  # {"lat": float, "lon": float}

    def update_location(self, lat: float, lon: float) -> None:
        self._last_location = {"lat": lat, "lon": lon}

    async def run(self, name: str, args: dict) -> str:
        try:
            if name == "bash":
                return await self._bash(args["command"])
            if name == "ssh_exec":
                return await self._ssh_exec(args["name"], args["command"])
            if name == "ssh_save":
                return await self._ssh_save(args)
            if name == "ssh_list":
                return await self._ssh_list()
            if name == "read_file":
                return self._read_file(args["path"])
            if name == "write_file":
                return self._write_file(args["path"], args["content"])
            if name == "list_dir":
                return self._list_dir(args["path"])
            if name == "calendar_list":
                return await self._calendar_list(args)
            if name == "calendar_create":
                return await self._calendar_create(args)
            if name == "calendar_modify":
                return await self._calendar_modify(args)
            if name == "calendar_cancel":
                return await self._calendar_cancel(args)
            if name == "email_send":
                return await self._email_send(args)
            if name == "email_read":
                return await self._email_read(args)
            if name == "fact_save":
                return await self._fact_save(args)
            if name == "fact_list":
                return await self._fact_list(args)
            if name == "task_create":
                return await self._task_create(args)
            if name == "task_list":
                return await self._task_list()
            if name == "task_done":
                return await self._task_done(args)
            if name == "task_update":
                return await self._task_update(args)
            if name == "web_search":
                return await self._web_search(args)
            if name == "youtube_transcribe":
                return await self._youtube_transcribe(args)
            if name == "nearby_search":
                return await self._nearby_search(args)
            return f"Herramienta desconocida: {name}"
        except KeyError as e:
            return f"Error: falta el parámetro {e}"
        except Exception as e:
            return f"Error ejecutando {name}: {e}"

    async def _bash(self, command: str) -> str:
        if self._ssh is None:
            return "Herramienta bash no disponible."
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            return "Error: timeout (60s) alcanzado"
        out = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
        if len(out) > _MAX_OUTPUT:
            out = out[:_MAX_OUTPUT] + f"\n... [truncado a {_MAX_OUTPUT} chars]"
        return out or "(sin salida)"

    async def _ssh_exec(self, name: str, command: str) -> str:
        if self._ssh is None:
            return "Herramienta SSH no disponible."
        import asyncssh
        data = await self._ssh.load(name)
        connect_kwargs: dict = {
            "host": data["host"],
            "port": data.get("port", 22),
            "username": data["user"],
            "known_hosts": None,
        }
        if "ssh_key" in data:
            connect_kwargs["client_keys"] = [asyncssh.import_private_key(data["ssh_key"])]
        else:
            connect_kwargs["password"] = data.get("password", "")
        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run(command, check=False)
        out = ((result.stdout or "") + (result.stderr or "")).strip()
        if len(out) > _MAX_OUTPUT:
            out = out[:_MAX_OUTPUT] + "\n... [truncado]"
        return out or "(sin salida)"

    async def _ssh_save(self, args: dict) -> str:
        if self._ssh is None:
            return "Herramienta SSH no disponible."
        await self._ssh.save(
            name=args["name"],
            host=args["host"],
            user=args["user"],
            password=args.get("password"),
            ssh_key=args.get("ssh_key"),
            port=int(args.get("port", 22)),
        )
        return f"✅ Conexión '{args['name']}' ({args['host']}) guardada."

    async def _ssh_list(self) -> str:
        if self._ssh is None:
            return "Herramienta SSH no disponible."
        connections = await self._ssh.list_all()
        if not connections:
            return "No hay conexiones SSH guardadas."
        lines = [f"• {c['name']}: {c['user']}@{c['host']}:{c['port']}" for c in connections]
        return "Conexiones SSH guardadas:\n" + "\n".join(lines)

    def _read_file(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: el fichero '{path}' no existe."
        if not p.is_file():
            return f"Error: '{path}' no es un fichero."
        content = p.read_text(errors="replace")
        if len(content) > _MAX_FILE:
            content = content[:_MAX_FILE] + f"\n... [truncado a {_MAX_FILE} chars]"
        return content

    def _write_file(self, path: str, content: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"✅ Fichero '{path}' escrito ({len(content)} chars)."

    def _list_dir(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: '{path}' no existe."
        if not p.is_dir():
            return f"Error: '{path}' no es un directorio."
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = []
        for e in entries:
            if e.is_dir():
                lines.append(f"📁 {e.name}/")
            else:
                lines.append(f"📄 {e.name} ({e.stat().st_size} bytes)")
        return "\n".join(lines) if lines else "(directorio vacío)"

    async def _calendar_list(self, args: dict) -> str:
        if self._calendar is None:
            return "Calendario no configurado. Usa /config_calendar para configurarlo."
        days_ahead = int(args.get("days_ahead", 7))
        events = await self._calendar.list_events(days_ahead=days_ahead)
        if not events:
            return f"No hay eventos en los próximos {days_ahead} días."
        lines = []
        for e in events:
            local_start = e.start.strftime("%d/%m/%Y %H:%M")
            line = f"• [{e.id}] *{e.title}* — {local_start}"
            if e.location:
                line += f" 📍 {e.location}"
            lines.append(line)
        return "\n".join(lines)

    async def _calendar_create(self, args: dict) -> str:
        if self._calendar is None:
            return "Calendario no configurado. Usa /config_calendar para configurarlo."
        start = datetime.fromisoformat(args["start_iso"])
        end = datetime.fromisoformat(args["end_iso"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        event = await self._calendar.create_event(
            title=args["title"],
            start=start,
            end=end,
            description=args.get("description", ""),
            location=args.get("location", ""),
        )
        return f"✅ Evento creado: *{event.title}* el {event.start.strftime('%d/%m/%Y %H:%M')} (ID: {event.id})"

    async def _calendar_modify(self, args: dict) -> str:
        if self._calendar is None:
            return "Calendario no configurado. Usa /config_calendar para configurarlo."
        event_id = args["event_id"]
        fields = {k: v for k, v in args.items() if k != "event_id"}
        event = await self._calendar.modify_event(event_id, **fields)
        return f"✅ Evento actualizado: *{event.title}* el {event.start.strftime('%d/%m/%Y %H:%M')}"

    async def _calendar_cancel(self, args: dict) -> str:
        if self._calendar is None:
            return "Calendario no configurado. Usa /config_calendar para configurarlo."
        event_id = args["event_id"]
        await self._calendar.cancel_event(event_id)
        return f"✅ Evento {event_id} cancelado."

    async def _email_send(self, args: dict) -> str:
        if self._email is None:
            return "Email no configurado. Usa /config_email para activarlo."
        await self._email.send(to=args["to"], subject=args["subject"], body=args["body"])
        return f"✅ Email enviado a {args['to']}."

    async def _email_read(self, args: dict) -> str:
        if self._email is None:
            return "Email no configurado. Usa /config_email para activarlo."
        limit = int(args.get("limit", 5))
        messages = await self._email.fetch_inbox(limit=limit)
        if not messages:
            return "No hay emails nuevos."
        lines = []
        for m in messages:
            lines.append(f"📧 *De:* {m.sender}\n*Asunto:* {m.subject}\n{m.body[:300]}")
        return "\n\n---\n\n".join(lines)

    async def _fact_save(self, args: dict) -> str:
        if self._facts is None:
            return "Servicio de datos no disponible."
        key = args["key"]
        value = args["value"]
        category = args.get("category", "general")
        await self._facts.save(key=key, value=value, category=category)
        return f"✅ Guardado: {key} = {value} (categoría: {category})"

    async def _fact_list(self, args: dict) -> str:
        if self._facts is None:
            return "Servicio de datos no disponible."
        category = args.get("category")
        facts = await self._facts.list_all(category=category)
        if not facts:
            return "No hay datos personales guardados."
        lines = ["📋 Datos personales guardados:"]
        current_cat = None
        for f in facts:
            if f.category != current_cat:
                current_cat = f.category
                lines.append(f"\n**{current_cat}:**")
            lines.append(f"  • {f.key}: {f.value}")
        return "\n".join(lines)

    async def _task_create(self, args: dict) -> str:
        if self._tasks is None:
            return "Servicio de tareas no disponible."
        title = args["title"]
        description = args.get("description")
        task_id = await self._tasks.create(title=title, description=description)
        return f"✅ Tarea creada: {title} (ID: {task_id})"

    async def _task_list(self) -> str:
        if self._tasks is None:
            return "Servicio de tareas no disponible."
        tasks = await self._tasks.list_all()
        if not tasks:
            return "No hay tareas."
        pending = [t for t in tasks if t.status == "pending"]
        done = [t for t in tasks if t.status == "done"]
        lines = []
        if pending:
            lines.append("📋 **Tareas pendientes:**")
            for t in pending:
                desc = f" — {t.description}" if t.description else ""
                lines.append(f"  • [{t.id}] {t.title}{desc}")
        if done:
            lines.append("\n✅ **Completadas:**")
            for t in done[-5:]:  # last 5 done tasks
                lines.append(f"  ~~{t.title}~~")
        return "\n".join(lines) if lines else "No hay tareas."

    async def _task_done(self, args: dict) -> str:
        if self._tasks is None:
            return "Servicio de tareas no disponible."
        task_id = args["task_id"]
        ok = await self._tasks.mark_done(task_id=task_id)
        return f"✅ Tarea {task_id} marcada como completada." if ok else f"No encontré la tarea {task_id}."

    async def _task_update(self, args: dict) -> str:
        if self._tasks is None:
            return "Servicio de tareas no disponible."
        task_id = args["task_id"]
        title = args.get("title")
        description = args.get("description")
        ok = await self._tasks.update(task_id=task_id, title=title, description=description)
        return f"✅ Tarea {task_id} actualizada." if ok else f"No encontré la tarea {task_id}."

    async def _web_search(self, args: dict) -> str:
        if self._search is None:
            return "Búsqueda web no disponible."
        query = args["query"]
        max_results = min(int(args.get("max_results", 5)), 10)
        return await self._search.search(query=query, max_results=max_results)

    async def _youtube_transcribe(self, args: dict) -> str:
        if self._youtube is None:
            return "Transcripción de YouTube no disponible."
        url = args["url"]
        save_path = args.get("save_path", f"transcripciones/video_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md")
        text = await self._youtube.transcribe(url=url)
        # Save to vault
        full_path = Path("./data/vault") / save_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(f"# Transcripción\n\nFuente: {url}\nFecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n{text}")
        preview = text[:500] + "..." if len(text) > 500 else text
        return f"✅ Transcripción guardada en {save_path} ({len(text)} chars)\n\nExtracto:\n{preview}"

    async def _nearby_search(self, args: dict) -> str:
        if self._location is None:
            return "Búsqueda de ubicación no disponible."
        if self._last_location is None:
            return "No tengo tu ubicación. Envíame tu ubicación por Telegram primero (botón 📎 → Ubicación)."
        query = args["query"]
        radius_m = int(args.get("radius_m", 1000))
        lat = self._last_location["lat"]
        lon = self._last_location["lon"]
        return await self._location.nearby(lat=lat, lon=lon, query=query, radius_m=radius_m)
```

- [ ] **Step 2: Update `shared/tools/__init__.py` to export new clients**

Read the current file first, then add new exports. The file should export:

```python
from shared.tools.definitions import TOOL_DEFINITIONS
from shared.tools.executor import ToolExecutor
from shared.tools.safety import is_destructive
from shared.tools.ssh_store import SSHStore

__all__ = ["TOOL_DEFINITIONS", "ToolExecutor", "is_destructive", "SSHStore"]
```

- [ ] **Step 3: Commit**

```bash
git add shared/tools/executor.py shared/tools/__init__.py
git commit -m "feat(tools): implement all new tool handlers in ToolExecutor"
```

---

## Task 7: GPS location handler + secretary agent wiring

**Files:**
- Create: `secretary/handlers/location.py`
- Modify: `secretary/agent.py`

- [ ] **Step 1: Create `secretary/handlers/location.py`**

```python
from __future__ import annotations

import json
import logging
from uuid import UUID

from telegram import Update
from telegram.ext import ContextTypes

from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository

logger = logging.getLogger(__name__)


async def handle_location(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    employee_id: UUID,
    pool: DatabasePool,
    store: CredentialStore,
    executor,  # ToolExecutor, untyped to avoid circular import
) -> str:
    loc = update.message.location  # type: ignore[union-attr]
    if loc is None:
        return "No encontré ubicación en el mensaje."

    lat = loc.latitude
    lon = loc.longitude

    # Persist to credentials for the job scripts
    location_data = json.dumps({"lat": lat, "lon": lon})
    async with pool.acquire() as conn:
        repo = Repository(conn, employee_id)
        await repo.save_credential("last_location", store.encrypt(location_data))

    # Update in-memory location in executor
    if executor is not None:
        executor.update_location(lat=lat, lon=lon)

    return (
        f"📍 Ubicación guardada: {lat:.5f}, {lon:.5f}\n"
        "Ahora puedo buscar lugares cercanos. Dime qué buscas (ej: 'farmacia cercana')."
    )
```

- [ ] **Step 2: Add location handler to `secretary/agent.py`**

After the existing imports, add:
```python
from secretary.handlers.location import handle_location
```

After `app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))` in the `run()` method, add:
```python
app.add_handler(MessageHandler(filters.LOCATION, self._handle_location))
```

Add the handler method inside `SecretaryAgent` class, after `_handle_photo`:

```python
async def _handle_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await self._is_authorized(update):
        return
    response = await handle_location(
        update=update,
        context=context,
        employee_id=self._employee_id,
        pool=self._pool,
        store=self._store,
        executor=self._executor,
    )
    await update.message.reply_text(response)  # type: ignore[union-attr]
```

- [ ] **Step 3: Commit**

```bash
git add secretary/handlers/location.py secretary/agent.py
git commit -m "feat(secretary): add GPS location handler with nearby_search support"
```

---

## Task 8: Wire all new clients in secretary/__main__.py

**Files:**
- Modify: `secretary/__main__.py`

- [ ] **Step 1: Update `secretary/__main__.py` to wire all new clients**

Replace the entire file with:

```python
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv

from secretary.agent import SecretaryAgent
from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient
from shared.tools import SSHStore, ToolExecutor
from shared.facts.client import FactsClient
from shared.tasks.client import TasksClient
from shared.search.duckduckgo import DuckDuckGoClient
from shared.location.nominatim import NominatimClient
from shared.youtube.transcriber import YouTubeTranscriber

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


async def main(employee_id_str: str) -> None:
    employee_id = UUID(employee_id_str)
    app_dsn = os.environ.get("APP_DB_URL", os.environ["DATABASE_URL"])

    raw_conn = await asyncpg.connect(app_dsn)
    row = await raw_conn.fetchrow(
        "SELECT name, telegram_chat_id FROM employees WHERE id = $1",
        employee_id,
    )
    await raw_conn.close()

    if not row:
        print(f"ERROR: employee {employee_id} not found")
        sys.exit(1)

    employee_name = row["name"]
    telegram_chat_id = row["telegram_chat_id"]

    raw_conn = await asyncpg.connect(app_dsn)
    async with raw_conn.transaction():
        await raw_conn.execute(
            "SELECT set_config('app.current_employee_id', $1, true)",
            str(employee_id),
        )
        enc_token = await raw_conn.fetchval(
            "SELECT encrypted FROM credentials "
            "WHERE employee_id=$1 AND service_type='telegram_token'",
            employee_id,
        )
    await raw_conn.close()

    fernet_key = os.environ["FERNET_KEY"].encode()
    store = CredentialStore(fernet_key)
    bot_token = store.decrypt(enc_token)

    raw_conn2 = await asyncpg.connect(app_dsn)
    async with raw_conn2.transaction():
        await raw_conn2.execute(
            "SELECT set_config('app.current_employee_id', $1, true)",
            str(employee_id),
        )
        tools_enc = await raw_conn2.fetchval(
            "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='tools_enabled'",
            employee_id,
        )
    await raw_conn2.close()
    tools_enabled = tools_enc is not None and store.decrypt(tools_enc) == "true"

    # Load calendar
    raw_conn3 = await asyncpg.connect(app_dsn)
    async with raw_conn3.transaction():
        await raw_conn3.execute(
            "SELECT set_config('app.current_employee_id', $1, true)",
            str(employee_id),
        )
        calendar_provider_enc = await raw_conn3.fetchval(
            "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='calendar_provider'",
            employee_id,
        )
    await raw_conn3.close()

    calendar_client = None
    if calendar_provider_enc is not None:
        from shared.calendar.client import make_calendar_client
        provider = store.decrypt(calendar_provider_enc)
        raw_conn4 = await asyncpg.connect(app_dsn)
        async with raw_conn4.transaction():
            await raw_conn4.execute(
                "SELECT set_config('app.current_employee_id', $1, true)",
                str(employee_id),
            )
            if provider == "google":
                token_enc = await raw_conn4.fetchval(
                    "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='calendar_google_token'",
                    employee_id,
                )
                creds = json.loads(store.decrypt(token_enc))
            else:
                caldav_enc = await raw_conn4.fetchval(
                    "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='calendar_caldav'",
                    employee_id,
                )
                creds = json.loads(store.decrypt(caldav_enc))
        await raw_conn4.close()
        try:
            calendar_client = make_calendar_client(provider, creds)
        except Exception as e:
            logging.warning("Failed to create calendar client: %s", e)

    # Load email
    raw_conn5 = await asyncpg.connect(app_dsn)
    async with raw_conn5.transaction():
        await raw_conn5.execute(
            "SELECT set_config('app.current_employee_id', $1, true)",
            str(employee_id),
        )
        email_imap_enc = await raw_conn5.fetchval(
            "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='email_imap'",
            employee_id,
        )
        email_smtp_enc = await raw_conn5.fetchval(
            "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='email_smtp'",
            employee_id,
        )
    await raw_conn5.close()

    email_client = None
    if email_imap_enc and email_smtp_enc:
        from shared.email.client import EmailClient
        from shared.email.models import EmailConfig
        imap = json.loads(store.decrypt(email_imap_enc))
        smtp = json.loads(store.decrypt(email_smtp_enc))
        try:
            email_client = EmailClient(
                EmailConfig(
                    imap_host=imap["host"],
                    imap_port=int(imap["port"]),
                    smtp_host=smtp["host"],
                    smtp_port=int(smtp["port"]),
                    username=imap["username"],
                    password=imap["password"],
                )
            )
        except Exception as e:
            logging.warning("Failed to create email client: %s", e)

    # Load last known location
    raw_conn6 = await asyncpg.connect(app_dsn)
    async with raw_conn6.transaction():
        await raw_conn6.execute(
            "SELECT set_config('app.current_employee_id', $1, true)",
            str(employee_id),
        )
        location_enc = await raw_conn6.fetchval(
            "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='last_location'",
            employee_id,
        )
    await raw_conn6.close()

    last_location = None
    if location_enc:
        try:
            last_location = json.loads(store.decrypt(location_enc))
        except Exception:
            pass

    pool = DatabasePool(app_dsn, employee_id)
    await pool.connect()

    ssh_store = None
    if tools_enabled:
        ssh_store = SSHStore(pool=pool, employee_id=employee_id, store=store)

    whisper = WhisperClient(base_url=os.environ["WHISPER_URL"])

    # Always create executor (facts, tasks, search always available; ssh only if tools_enabled)
    executor = ToolExecutor(
        ssh_store=ssh_store,
        calendar_client=calendar_client,
        email_client=email_client,
        facts_client=FactsClient(pool=pool, employee_id=employee_id),
        tasks_client=TasksClient(pool=pool, employee_id=employee_id),
        search_client=DuckDuckGoClient(),
        location_client=NominatimClient(),
        youtube_client=YouTubeTranscriber(whisper=whisper),
        last_location=last_location,
    )

    agent = SecretaryAgent(
        employee_id=employee_id,
        employee_name=employee_name,
        allowed_chat_id=telegram_chat_id,
        db_pool=pool,
        chat=ChatClient(
            base_url=os.environ["VLLM_CHAT_URL"],
            api_key=os.environ["VLLM_API_KEY"],
            model=os.environ["CHAT_MODEL"],
        ),
        embed=EmbeddingClient(
            base_url=os.environ["VLLM_EMBED_URL"],
            api_key=os.environ["VLLM_API_KEY"],
            model=os.environ["EMBEDDING_MODEL"],
        ),
        whisper=whisper,
        documents_dir=Path(os.environ.get("DOCUMENTS_DIR", "./data/documents")),
        fernet_key=fernet_key,
        redis_url=os.environ["REDIS_URL"],
        executor=executor,
        calendar_client=calendar_client,
        google_client_id=os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", ""),
        google_client_secret=os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", ""),
    )

    await agent.run(bot_token)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m secretary <employee_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 2: Add `jobs` package to `pyproject.toml`**

In `pyproject.toml`, in the `packages` or `find` section, add `"jobs"` alongside the other packages. For example if there's a section like:
```toml
[tool.setuptools.packages.find]
```
or a `packages` list, add `"jobs"`.

- [ ] **Step 3: Create `jobs/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Commit**

```bash
git add secretary/__main__.py jobs/__init__.py pyproject.toml
git commit -m "feat(secretary): wire all new tool clients into __main__.py"
```

---

## Task 9: Weekly summary systemd job

**Files:**
- Create: `jobs/weekly_summary.py`
- Create: `infrastructure/systemd/weekly-summary.service`
- Create: `infrastructure/systemd/weekly-summary.timer`

- [ ] **Step 1: Create `jobs/weekly_summary.py`**

```python
"""Weekly summary job — runs Monday 8:00 via systemd timer.

Fetches the past 7 days of conversations + tasks for each active employee
and sends a Telegram summary generated by the LLM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
from dotenv import load_dotenv

from shared.crypto import CredentialStore
from shared.llm.chat import ChatClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "Eres un asistente que genera resúmenes semanales concisos en español. "
    "Dado el historial de conversaciones y tareas de una persona, genera un resumen "
    "de máximo 300 palabras: qué se trató esta semana, tareas pendientes importantes, "
    "y cualquier información destacable. Sé amigable y directo."
)


async def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


async def summarize_employee(
    conn: asyncpg.Connection,
    employee_id,
    employee_name: str,
    chat_id: str,
    store: CredentialStore,
    chat: ChatClient,
) -> None:
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # Fetch last 50 conversation entries from the week
    rows = await conn.fetch(
        """
        SELECT role, content, created_at FROM conversations
        WHERE employee_id = $1 AND created_at >= $2
        ORDER BY created_at ASC
        LIMIT 50
        """,
        employee_id, week_ago,
    )
    conv_lines = [f"[{r['created_at'].strftime('%d/%m %H:%M')}] {r['role']}: {r['content'][:200]}" for r in rows]

    # Fetch tasks
    task_rows = await conn.fetch(
        "SELECT title, description, status FROM tasks WHERE employee_id = $1 ORDER BY status, created_at",
        employee_id,
    )
    task_lines = [f"- [{t['status']}] {t['title']}" + (f": {t['description'][:100]}" if t['description'] else "") for t in task_rows]

    if not conv_lines and not task_lines:
        logger.info("No data for employee %s this week, skipping", employee_name)
        return

    user_content = f"Conversaciones de esta semana:\n" + "\n".join(conv_lines or ["(ninguna)"])
    user_content += f"\n\nTareas:\n" + "\n".join(task_lines or ["(ninguna)"])

    summary, _ = await chat.complete_with_tools(
        messages=[{"role": "user", "content": user_content}],
        system=_SUMMARY_SYSTEM,
        tools=[],
    )

    # Get bot token
    enc_token = await conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id = $1 AND service_type = 'telegram_token'",
        employee_id,
    )
    if not enc_token:
        logger.warning("No telegram token for employee %s", employee_name)
        return

    bot_token = store.decrypt(enc_token)
    text = f"📊 *Resumen semanal — {datetime.now().strftime('%d/%m/%Y')}*\n\n{summary}"
    await _send_telegram(bot_token, chat_id, text)
    logger.info("Weekly summary sent to %s", employee_name)


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]  # superuser, bypasses RLS
    fernet_key = os.environ["FERNET_KEY"].encode()
    store = CredentialStore(fernet_key)
    chat = ChatClient(
        base_url=os.environ["VLLM_CHAT_URL"],
        api_key=os.environ["VLLM_API_KEY"],
        model=os.environ["CHAT_MODEL"],
    )

    conn = await asyncpg.connect(dsn)
    try:
        employees = await conn.fetch(
            "SELECT id, name, telegram_chat_id FROM employees "
            "WHERE is_active = true AND is_orchestrator = false AND telegram_chat_id IS NOT NULL"
        )
        for emp in employees:
            try:
                await summarize_employee(
                    conn=conn,
                    employee_id=emp["id"],
                    employee_name=emp["name"],
                    chat_id=emp["telegram_chat_id"],
                    store=store,
                    chat=chat,
                )
            except Exception:
                logger.exception("Error summarizing employee %s", emp["name"])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Create `infrastructure/systemd/weekly-summary.service`**

```ini
[Unit]
Description=Secretarios Virtuales — Weekly Summary Job
After=network.target postgresql.service

[Service]
Type=oneshot
User=sv
WorkingDirectory=/opt/secretarios-virtuales
EnvironmentFile=/opt/secretarios-virtuales/.env
ExecStart=/opt/secretarios-virtuales/.venv/bin/python -m jobs.weekly_summary
```

- [ ] **Step 3: Create `infrastructure/systemd/weekly-summary.timer`**

```ini
[Unit]
Description=Run weekly summary every Monday at 08:00

[Timer]
OnCalendar=Mon *-*-* 08:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Commit**

```bash
git add jobs/weekly_summary.py infrastructure/systemd/weekly-summary.service infrastructure/systemd/weekly-summary.timer
git commit -m "feat(jobs): add weekly summary job with systemd timer (Mon 08:00)"
```

---

## Task 10: Morning email digest systemd job

**Files:**
- Create: `jobs/morning_digest.py`
- Create: `infrastructure/systemd/morning-digest.service`
- Create: `infrastructure/systemd/morning-digest.timer`

- [ ] **Step 1: Create `jobs/morning_digest.py`**

```python
"""Morning email digest job — runs daily at 08:00 via systemd timer.

For each active employee with email configured, fetches unread emails
from the last 24h, summarizes them with LLM, and sends digest via Telegram.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
from dotenv import load_dotenv

from shared.crypto import CredentialStore
from shared.email.client import EmailClient
from shared.email.models import EmailConfig
from shared.llm.chat import ChatClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_DIGEST_SYSTEM = (
    "Eres un asistente que resume emails en español de forma concisa. "
    "Dado una lista de emails recientes, genera un resumen breve de máximo 250 palabras: "
    "cuántos emails hay, los temas principales, y cuáles parecen urgentes o importantes. "
    "Usa formato amigable con emojis donde corresponda."
)


async def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


async def digest_employee(
    conn: asyncpg.Connection,
    employee_id,
    employee_name: str,
    chat_id: str,
    store: CredentialStore,
    chat: ChatClient,
) -> None:
    # Get email credentials
    email_imap_enc = await conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id = $1 AND service_type = 'email_imap'",
        employee_id,
    )
    email_smtp_enc = await conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id = $1 AND service_type = 'email_smtp'",
        employee_id,
    )
    if not email_imap_enc or not email_smtp_enc:
        logger.debug("No email configured for employee %s", employee_name)
        return

    imap = json.loads(store.decrypt(email_imap_enc))
    smtp = json.loads(store.decrypt(email_smtp_enc))
    email_client = EmailClient(
        EmailConfig(
            imap_host=imap["host"],
            imap_port=int(imap["port"]),
            smtp_host=smtp["host"],
            smtp_port=int(smtp["port"]),
            username=imap["username"],
            password=imap["password"],
        )
    )

    try:
        messages = await asyncio.wait_for(
            email_client.fetch_inbox(limit=20, since_days=1),
            timeout=30.0,
        )
    except Exception as e:
        logger.warning("Failed to fetch email for %s: %s", employee_name, e)
        return

    if not messages:
        logger.info("No new emails for %s", employee_name)
        return

    email_lines = []
    for m in messages:
        snippet = m.body[:200].replace("\n", " ") if m.body else ""
        email_lines.append(f"De: {m.sender}\nAsunto: {m.subject}\n{snippet}")

    user_content = f"Emails recibidos en las últimas 24h ({len(messages)} total):\n\n" + "\n\n---\n\n".join(email_lines)

    summary, _ = await chat.complete_with_tools(
        messages=[{"role": "user", "content": user_content}],
        system=_DIGEST_SYSTEM,
        tools=[],
    )

    # Get bot token
    enc_token = await conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id = $1 AND service_type = 'telegram_token'",
        employee_id,
    )
    if not enc_token:
        return

    bot_token = store.decrypt(enc_token)
    text = f"📬 *Digest matutino — {datetime.now().strftime('%d/%m/%Y')}*\n\n{summary}"
    await _send_telegram(bot_token, chat_id, text)
    logger.info("Morning digest sent to %s", employee_name)


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]  # superuser
    fernet_key = os.environ["FERNET_KEY"].encode()
    store = CredentialStore(fernet_key)
    chat = ChatClient(
        base_url=os.environ["VLLM_CHAT_URL"],
        api_key=os.environ["VLLM_API_KEY"],
        model=os.environ["CHAT_MODEL"],
    )

    conn = await asyncpg.connect(dsn)
    try:
        employees = await conn.fetch(
            "SELECT id, name, telegram_chat_id FROM employees "
            "WHERE is_active = true AND is_orchestrator = false AND telegram_chat_id IS NOT NULL"
        )
        for emp in employees:
            try:
                await digest_employee(
                    conn=conn,
                    employee_id=emp["id"],
                    employee_name=emp["name"],
                    chat_id=emp["telegram_chat_id"],
                    store=store,
                    chat=chat,
                )
            except Exception:
                logger.exception("Error digesting email for employee %s", emp["name"])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Create `infrastructure/systemd/morning-digest.service`**

```ini
[Unit]
Description=Secretarios Virtuales — Morning Email Digest Job
After=network.target postgresql.service

[Service]
Type=oneshot
User=sv
WorkingDirectory=/opt/secretarios-virtuales
EnvironmentFile=/opt/secretarios-virtuales/.env
ExecStart=/opt/secretarios-virtuales/.venv/bin/python -m jobs.morning_digest
```

- [ ] **Step 3: Create `infrastructure/systemd/morning-digest.timer`**

```ini
[Unit]
Description=Run morning email digest every day at 08:00

[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Commit**

```bash
git add jobs/morning_digest.py infrastructure/systemd/morning-digest.service infrastructure/systemd/morning-digest.timer
git commit -m "feat(jobs): add morning email digest job with systemd timer (daily 08:00)"
```

---

## Task 11: Update system prompt to mention new capabilities

**Files:**
- Modify: `secretary/agent.py`

- [ ] **Step 1: Update `_build_tool_system()` in `secretary/agent.py`**

Replace the `_build_tool_system` function with:

```python
def _build_tool_system(employee_name: str, profile: dict | None, cal_context: str = "") -> str:
    from datetime import datetime as _dt
    bot_name = (profile or {}).get("bot_name") or employee_name
    preferred_name = (profile or {}).get("preferred_name") or employee_name
    language = (profile or {}).get("language") or "español"
    tool_names = ", ".join(t["function"]["name"] for t in TOOL_DEFINITIONS)
    now_str = _dt.now().strftime("%A %d/%m/%Y %H:%M")
    base = (
        f"Eres {bot_name}, asistente personal de {preferred_name}. "
        f"Responde en {language}. "
        f"Tienes acceso a herramientas: {tool_names}. "
        "Úsalas para completar las tareas. Ejecuta en silencio y da un resumen al final. "
        "NUNCA uses chino ni muestres razonamiento interno.\n"
        f"Fecha y hora actual: {now_str}\n\n"
        "INSTRUCCIONES ESPECIALES:\n"
        "- Cuando el usuario mencione información personal importante (médico, coche, domicilio, "
        "preferencias, contactos clave), úsala fact_save para guardarla automáticamente.\n"
        "- Antes de responder preguntas sobre el usuario, consulta fact_list para recordar datos previos.\n"
        "- Para tareas y pendientes del usuario, usa task_create/task_list/task_done.\n"
        "- Para búsquedas web, usa web_search.\n"
        "- Para transcribir vídeos o podcasts, usa youtube_transcribe.\n"
        "- Si el usuario pregunta por lugares cercanos, usa nearby_search (requiere ubicación GPS previa)."
    )
    if cal_context:
        base = f"{base}\n\n{cal_context}"
    return base
```

- [ ] **Step 2: Commit**

```bash
git add secretary/agent.py
git commit -m "feat(secretary): update system prompt with facts/tasks/search/location guidance"
```

---

## Verification

### Syntax check all new files
```bash
python -m py_compile shared/facts/client.py shared/tasks/client.py shared/search/duckduckgo.py shared/location/nominatim.py shared/youtube/transcriber.py secretary/handlers/location.py jobs/weekly_summary.py jobs/morning_digest.py
```
Expected: no output (no errors).

### Install systemd timers on server
```bash
sudo cp infrastructure/systemd/weekly-summary.{service,timer} /etc/systemd/system/
sudo cp infrastructure/systemd/morning-digest.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable weekly-summary.timer morning-digest.timer
sudo systemctl start weekly-summary.timer morning-digest.timer
sudo systemctl list-timers --all | grep -E "weekly|digest"
```

### Test fact_save / fact_list manually
```bash
python -c "
import asyncio
from shared.facts.client import FactsClient
from shared.db.pool import DatabasePool
from uuid import UUID
import os
from dotenv import load_dotenv
load_dotenv()
# Requires real DB connection
print('imports ok')
"
```

### Test DuckDuckGo search
```bash
python -c "
import asyncio
from shared.search.duckduckgo import DuckDuckGoClient
result = asyncio.run(DuckDuckGoClient().search('tiempo Valencia hoy'))
print(result[:300])
"
```
Expected: search results printed.

### Test YouTube transcriber (requires yt-dlp installed)
```bash
pip install yt-dlp
python -c "from shared.youtube.transcriber import YouTubeTranscriber; print('ok')"
```
