# Agent Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir ejecución real (bash local, SSH remoto, ficheros) al orquestador y secretarios con permisos, usando OpenAI function calling con Qwen vía vLLM.

**Architecture:** El LLM decide qué herramienta usar devolviendo `tool_calls` JSON. `ChatClient.complete_with_tools()` devuelve esos tool_calls. El agente ejecuta cada herramienta vía `ToolExecutor` y devuelve los resultados al LLM en un bucle (máx. 10 iter). Comandos destructivos sin `/superuser` activo piden confirmación al usuario antes de ejecutar.

**Tech Stack:** Python 3.11+, asyncssh 2.14+, asyncio subprocess, OpenAI client (vLLM), Fernet (credenciales SSH cifradas), asyncpg (DB).

---

## File Map

| Fichero | Acción | Qué hace |
|---------|--------|----------|
| `shared/tools/__init__.py` | Crear | Exports |
| `shared/tools/safety.py` | Crear | `is_destructive(name, args) -> bool` |
| `shared/tools/definitions.py` | Crear | `TOOL_DEFINITIONS: list[dict]` — schemas OpenAI |
| `shared/tools/ssh_store.py` | Crear | `SSHStore` — save/load/list conexiones SSH cifradas |
| `shared/tools/executor.py` | Crear | `ToolExecutor` — despacha las 7 herramientas |
| `shared/llm/chat.py` | Modificar | Añade `ToolCall` dataclass + `complete_with_tools()` |
| `shared/db/repository.py` | Modificar | Añade `get_credentials_by_prefix()` |
| `secretary/agent.py` | Modificar | Bucle de herramientas, `/superuser`, confirmación |
| `orchestrator/admin.py` | Modificar | `create_secretary(tools_enabled=False)` |
| `orchestrator/parser.py` | Modificar | `CreateSecretaryCommand.tools_enabled`, detecta "con herramientas" |
| `orchestrator/agent.py` | Modificar | Crea `ToolExecutor` siempre activo |
| `secretary/__main__.py` | Modificar | Lee `tools_enabled`, pasa `ToolExecutor` al agente |
| `pyproject.toml` | Modificar | Añade `asyncssh>=2.14,<3` |
| `tests/tools/test_safety.py` | Crear | Tests de `is_destructive` |
| `tests/tools/test_executor.py` | Crear | Tests de `ToolExecutor` (mocks) |
| `tests/orchestrator/test_parser.py` | Modificar | Tests del flag `tools_enabled` |

---

## Task 1: `shared/tools/safety.py` — detección de destructivos

**Files:**
- Create: `shared/tools/safety.py`
- Create: `tests/tools/__init__.py`
- Create: `tests/tools/test_safety.py`

- [ ] **Step 1: Crear test**

```python
# tests/tools/test_safety.py
import pytest
from shared.tools.safety import is_destructive


@pytest.mark.parametrize("name,args,expected", [
    ("bash", {"command": "ls -la"}, False),
    ("bash", {"command": "rm -rf /tmp/test"}, True),
    ("bash", {"command": "rmdir /tmp/empty"}, True),
    ("bash", {"command": "kill 1234"}, True),
    ("bash", {"command": "shutdown now"}, True),
    ("bash", {"command": "DROP TABLE users"}, True),
    ("bash", {"command": "DELETE FROM logs"}, True),
    ("bash", {"command": "TRUNCATE sessions"}, True),
    ("bash", {"command": "echo hola"}, False),
    ("bash", {"command": "cat /etc/hosts"}, False),
    ("ssh_exec", {"name": "srv", "command": "rm -rf /var"}, True),
    ("ssh_exec", {"name": "srv", "command": "df -h"}, False),
    ("write_file", {"path": "/etc/passwd", "content": "x"}, False),  # write is not destructive
    ("read_file", {"path": "/etc/hosts"}, False),
])
def test_is_destructive(name, args, expected):
    assert is_destructive(name, args) == expected
```

- [ ] **Step 2: Ejecutar test — verificar que falla**

```bash
cd ~/secretarios-virtuales && python -m pytest tests/tools/test_safety.py -v
```
Expected: `ModuleNotFoundError: No module named 'shared.tools'`

- [ ] **Step 3: Crear `tests/tools/__init__.py`**

```python
```
(vacío)

- [ ] **Step 4: Implementar `shared/tools/safety.py`**

```python
_DESTRUCTIVE_PATTERNS = (
    r"\brm\b",
    r"\brmdir\b",
    r"\bunlink\b",
    r"\bshred\b",
    r"\bwipefs\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bkill\b",
    r"\bpkill\b",
    r"\bkillall\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\bpasswd\b",
    r"\buserdel\b",
    r"\bgroupdel\b",
    r"DROP\s+TABLE",
    r"DROP\s+DATABASE",
    r"DELETE\s+FROM",
    r"\bTRUNCATE\b",
)

import re

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _DESTRUCTIVE_PATTERNS]


def is_destructive(tool_name: str, args: dict) -> bool:
    """Return True if the tool call looks destructive and needs confirmation."""
    command = ""
    if tool_name in ("bash", "ssh_exec"):
        command = args.get("command", "")
    if not command:
        return False
    return any(pat.search(command) for pat in _COMPILED)
```

- [ ] **Step 5: Ejecutar test — verificar que pasa**

```bash
python -m pytest tests/tools/test_safety.py -v
```
Expected: todos PASSED

- [ ] **Step 6: Commit**

```bash
git add shared/tools/ tests/tools/
git commit -m "feat: add tool safety detection for destructive commands"
```

---

## Task 2: `shared/tools/definitions.py` — schemas OpenAI

**Files:**
- Create: `shared/tools/definitions.py`

- [ ] **Step 1: Crear `shared/tools/definitions.py`**

```python
TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Ejecuta un comando bash en el servidor local donde corre el agente. Úsalo para operaciones del sistema, instalar paquetes, ver logs, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando bash a ejecutar"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_exec",
            "description": "Ejecuta un comando en una máquina remota usando una conexión SSH guardada por nombre.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre de la conexión SSH guardada"},
                    "command": {"type": "string", "description": "Comando a ejecutar en la máquina remota"},
                },
                "required": ["name", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_save",
            "description": "Guarda una nueva conexión SSH cifrada para uso futuro. Requiere siempre un nombre identificador.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre identificador para esta conexión (ej: servidor-web)"},
                    "host": {"type": "string", "description": "IP o hostname del servidor"},
                    "user": {"type": "string", "description": "Usuario SSH"},
                    "password": {"type": "string", "description": "Contraseña SSH (opcional si se usa ssh_key)"},
                    "ssh_key": {"type": "string", "description": "Contenido de la clave privada SSH (opcional)"},
                    "port": {"type": "integer", "description": "Puerto SSH (por defecto 22)"},
                },
                "required": ["name", "host", "user"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ssh_list",
            "description": "Lista todas las conexiones SSH guardadas con su nombre y host (sin mostrar contraseñas).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lee el contenido de un fichero en el servidor local.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta o relativa del fichero"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Crea o sobreescribe un fichero con el contenido dado. Crea directorios intermedios si no existen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del fichero a crear/sobreescribir"},
                    "content": {"type": "string", "description": "Contenido del fichero"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "Lista el contenido de un directorio en el servidor local.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del directorio"},
                },
                "required": ["path"],
            },
        },
    },
]
```

- [ ] **Step 2: Commit**

```bash
git add shared/tools/definitions.py
git commit -m "feat: add OpenAI tool definitions for agent tools"
```

---

## Task 3: `shared/db/repository.py` — añadir `get_credentials_by_prefix`

**Files:**
- Modify: `shared/db/repository.py` (añadir método al final)

- [ ] **Step 1: Añadir método al final de `Repository`**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add shared/db/repository.py
git commit -m "feat: add get_credentials_by_prefix to Repository"
```

---

## Task 4: `shared/tools/ssh_store.py` — gestión de conexiones SSH

**Files:**
- Create: `shared/tools/ssh_store.py`

- [ ] **Step 1: Crear `shared/tools/ssh_store.py`**

```python
from __future__ import annotations

import json
from uuid import UUID

from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository

_PREFIX = "ssh:"


class SSHStore:
    def __init__(self, pool: DatabasePool, employee_id: UUID, store: CredentialStore) -> None:
        self._pool = pool
        self._employee_id = employee_id
        self._store = store

    async def save(
        self,
        name: str,
        host: str,
        user: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 22,
    ) -> None:
        data = {"host": host, "user": user, "port": port}
        if password:
            data["password"] = password
        if ssh_key:
            data["ssh_key"] = ssh_key
        encrypted = self._store.encrypt(json.dumps(data))
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            await repo.save_credential(f"{_PREFIX}{name}", encrypted)

    async def load(self, name: str) -> dict:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            raw = await repo.get_credential(f"{_PREFIX}{name}")
        if raw is None:
            raise KeyError(f"No existe conexión SSH con nombre '{name}'. Usa ssh_list para ver las disponibles.")
        return json.loads(self._store.decrypt(raw))

    async def list_all(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            rows = await repo.get_credentials_by_prefix(_PREFIX)
        result = []
        for service_type, encrypted in rows:
            name = service_type[len(_PREFIX):]
            try:
                data = json.loads(self._store.decrypt(encrypted))
                result.append({"name": name, "host": data.get("host", "?"), "port": data.get("port", 22), "user": data.get("user", "?")})
            except Exception:
                pass
        return result
```

- [ ] **Step 2: Commit**

```bash
git add shared/tools/ssh_store.py
git commit -m "feat: add SSHStore for encrypted SSH connection management"
```

---

## Task 5: `shared/tools/executor.py` — ToolExecutor

**Files:**
- Create: `shared/tools/executor.py`
- Create: `tests/tools/test_executor.py`

- [ ] **Step 1: Crear test**

```python
# tests/tools/test_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from shared.tools.executor import ToolExecutor


@pytest.fixture
def mock_ssh_store():
    store = AsyncMock()
    store.list_all.return_value = [{"name": "srv", "host": "1.2.3.4", "port": 22, "user": "admin"}]
    store.save = AsyncMock()
    return store


@pytest.fixture
def executor(mock_ssh_store):
    return ToolExecutor(ssh_store=mock_ssh_store)


async def test_bash_echo(executor):
    result = await executor.run("bash", {"command": "echo hello"})
    assert "hello" in result


async def test_list_dir(executor, tmp_path):
    (tmp_path / "file.txt").write_text("x")
    result = await executor.run("list_dir", {"path": str(tmp_path)})
    assert "file.txt" in result


async def test_write_and_read_file(executor, tmp_path):
    path = str(tmp_path / "test.txt")
    await executor.run("write_file", {"path": path, "content": "hola"})
    result = await executor.run("read_file", {"path": path})
    assert "hola" in result


async def test_ssh_list(executor, mock_ssh_store):
    result = await executor.run("ssh_list", {})
    assert "srv" in result
    assert "1.2.3.4" in result


async def test_ssh_save(executor, mock_ssh_store):
    await executor.run("ssh_save", {"name": "nuevo", "host": "5.6.7.8", "user": "root", "password": "pw"})
    mock_ssh_store.save.assert_called_once_with(
        name="nuevo", host="5.6.7.8", user="root", password="pw", ssh_key=None, port=22
    )


async def test_unknown_tool(executor):
    result = await executor.run("nonexistent", {})
    assert "desconocida" in result.lower()
```

- [ ] **Step 2: Ejecutar test — verificar que falla**

```bash
python -m pytest tests/tools/test_executor.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implementar `shared/tools/executor.py`**

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from shared.tools.ssh_store import SSHStore

_MAX_OUTPUT = 4000
_MAX_FILE = 8000


class ToolExecutor:
    def __init__(self, ssh_store: SSHStore) -> None:
        self._ssh = ssh_store

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
            return f"Herramienta desconocida: {name}"
        except KeyError as e:
            return f"Error: falta el parámetro {e}"
        except Exception as e:
            return f"Error ejecutando {name}: {e}"

    async def _bash(self, command: str) -> str:
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
            out = out[:_MAX_OUTPUT] + f"\n... [truncado]"
        return out or "(sin salida)"

    async def _ssh_save(self, args: dict) -> str:
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
                size = e.stat().st_size
                lines.append(f"📄 {e.name} ({size} bytes)")
        return "\n".join(lines) if lines else "(directorio vacío)"
```

- [ ] **Step 4: Ejecutar test — verificar que pasa**

```bash
python -m pytest tests/tools/test_executor.py -v
```
Expected: todos PASSED

- [ ] **Step 5: Commit**

```bash
git add shared/tools/executor.py tests/tools/test_executor.py
git commit -m "feat: implement ToolExecutor with bash, SSH, and file operations"
```

---

## Task 6: `shared/tools/__init__.py` + `pyproject.toml`

**Files:**
- Create: `shared/tools/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Crear `shared/tools/__init__.py`**

```python
from shared.tools.definitions import TOOL_DEFINITIONS
from shared.tools.executor import ToolExecutor
from shared.tools.safety import is_destructive
from shared.tools.ssh_store import SSHStore

__all__ = ["TOOL_DEFINITIONS", "ToolExecutor", "SSHStore", "is_destructive"]
```

- [ ] **Step 2: Añadir asyncssh a `pyproject.toml`**

En la sección `dependencies`, añadir después de `"pypdf>=4.0",`:
```toml
    "asyncssh>=2.14,<3",
```

- [ ] **Step 3: Reinstalar dependencias**

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
```
Expected: `asyncssh` instalado sin errores.

- [ ] **Step 4: Commit**

```bash
git add shared/tools/__init__.py pyproject.toml
git commit -m "feat: expose shared/tools package, add asyncssh dependency"
```

---

## Task 7: `shared/llm/chat.py` — `ToolCall` + `complete_with_tools`

**Files:**
- Modify: `shared/llm/chat.py`

El fichero actual (`shared/llm/chat.py`) tiene solo `ChatClient.complete()`. Hay que añadir `ToolCall` y `complete_with_tools()` sin romper la API existente.

- [ ] **Step 1: Reemplazar `shared/llm/chat.py` con la versión extendida**

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from openai import AsyncOpenAI

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


class ChatClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def complete(
        self,
        messages: list[dict],
        system: str | None = None,
    ) -> str:
        all_messages: list[dict] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,  # type: ignore[arg-type]
        )
        content = response.choices[0].message.content or ""
        return _THINK_RE.sub("", content).strip()

    async def complete_with_tools(
        self,
        messages: list[dict],
        system: str | None,
        tools: list[dict],
    ) -> tuple[str | None, list[ToolCall]]:
        """Single LLM call with tool support.

        Returns (text, []) when the model gives a final answer.
        Returns (None, tool_calls) when the model wants to call tools.
        """
        all_messages: list[dict] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    args=json.loads(tc.function.arguments),
                )
                for tc in msg.tool_calls
            ]
            return None, calls

        content = msg.content or ""
        return _THINK_RE.sub("", content).strip(), []
```

- [ ] **Step 2: Verificar que los tests existentes siguen pasando**

```bash
python -m pytest tests/ -v --ignore=tests/tools
```
Expected: todos los tests previos siguen en PASSED.

- [ ] **Step 3: Commit**

```bash
git add shared/llm/chat.py
git commit -m "feat: add ToolCall dataclass and complete_with_tools to ChatClient"
```

---

## Task 8: `secretary/agent.py` — bucle de herramientas, `/superuser`, confirmación

**Files:**
- Modify: `secretary/agent.py`

Este es el cambio más grande. Se añaden:
- `_executor: ToolExecutor | None` (None = sin herramientas)
- `_superuser_until: datetime | None`
- `_pending_*` fields para confirmaciones pausadas
- `_is_superuser()`, `_reset_superuser_timer()` helpers
- `_run_tool_loop()` método principal del bucle
- Manejo de `/superuser` y confirmaciones en `_handle_text`

- [ ] **Step 1: Añadir imports al inicio de `secretary/agent.py`**

Añadir al bloque de imports existente:
```python
import json
from datetime import datetime, timedelta

from shared.llm.chat import ToolCall
from shared.tools import TOOL_DEFINITIONS, ToolExecutor, is_destructive
```

- [ ] **Step 2: Extender `__init__` de `SecretaryAgent`**

El `__init__` existente recibe estos params: `employee_id, employee_name, allowed_chat_id, db_pool, chat, embed, whisper, documents_dir, fernet_key, redis_url, vision=None`. Añadir `executor: ToolExecutor | None = None`:

```python
    def __init__(
        self,
        employee_id: UUID,
        employee_name: str,
        allowed_chat_id: str,
        db_pool: DatabasePool,
        chat: ChatClient,
        embed: EmbeddingClient,
        whisper: WhisperClient,
        documents_dir: Path,
        fernet_key: bytes,
        redis_url: str,
        vision: ChatClient | None = None,
        executor: ToolExecutor | None = None,
    ) -> None:
        # ... (mantener todo el código existente del __init__) ...
        self._executor = executor
        self._superuser_until: datetime | None = None
        self._pending_tool: ToolCall | None = None
        self._pending_messages: list[dict] | None = None
        self._pending_used_tools: list[str] | None = None
        self._pending_system: str | None = None
        self._pending_original_msg: str = ""
```

- [ ] **Step 3: Añadir helpers después de `_check_email_configured`**

```python
    def _is_superuser(self) -> bool:
        if self._superuser_until is None:
            return False
        return datetime.now() < self._superuser_until

    def _reset_superuser_timer(self) -> None:
        if self._superuser_until is not None:
            self._superuser_until = datetime.now() + timedelta(minutes=30)
```

- [ ] **Step 4: Añadir `_run_tool_loop` después de los helpers**

```python
    async def _run_tool_loop(
        self,
        messages: list[dict],
        system: str,
        used_tools: list[str],
    ) -> str:
        """Runs the tool-calling loop. Returns the final text response."""
        for _ in range(10):
            text, tool_calls = await self._chat.complete_with_tools(
                messages, system, TOOL_DEFINITIONS
            )
            if not tool_calls:
                suffix = (
                    f"\n\n_Herramientas usadas: {', '.join(used_tools)}_"
                    if used_tools
                    else ""
                )
                return (text or "") + suffix

            # Append assistant message with tool_calls to history
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args),
                        },
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                if is_destructive(tc.name, tc.args) and not self._is_superuser():
                    self._pending_tool = tc
                    self._pending_messages = messages
                    self._pending_used_tools = used_tools
                    self._pending_system = system
                    cmd_str = tc.args.get("command", json.dumps(tc.args))
                    return f"⚠️ Voy a ejecutar:\n`{cmd_str}`\n¿Confirmas? (sí/no)"

                result = await self._executor.run(tc.name, tc.args)  # type: ignore[union-attr]
                used_tools.append(tc.name)
                self._reset_superuser_timer()
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return "⚠️ Límite de 10 iteraciones alcanzado."
```

- [ ] **Step 5: Actualizar `_handle_text` — añadir `/superuser` y confirmaciones**

En el método `_handle_text`, después de la comprobación de autorización y ANTES del bloque del wizard de email, añadir:

```python
        # Superuser activation
        if msg == "/superuser":
            self._superuser_until = datetime.now() + timedelta(minutes=30)
            await update.message.reply_text(  # type: ignore[union-attr]
                "🔓 Modo superusuario activo durante 30 minutos de inactividad.\n"
                "Los comandos destructivos se ejecutarán sin confirmación."
            )
            return

        # Pending destructive confirmation
        if self._pending_tool is not None:
            tc = self._pending_tool
            if msg.lower().strip() in ("sí", "si", "s", "yes", "y"):
                self._pending_tool = None
                result = await self._executor.run(tc.name, tc.args)  # type: ignore[union-attr]
                self._pending_used_tools.append(tc.name)  # type: ignore[union-attr]
                self._reset_superuser_timer()
                self._pending_messages.append({  # type: ignore[union-attr]
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
                messages = self._pending_messages
                system = self._pending_system
                used_tools = self._pending_used_tools
                original_msg = self._pending_original_msg
                self._pending_messages = None
                self._pending_system = None
                self._pending_used_tools = None
                self._pending_original_msg = ""
                response = await self._run_tool_loop(messages, system, used_tools)  # type: ignore[arg-type]
                async with self._pool.acquire() as conn:
                    repo = Repository(conn, self._employee_id)
                    memory = MemoryManager(repo=repo, embed_client=self._embed)
                    await memory.save_turn(original_msg, response)
                await update.message.reply_text(response, parse_mode="Markdown")  # type: ignore[union-attr]
            else:
                self._pending_tool = None
                self._pending_messages = None
                self._pending_system = None
                self._pending_used_tools = None
                self._pending_original_msg = ""
                await update.message.reply_text("❌ Comando cancelado.")  # type: ignore[union-attr]
            return
```

- [ ] **Step 6: Actualizar el bloque final de `_handle_text` — añadir rama de herramientas**

El bloque actual al final de `_handle_text` es:
```python
        email_configured = await self._check_email_configured()
        if self._profile is None:
            self._profile = await self._load_profile()
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            response = await handle_text(...)
            await memory.save_turn(msg, response)
        await update.message.reply_text(response)
```

Reemplazarlo con:
```python
        email_configured = await self._check_email_configured()
        if self._profile is None:
            self._profile = await self._load_profile()

        if self._executor is not None:
            system = _build_tool_system(self._employee_name, self._profile)
            self._pending_original_msg = msg
            response = await self._run_tool_loop(
                messages=[{"role": "user", "content": msg}],
                system=system,
                used_tools=[],
            )
            async with self._pool.acquire() as conn:
                repo = Repository(conn, self._employee_id)
                memory = MemoryManager(repo=repo, embed_client=self._embed)
                await memory.save_turn(msg, response)
            await update.message.reply_text(response, parse_mode="Markdown")  # type: ignore[union-attr]
            return

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            response = await handle_text(
                message=msg,
                employee_name=self._employee_name,
                memory=memory,
                chat=self._chat,
                email_configured=email_configured,
                profile=self._profile,
            )
            await memory.save_turn(msg, response)
        await update.message.reply_text(response)  # type: ignore[union-attr]
```

- [ ] **Step 7: Añadir `_build_tool_system` al final de `secretary/agent.py` (fuera de la clase)**

```python
def _build_tool_system(employee_name: str, profile: dict | None) -> str:
    bot_name = (profile or {}).get("bot_name") or employee_name
    preferred_name = (profile or {}).get("preferred_name") or employee_name
    language = (profile or {}).get("language") or "español"
    from shared.tools.definitions import TOOL_DEFINITIONS
    tool_names = ", ".join(
        t["function"]["name"] for t in TOOL_DEFINITIONS
    )
    return (
        f"Eres {bot_name}, asistente técnico personal de {preferred_name}. "
        f"Responde en {language}. "
        f"Tienes acceso a herramientas de sistema: {tool_names}. "
        "Úsalas para completar las tareas. Ejecuta en silencio y da un resumen al final. "
        "NUNCA uses chino ni muestres razonamiento interno."
    )
```

- [ ] **Step 8: Verificar sintaxis**

```bash
python -c "from secretary.agent import SecretaryAgent; print('OK')"
```
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add secretary/agent.py
git commit -m "feat: add tool loop, /superuser mode, and destructive confirmation to SecretaryAgent"
```

---

## Task 9: `orchestrator/parser.py` + `orchestrator/admin.py` — `tools_enabled`

**Files:**
- Modify: `orchestrator/parser.py`
- Modify: `orchestrator/admin.py`
- Modify: `tests/orchestrator/test_parser.py`

- [ ] **Step 1: Añadir test en `tests/orchestrator/test_parser.py`**

Añadir al final del fichero:
```python
def test_parse_create_with_tools():
    token = "123456789:ABCDefghIJKLmnopQRSTuvwxYZ1234567890ab"
    cmd = parse_command(f"crea secretario para Carlos con herramientas, token: {token}, chatid: 111222333")
    assert isinstance(cmd, CreateSecretaryCommand)
    assert cmd.name == "Carlos"
    assert cmd.tools_enabled is True


def test_parse_create_without_tools_flag():
    token = "123456789:ABCDefghIJKLmnopQRSTuvwxYZ1234567890ab"
    cmd = parse_command(f"crea secretario para Laura, token: {token}, chatid: 444555666")
    assert isinstance(cmd, CreateSecretaryCommand)
    assert cmd.tools_enabled is False
```

- [ ] **Step 2: Ejecutar test — verificar que falla**

```bash
python -m pytest tests/orchestrator/test_parser.py::test_parse_create_with_tools -v
```
Expected: `FAILED` con `AttributeError`

- [ ] **Step 3: Actualizar `orchestrator/parser.py`**

Cambiar `CreateSecretaryCommand` y `parse_command`:
```python
@dataclass
class CreateSecretaryCommand:
    name: str
    telegram_token: str
    telegram_chat_id: str
    tools_enabled: bool = False
```

En `parse_command`, en el bloque de `_CREATE_PATTERN`:
```python
    if m := _CREATE_PATTERN.search(text):
        token_m = _TOKEN_RE.search(text)
        text_no_token = _TOKEN_RE.sub("", text)
        chatid_m = re.search(r"(?<!\d)(\d{5,15})(?!\d)", text_no_token)

        token = token_m.group(0) if token_m else ""
        chat_id = chatid_m.group(1) if chatid_m else ""

        if not token or not chat_id:
            raise ValueError(
                "Para crear un secretario necesito el token del bot y el chat_id.\n"
                "Ejemplo: crea un secretario para María, token 123456:ABC... chatid 987654321"
            )
        tools_enabled = bool(re.search(r"con\s+herramientas", text, re.IGNORECASE))
        return CreateSecretaryCommand(
            name=m.group("name"),
            telegram_token=token,
            telegram_chat_id=chat_id,
            tools_enabled=tools_enabled,
        )
```

- [ ] **Step 4: Actualizar `orchestrator/admin.py` — añadir `tools_enabled` a `create_secretary`**

Cambiar la firma y añadir el guardado del flag:
```python
    async def create_secretary(
        self,
        name: str,
        telegram_token: str,
        telegram_chat_id: str,
        tools_enabled: bool = False,
    ) -> UUID:
```

Después de insertar el `telegram_token` en credentials (dentro del bloque `async with conn.transaction()`), añadir:
```python
                if tools_enabled:
                    await conn.execute(
                        """
                        INSERT INTO credentials (employee_id, service_type, encrypted)
                        VALUES ($1, 'tools_enabled', $2)
                        """,
                        employee_id,
                        self._store.encrypt("true"),
                    )
```

- [ ] **Step 5: Actualizar `orchestrator/agent.py` — pasar `tools_enabled` al crear secretario**

En `_handle_admin_command`, bloque `isinstance(command, CreateSecretaryCommand)`:
```python
            try:
                employee_id = await self._admin.create_secretary(
                    name=command.name,
                    telegram_token=command.telegram_token,
                    telegram_chat_id=command.telegram_chat_id,
                    tools_enabled=command.tools_enabled,
                )
            except ValueError as exc:
                await update.message.reply_text(str(exc))
                return True
            tools_note = " (con herramientas)" if command.tools_enabled else ""
            await update.message.reply_text(
                f"✅ Secretario {command.name} creado{tools_note} (id: {employee_id}).\n"
                "El supervisor lo arrancará en breve."
            )
```

- [ ] **Step 6: Ejecutar tests**

```bash
python -m pytest tests/orchestrator/ -v
```
Expected: todos PASSED

- [ ] **Step 7: Commit**

```bash
git add orchestrator/parser.py orchestrator/admin.py orchestrator/agent.py tests/orchestrator/test_parser.py
git commit -m "feat: add tools_enabled flag to CreateSecretaryCommand and admin.create_secretary"
```

---

## Task 10: `secretary/__main__.py` — leer `tools_enabled` y pasar `ToolExecutor`

**Files:**
- Modify: `secretary/__main__.py`

- [ ] **Step 1: Actualizar `secretary/__main__.py`**

Añadir imports al inicio:
```python
from shared.tools import ToolExecutor, SSHStore
from shared.db.pool import DatabasePool
```

En la función `main`, después de obtener `fernet_key` y `store`, antes de crear `pool`, añadir la lectura de `tools_enabled`:

```python
    # Check tools_enabled
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
```

Al crear `SecretaryAgent`, añadir el executor si corresponde:

```python
    pool = DatabasePool(app_dsn, employee_id)
    await pool.connect()

    executor: ToolExecutor | None = None
    if tools_enabled:
        ssh_store = SSHStore(pool=pool, employee_id=employee_id, store=store)
        executor = ToolExecutor(ssh_store=ssh_store)

    agent = SecretaryAgent(
        employee_id=employee_id,
        employee_name=employee_name,
        allowed_chat_id=telegram_chat_id,
        db_pool=pool,
        chat=ChatClient(...),
        embed=EmbeddingClient(...),
        whisper=WhisperClient(...),
        documents_dir=Path(os.environ.get("DOCUMENTS_DIR", "./data/documents")),
        fernet_key=fernet_key,
        redis_url=os.environ["REDIS_URL"],
        executor=executor,
    )
```

- [ ] **Step 2: Verificar sintaxis**

```bash
python -c "import secretary.__main__; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add secretary/__main__.py
git commit -m "feat: read tools_enabled from DB and pass ToolExecutor to SecretaryAgent on startup"
```

---

## Task 11: `orchestrator/__main__.py` — ToolExecutor siempre activo

**Files:**
- Modify: `orchestrator/__main__.py`

- [ ] **Step 1: Leer `orchestrator/__main__.py`**

```bash
cat orchestrator/__main__.py
```

- [ ] **Step 2: Actualizar para crear y pasar `ToolExecutor` al orquestador**

Añadir imports:
```python
from shared.tools import ToolExecutor, SSHStore
```

Antes de crear `OrchestratorAgent`, crear el executor:
```python
    ssh_store = SSHStore(pool=pool, employee_id=employee_id, store=store)
    executor = ToolExecutor(ssh_store=ssh_store)
```

Pasar al constructor de `OrchestratorAgent`:
```python
    agent = OrchestratorAgent(
        ...,
        executor=executor,
    )
```

- [ ] **Step 3: Verificar que `OrchestratorAgent.__init__` acepta `executor`**

`OrchestratorAgent` hereda de `SecretaryAgent`. `SecretaryAgent.__init__` ya acepta `executor` tras el Task 8. Solo hay que pasar el kwarg en `super().__init__()` dentro de `OrchestratorAgent.__init__`:

En `orchestrator/agent.py`, en el `super().__init__()` call, añadir:
```python
        super().__init__(
            employee_id=employee_id,
            employee_name=employee_name,
            allowed_chat_id=allowed_chat_id,
            db_pool=db_pool,
            chat=chat,
            embed=embed,
            whisper=whisper,
            documents_dir=documents_dir,
            fernet_key=fernet_key,
            redis_url=redis_url,
            executor=executor,
        )
```

Y actualizar la firma de `OrchestratorAgent.__init__` para aceptar `executor`:
```python
    def __init__(
        self,
        ...
        executor: "ToolExecutor | None" = None,
    ) -> None:
```

- [ ] **Step 4: Verificar sintaxis**

```bash
python -c "from orchestrator.agent import OrchestratorAgent; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/__main__.py orchestrator/agent.py
git commit -m "feat: orchestrator always gets ToolExecutor for full system access"
```

---

## Task 12: Test de integración del parser + push final

- [ ] **Step 1: Ejecutar toda la suite de tests**

```bash
python -m pytest tests/ -v
```
Expected: todos PASSED

- [ ] **Step 2: Verificar importaciones del paquete tools**

```bash
python -c "
from shared.tools import TOOL_DEFINITIONS, ToolExecutor, SSHStore, is_destructive
from shared.llm.chat import ToolCall
print(f'Tools: {len(TOOL_DEFINITIONS)} definidas')
print('OK')
"
```
Expected:
```
Tools: 7 definidas
OK
```

- [ ] **Step 3: Push final**

```bash
git push
```

---

## Self-Review

**Spec coverage:**
- ✅ 7 herramientas implementadas (bash, ssh_exec, ssh_save, ssh_list, read_file, write_file, list_dir)
- ✅ Bucle de tool calling en `_run_tool_loop` (máx. 10 iteraciones)
- ✅ `/superuser` con timer de 30 min que se resetea en cada herramienta
- ✅ Confirmación de destructivos con pausa y reanudación del bucle
- ✅ SSH con password y SSH key, guardado cifrado con Fernet
- ✅ `tools_enabled` sin migración de BD (usa tabla credentials)
- ✅ `create_secretary ... con herramientas` activa el flag
- ✅ Orquestador siempre con herramientas activas
- ✅ asyncssh añadida a pyproject.toml

**Type consistency:**
- `ToolCall.id`, `ToolCall.name`, `ToolCall.args` — usados consistentemente en Tasks 7 y 8
- `ToolExecutor.run(name: str, args: dict) -> str` — consistente en Tasks 5 y 8
- `SSHStore.__init__(pool, employee_id, store)` — consistente en Tasks 4 y 10/11
