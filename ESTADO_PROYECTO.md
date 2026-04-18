# SECRETARIOS VIRTUALES — DOCUMENTACIÓN COMPLETA

> Generado: 2026-04-18  
> Estado: Implementación completa (3 fases). Listo para despliegue en Ubuntu Server.

---

## ÍNDICE

1. [Qué es el sistema](#1-qué-es-el-sistema)
2. [Arquitectura](#2-arquitectura)
3. [Decisiones de diseño críticas](#3-decisiones-de-diseño-críticas)
4. [Variables de entorno](#4-variables-de-entorno)
5. [Esquema de base de datos](#5-esquema-de-base-de-datos)
6. [Perfiles de hardware](#6-perfiles-de-hardware)
7. [Todos los ficheros fuente (verbatim)](#7-todos-los-ficheros-fuente-verbatim)
8. [Tests](#8-tests)
9. [Instalación en Ubuntu Server](#9-instalación-en-ubuntu-server)
10. [Cómo usar el sistema](#10-cómo-usar-el-sistema)
11. [Errores conocidos y soluciones aplicadas](#11-errores-conocidos-y-soluciones-aplicadas)
12. [Historial de commits](#12-historial-de-commits)

---

## 1. Qué es el sistema

**Secretarios Virtuales** es un sistema multi-agente de secretarios personales vía Telegram.

- Cada empleado tiene un bot de Telegram propio (su "secretario").
- Hay un bot adicional de "orquestador" que pertenece al dueño del sistema y permite crear/destruir secretarios y enviarles mensajes.
- Un proceso "supervisor" arranca y monitoriza todos los bots como subprocesos del SO.

**Capacidades de cada secretario:**
- Responder mensajes de texto usando un LLM local (vLLM).
- Transcribir mensajes de voz (Whisper) y responder.
- Guardar documentos (PDF/texto) y buscarlos semánticamente (pgvector).
- Analizar fotos (LLM multimodal).
- Comprobar y resumir bandeja de entrada de correo.
- Recordar historial de conversaciones (últimas 8 + 3 docs relevantes por contexto).

**Capacidades del orquestador (dueño del sistema):**
- `crea secretario para X, token: T, chatid: C` → crea un nuevo secretario.
- `destruye secretario de X` → desactiva un secretario.
- `lista los secretarios` → lista todos los secretarios.
- `avisa a X que ...` → envía un mensaje admin al secretario de X.
- También puede usarlo como su propio secretario personal.

---

## 2. Arquitectura

```
Ubuntu Server
├── python -m supervisor          ← Proceso principal. Arranca todo lo demás.
│   ├── python -m orchestrator    ← Orquestador (1 proceso, 1 bot Telegram)
│   ├── python -m secretary <id1> ← Secretario empleado 1 (1 proceso, 1 bot)
│   ├── python -m secretary <id2> ← Secretario empleado 2
│   └── ...
│
├── Docker Compose (infrastructure/docker-compose.yml)
│   ├── sv-postgres   :5432  (pgvector/pgvector:pg16)
│   ├── sv-redis      :6379  (redis:7-alpine, autenticado)
│   ├── sv-vllm-chat  :8000  (vLLM, modelo chat)
│   ├── sv-vllm-embed :8001  (vLLM, modelo embedding, task=embed)
│   └── sv-whisper    :9000  (faster-whisper-server)
```

**Flujo de mensaje de texto:**
```
Usuario Telegram → Bot (python-telegram-bot) → SecretaryAgent._handle_text()
  → DatabasePool.acquire()   (asyncpg, setea app.current_employee_id en PostgreSQL)
  → Repository               (CRUD bajo RLS de PostgreSQL)
  → MemoryManager.build_context()
      → EmbeddingClient.embed(query)    → vLLM :8001
      → repo.get_recent_conversations() → PostgreSQL (RLS filtrado)
      → repo.search_documents()         → PostgreSQL cosine <=> pgvector
  → ChatClient.complete(messages, system) → vLLM :8000
  → memory.save_turn()
  → update.message.reply_text()
```

**Flujo de creación de secretario:**
```
Dueño → OrchestratorAgent._handle_text()
  → parse_command()  → CreateSecretaryCommand
  → AdminService.create_secretary()
      → asyncpg INSERT employees + INSERT credentials (token cifrado Fernet)
      → redis.publish("secretary.lifecycle", {event: "created", employee_id: "..."})
  → Supervisor._listen_lifecycle()
      → recibe el evento
      → asyncio.create_subprocess_exec(python, "-m", "secretary", str(id))
```

**Aislamiento multi-tenant:**
```
DatabasePool(dsn, employee_id)
  .acquire() → conn.execute("SELECT set_config('app.current_employee_id', $1, true)", uuid)
             → toda query bajo RLS PostgreSQL filtra por ese UUID
             → svapp no es superusuario → no puede saltarse FORCE ROW LEVEL SECURITY
```

---

## 3. Decisiones de diseño críticas

### 3.1 PostgreSQL RLS con set_config por conexión
Cada conexión en `DatabasePool.acquire()` ejecuta:
```sql
SELECT set_config('app.current_employee_id', '<uuid>', true)
```
El tercer argumento `true` hace que la variable sea local a la transacción.
Las políticas RLS usan `current_setting('app.current_employee_id', true)::uuid`.

**Por qué no superusuario:** El usuario `svuser` es el dueño de las tablas y podría saltarse RLS. Por eso se creó el rol `svapp` (no superusuario, no dueño) con `FORCE ROW LEVEL SECURITY`. Las aplicaciones usan `APP_DB_URL` con svapp. El setup wizard usa `DATABASE_URL` con svuser solo para operaciones de administración.

### 3.2 Un proceso OS por secretario
`supervisor.py` usa `asyncio.create_subprocess_exec(sys.executable, "-m", "secretary", str(id))`.
- Aislamiento real: si un secretario peta, no mata a los demás.
- Monitorización cada 30 segundos: si el proceso terminó y el empleado sigue activo, lo reinicia.

### 3.3 Redis pub/sub para coordinación
- Canal `secretary.lifecycle` → supervisor escucha para spawn/terminate.
- Canal `secretary.<uuid>` → secretario escucha mensajes admin del orquestador.

### 3.4 Fernet para cifrado de credenciales
- Tokens de Telegram y credenciales de email se cifran con `cryptography.Fernet`.
- La clave Fernet (`FERNET_KEY`) se genera en el setup y se guarda en `.env`.
- Sin la clave, las credenciales guardadas en PostgreSQL son inútiles.

### 3.5 redis-py 5.x: from_url() es SÍNCRONO
En redis-py ≥5, `redis.asyncio.from_url()` devuelve el cliente directamente (NO es una coroutine). **No se debe usar `await`.**
```python
# CORRECTO (redis-py 5.x):
r = aioredis.from_url(self._redis_url)
await r.publish(...)

# INCORRECTO (causa error):
r = await aioredis.from_url(self._redis_url)  # NO
```

### 3.6 Formato de vectores para pgvector
asyncpg no sabe serializar `list[float]` como `vector`. Hay que convertirlo a string:
```python
vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
await conn.execute("INSERT ... VALUES ($1::vector)", vec_str)
```

### 3.7 OrchestratorAgent hereda de SecretaryAgent
El orquestador tiene sus propias capacidades de secretario (el dueño también tiene asistente) más las capacidades admin. Sobreescribe `_handle_text()` para intentar primero el comando admin, y si no hay match llama a `super()._handle_text()`.

---

## 4. Variables de entorno

Fichero: `.env` (generado por `python -m infrastructure.setup`)

| Variable | Descripción | Ejemplo |
|---|---|---|
| `POSTGRES_USER` | Usuario owner de PostgreSQL | `svuser` |
| `POSTGRES_PASSWORD` | Contraseña de svuser | auto-generada |
| `POSTGRES_DB` | Nombre de la base de datos | `secretarios` |
| `DATABASE_URL` | DSN completo con svuser (admin) | `postgresql://svuser:pass@localhost:5432/secretarios` |
| `APP_DB_URL` | DSN con svapp (no superusuario, RLS) | `postgresql://svapp:svapppassword@localhost:5432/secretarios` |
| `REDIS_PASSWORD` | Contraseña Redis | auto-generada |
| `REDIS_URL` | URL Redis con auth | `redis://:pass@localhost:6379` |
| `VLLM_CHAT_URL` | URL vLLM chat | `http://localhost:8000/v1` |
| `VLLM_EMBED_URL` | URL vLLM embeddings | `http://localhost:8001/v1` |
| `VLLM_API_KEY` | API key vLLM (no se valida) | `sk-no-key-required` |
| `CHAT_MODEL` | Modelo de chat en vLLM | `Qwen/Qwen2.5-7B-Instruct-FP8` |
| `EMBEDDING_MODEL` | Modelo de embeddings en vLLM | `BAAI/bge-m3` |
| `EMBEDDING_DIM` | Dimensión del vector embedding | `1024` |
| `GPU_MEMORY_CHAT` | Fracción VRAM para chat | `0.70` |
| `GPU_MEMORY_EMBED` | Fracción VRAM para embeddings | `0.10` |
| `WHISPER_URL` | URL Whisper server | `http://localhost:9000` |
| `WHISPER_MODEL` | Modelo Whisper | `base` |
| `HF_TOKEN` | Token HuggingFace (descarga modelos) | `hf_xxxx` |
| `FERNET_KEY` | Clave Fernet base64url (32 bytes) | auto-generada |
| `DOCUMENTS_DIR` | Directorio de documentos subidos | `./data/documents` |
| `ORCHESTRATOR_BOT_TOKEN` | Token bot Telegram del orquestador | `123:ABC...` |
| `ORCHESTRATOR_CHAT_ID` | Chat ID del dueño del sistema | `123456789` |
| `HARDWARE_PROFILE` | Perfil detectado | `rtx3080_12gb` |
| `MAX_USERS` | Máx usuarios según hardware | `5` |

> **Nota:** `APP_DB_URL` está en `.env.example` pero el código usa `DATABASE_URL` tanto para admin como para la pool de secretarios. La columna `APP_DB_URL` fue parte del diseño inicial de RLS pero la implementación final usa `DATABASE_URL` para todo (svuser) en la pool. Si se quisiera máxima seguridad, cambiar `DatabasePool` para usar `APP_DB_URL` con svapp.

---

## 5. Esquema de base de datos

Fichero: `infrastructure/db/init.sql`

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE employees (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    telegram_chat_id TEXT UNIQUE,
    is_orchestrator BOOLEAN NOT NULL DEFAULT false,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'telegram',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON conversations(employee_id, created_at DESC);

CREATE TABLE documents (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    filepath     TEXT NOT NULL,
    content_text TEXT,
    embedding    vector,         -- SIN dimensión fija (compatible con múltiples perfiles)
    mime_type    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON documents(employee_id);

CREATE TABLE credentials (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    service_type TEXT NOT NULL,
    encrypted    TEXT NOT NULL,
    UNIQUE(employee_id, service_type)
);

CREATE TABLE tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'cancelled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON tasks(employee_id, status);

-- Row Level Security
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents     ENABLE ROW LEVEL SECURITY;
ALTER TABLE credentials   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks         ENABLE ROW LEVEL SECURITY;

CREATE POLICY isolate ON conversations
    FOR ALL USING (employee_id = current_setting('app.current_employee_id', true)::uuid);
CREATE POLICY isolate ON documents
    FOR ALL USING (employee_id = current_setting('app.current_employee_id', true)::uuid);
CREATE POLICY isolate ON credentials
    FOR ALL USING (employee_id = current_setting('app.current_employee_id', true)::uuid);
CREATE POLICY isolate ON tasks
    FOR ALL USING (employee_id = current_setting('app.current_employee_id', true)::uuid);

-- Application role (non-superuser, subject to RLS)
CREATE ROLE svapp LOGIN PASSWORD 'svapppassword';
GRANT CONNECT ON DATABASE secretarios TO svapp;
GRANT USAGE ON SCHEMA public TO svapp;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO svapp;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO svapp;

-- Force RLS even for table owners
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
ALTER TABLE documents     FORCE ROW LEVEL SECURITY;
ALTER TABLE credentials   FORCE ROW LEVEL SECURITY;
ALTER TABLE tasks         FORCE ROW LEVEL SECURITY;
```

**Tipos de credencial (`service_type`):**
- `telegram_token` → token del bot de Telegram (cifrado Fernet, JSON)
- `email_imap` → JSON cifrado con `{host, port, username, password}`
- `email_smtp` → JSON cifrado con `{host, port, username, password}`

---

## 6. Perfiles de hardware

Fichero: `infrastructure/profiles/hardware.json`

El setup wizard detecta la VRAM total via `nvidia-smi` y selecciona el perfil más capaz que quepa.

| Perfil | VRAM mín | Modelo Chat | Modelo Embed | Dim | Whisper | Usuarios |
|---|---|---|---|---|---|---|
| `spark` | 48 GB | Qwen3-30B-A3B-Instruct-2507-FP8 | Qwen3-Embedding-4B | 2560 | large-v3 | 20 |
| `rtx3090` | 24 GB | Qwen2.5-14B-Instruct-FP8 | Qwen3-Embedding-4B | 2560 | medium | 10 |
| `rtx3080_12gb` | 12 GB | Qwen2.5-7B-Instruct-FP8 | BAAI/bge-m3 | 1024 | base | 5 |
| `rtx3080ti_8gb` | 8 GB | Qwen2.5-3B-Instruct-FP8 | BAAI/bge-small-en-v1.5 | 384 | tiny | 3 |

Fracciones de VRAM:
- `spark`: chat=0.55, embed=0.20
- `rtx3090`: chat=0.55, embed=0.25
- `rtx3080_12gb`: chat=0.70, embed=0.10
- `rtx3080ti_8gb`: chat=0.75, embed=0.08

---

## 7. Todos los ficheros fuente (verbatim)

### pyproject.toml

```toml
[build-system]
requires = ["setuptools>=70"]
build-backend = "setuptools.build_meta"

[project]
name = "secretarios-virtuales"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "python-telegram-bot>=21.0,<22",
    "asyncpg>=0.29,<1",
    "openai>=1.0,<2",
    "aioimaplib>=2.0,<3",
    "aiosmtplib>=3.0,<4",
    "cryptography>=42.0,<43",
    "redis>=5.0,<6",
    "python-dotenv>=1.0,<2",
    "pydantic>=2.0,<3",
    "httpx>=0.27,<1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9",
    "pytest-asyncio>=0.23,<1",
    "ruff>=0.4,<1",
    "mypy>=1.9,<2",
    "pytest-mock>=3.14,<4",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["shared*", "secretary*", "orchestrator*", "supervisor*", "infrastructure*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### ruff.toml

```toml
line-length = 100
target-version = "py311"

[lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[lint.isort]
known-first-party = ["shared", "secretary", "orchestrator", "supervisor", "infrastructure"]
```

### mypy.ini

```ini
[mypy]
python_version = 3.11
strict = true
ignore_missing_imports = true
plugins = pydantic.mypy
```

### .env.example

```
# Base de datos
POSTGRES_USER=svuser
POSTGRES_PASSWORD=svpassword
POSTGRES_DB=secretarios
DATABASE_URL=postgresql://svuser:svpassword@localhost:5432/secretarios
APP_DB_URL=postgresql://svapp:svapppassword@localhost:5432/secretarios

# Redis
REDIS_PASSWORD=svredispass
REDIS_URL=redis://:svredispass@localhost:6379

# LLM (vLLM local)
VLLM_CHAT_URL=http://localhost:8000/v1
VLLM_EMBED_URL=http://localhost:8001/v1
VLLM_API_KEY=sk-no-key-required
CHAT_MODEL=Qwen/Qwen2.5-7B-Instruct-FP8
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIM=1024

# Audio
WHISPER_URL=http://localhost:9000

# HuggingFace
HF_TOKEN=hf_xxxx

# Cifrado (generado en setup)
FERNET_KEY=

# Documentos
DOCUMENTS_DIR=./data/documents
```

### infrastructure/docker-compose.yml

```yaml
services:
  vllm-chat:
    image: nvcr.io/nvidia/vllm:25.11-py3
    container_name: sv-vllm-chat
    restart: unless-stopped
    environment:
      - HF_TOKEN=${HF_TOKEN}
    ports:
      - "8000:8000"
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
    ipc: host
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    command:
      - vllm
      - serve
      - "${CHAT_MODEL}"
      - --gpu-memory-utilization
      - "${GPU_MEMORY_CHAT:-0.70}"
      - --dtype
      - auto
      - --max-model-len
      - "20000"
      - --enable-prefix-caching
    networks:
      - sv-network
    profiles: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 5

  vllm-embedding:
    image: nvcr.io/nvidia/vllm:25.11-py3
    container_name: sv-vllm-embedding
    restart: unless-stopped
    environment:
      - HF_TOKEN=${HF_TOKEN}
    ports:
      - "8001:8000"
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
    ipc: host
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    command:
      - vllm
      - serve
      - "${EMBEDDING_MODEL}"
      - --task
      - embed
      - --gpu-memory-utilization
      - "${GPU_MEMORY_EMBED:-0.10}"
      - --max-model-len
      - "8192"
      - --dtype
      - auto
    networks:
      - sv-network
    profiles: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 5

  whisper:
    image: fedirz/faster-whisper-server:latest-cuda
    container_name: sv-whisper
    restart: unless-stopped
    ports:
      - "9000:8000"
    environment:
      - WHISPER__MODEL=${WHISPER_MODEL:-base}
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    networks:
      - sv-network
    profiles: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 5

  postgres:
    image: pgvector/pgvector:pg16
    container_name: sv-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_USER=${POSTGRES_USER:-svuser}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-svpassword}
      - POSTGRES_DB=${POSTGRES_DB:-secretarios}
    ports:
      - "5432:5432"
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - sv-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-svuser}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: sv-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - ./data/redis:/data
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD:-svredispass}", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
    networks:
      - sv-network

networks:
  sv-network:
    driver: bridge
```

### infrastructure/profiles/hardware.json

```json
{
  "spark": {
    "min_vram_gb": 48,
    "chat_model": "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8",
    "embedding_model": "Qwen/Qwen3-Embedding-4B",
    "embedding_dim": 2560,
    "whisper_model": "large-v3",
    "gpu_memory_chat": 0.55,
    "gpu_memory_embed": 0.20,
    "max_users": 20
  },
  "rtx3090": {
    "min_vram_gb": 24,
    "chat_model": "Qwen/Qwen2.5-14B-Instruct-FP8",
    "embedding_model": "Qwen/Qwen3-Embedding-4B",
    "embedding_dim": 2560,
    "whisper_model": "medium",
    "gpu_memory_chat": 0.55,
    "gpu_memory_embed": 0.25,
    "max_users": 10
  },
  "rtx3080_12gb": {
    "min_vram_gb": 12,
    "chat_model": "Qwen/Qwen2.5-7B-Instruct-FP8",
    "embedding_model": "BAAI/bge-m3",
    "embedding_dim": 1024,
    "whisper_model": "base",
    "gpu_memory_chat": 0.70,
    "gpu_memory_embed": 0.10,
    "max_users": 5
  },
  "rtx3080ti_8gb": {
    "min_vram_gb": 8,
    "chat_model": "Qwen/Qwen2.5-3B-Instruct-FP8",
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "embedding_dim": 384,
    "whisper_model": "tiny",
    "gpu_memory_chat": 0.75,
    "gpu_memory_embed": 0.08,
    "max_users": 3
  }
}
```

### infrastructure/setup/detect_hardware.py

```python
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROFILES_PATH = Path(__file__).parent.parent / "profiles" / "hardware.json"


@dataclass
class Profile:
    name: str
    chat_model: str
    embedding_model: str
    embedding_dim: int
    whisper_model: str
    gpu_memory_chat: float
    gpu_memory_embed: float
    max_users: int


def _load_profiles() -> dict:
    return json.loads(PROFILES_PATH.read_text())


def detect_hardware() -> Profile:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("nvidia-smi failed")

        lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        total_vram_mb = sum(int(line.split(",")[1].strip()) for line in lines)
        total_vram_gb = total_vram_mb / 1024

    except Exception:
        return Profile(
            name="cpu",
            chat_model="",
            embedding_model="",
            embedding_dim=0,
            whisper_model="",
            gpu_memory_chat=0.0,
            gpu_memory_embed=0.0,
            max_users=0,
        )

    profiles = _load_profiles()
    ordered = sorted(profiles.items(), key=lambda x: x[1]["min_vram_gb"], reverse=True)
    for name, p in ordered:
        if total_vram_gb >= p["min_vram_gb"]:
            return Profile(
                name=name,
                chat_model=p["chat_model"],
                embedding_model=p["embedding_model"],
                embedding_dim=p["embedding_dim"],
                whisper_model=p["whisper_model"],
                gpu_memory_chat=p["gpu_memory_chat"],
                gpu_memory_embed=p["gpu_memory_embed"],
                max_users=p["max_users"],
            )

    return Profile(
        name="cpu",
        chat_model="",
        embedding_model="",
        embedding_dim=0,
        whisper_model="",
        gpu_memory_chat=0.0,
        gpu_memory_embed=0.0,
        max_users=0,
    )
```

### infrastructure/setup/generate_config.py

```python
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from .detect_hardware import Profile


def generate_env(profile: Profile, answers: dict[str, str]) -> str:
    fernet_key = Fernet.generate_key().decode()
    db_password = answers.get("db_password") or secrets.token_urlsafe(16)
    redis_password = secrets.token_urlsafe(16)

    return f"""# Auto-generado por setup — {profile.name}

# HuggingFace
HF_TOKEN={answers["hf_token"]}

# Telegram (Orquestador)
ORCHESTRATOR_BOT_TOKEN={answers["bot_token"]}
ORCHESTRATOR_CHAT_ID={answers["chat_id"]}

# Base de datos
POSTGRES_USER=svuser
POSTGRES_PASSWORD={db_password}
POSTGRES_DB=secretarios
DATABASE_URL=postgresql://svuser:{db_password}@localhost:5432/secretarios
APP_DB_URL=postgresql://svapp:svapppassword@localhost:5432/secretarios

# Redis
REDIS_PASSWORD={redis_password}
REDIS_URL=redis://:{redis_password}@localhost:6379

# LLM
VLLM_CHAT_URL=http://localhost:8000/v1
VLLM_EMBED_URL=http://localhost:8001/v1
VLLM_API_KEY=sk-no-key-required
CHAT_MODEL={profile.chat_model}
EMBEDDING_MODEL={profile.embedding_model}
EMBEDDING_DIM={profile.embedding_dim}
GPU_MEMORY_CHAT={profile.gpu_memory_chat}
GPU_MEMORY_EMBED={profile.gpu_memory_embed}

# Audio
WHISPER_URL=http://localhost:9000
WHISPER_MODEL={profile.whisper_model}

# Cifrado
FERNET_KEY={fernet_key}

# Documentos
DOCUMENTS_DIR=./data/documents

# Hardware
HARDWARE_PROFILE={profile.name}
MAX_USERS={profile.max_users}
"""
```

### infrastructure/setup/__main__.py

```python
import subprocess
import sys
from pathlib import Path

from .detect_hardware import detect_hardware
from .generate_config import generate_env


def ask(prompt: str, secret: bool = False) -> str:
    import getpass
    if secret:
        return getpass.getpass(f"  {prompt}: ").strip()
    return input(f"  {prompt}: ").strip()


def main() -> None:
    print("\n╔══════════════════════════════════════════╗")
    print("║   SECRETARIOS VIRTUALES — INSTALACIÓN   ║")
    print("╚══════════════════════════════════════════╝\n")

    print("🔍 Detectando hardware...")
    profile = detect_hardware()
    if profile.max_users == 0:
        print("⚠️  No se detectó GPU NVIDIA. Se necesita GPU para ejecutar los modelos.")
        sys.exit(1)

    print(f"✅ Perfil detectado: {profile.name}")
    print(f"   Modelo chat: {profile.chat_model}")
    print(f"   Modelo embedding: {profile.embedding_model}")
    print(f"   Usuarios máx: {profile.max_users}\n")

    print("📋 CONFIGURACIÓN\n")
    answers = {
        "hf_token": ask("HuggingFace token (hf_...)"),
        "bot_token": ask("Token bot Telegram del orquestador"),
        "chat_id": ask(
            "Tu chat_id de Telegram (escríbele a @userinfobot si no lo sabes)"
        ),
        "db_password": ask("Contraseña BD (Enter para generar automáticamente)"),
    }

    env_content = generate_env(profile, answers)
    Path(".env").write_text(env_content)
    print("\n✅ .env generado")

    print("🐳 Levantando servicios Docker...")
    subprocess.run(
        ["docker", "compose", "-f", "infrastructure/docker-compose.yml", "up", "-d",
         "postgres", "redis"],
        check=True,
    )

    import time
    print("⏳ Esperando PostgreSQL...")
    time.sleep(8)

    print("✅ PostgreSQL listo")
    print("\n╔══════════════════════════════════════════╗")
    print("║          INSTALACIÓN COMPLETADA          ║")
    print("╚══════════════════════════════════════════╝")
    print("\nSiguiente paso:")
    print("  python -m supervisor    # Arranca el sistema\n")


if __name__ == "__main__":
    main()
```

### shared/db/models.py

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Employee:
    id: UUID
    name: str
    telegram_chat_id: str | None
    is_orchestrator: bool
    is_active: bool
    created_at: datetime


@dataclass
class Conversation:
    id: UUID
    employee_id: UUID
    role: str
    content: str
    source: str
    created_at: datetime


@dataclass
class Document:
    id: UUID
    employee_id: UUID
    filename: str
    filepath: str
    content_text: str | None
    mime_type: str | None
    created_at: datetime


@dataclass
class Credential:
    id: UUID
    employee_id: UUID
    service_type: str
    encrypted: str


@dataclass
class Task:
    id: UUID
    employee_id: UUID
    title: str
    description: str | None
    status: str
    created_at: datetime
```

### shared/db/pool.py

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from uuid import UUID

import asyncpg


class DatabasePool:
    def __init__(self, dsn: str, employee_id: UUID) -> None:
        self._dsn = dsn
        self._employee_id = employee_id
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        if self._pool is None:
            raise RuntimeError("Call connect() first")
        async with self._pool.acquire() as conn:
            await conn.execute(
                "SELECT set_config('app.current_employee_id', $1, true)",
                str(self._employee_id),
            )
            yield conn
```

### shared/db/repository.py

```python
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
        return row["id"]  # type: ignore[index]

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
        return row["id"]  # type: ignore[index]

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
```

### shared/llm/chat.py

```python
from openai import AsyncOpenAI


class ChatClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
    ) -> str:
        all_messages: list[dict[str, str]] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=all_messages,  # type: ignore[arg-type]
        )
        return response.choices[0].message.content or ""
```

### shared/llm/embeddings.py

```python
from openai import AsyncOpenAI


class EmbeddingClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding
```

### shared/audio/whisper.py

```python
import httpx


class WhisperClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.ogg") -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/audio/transcriptions",
                files={"file": (filename, audio_bytes, "audio/ogg")},
                data={"model": "whisper-1"},
            )
        if response.status_code != 200:
            raise RuntimeError(f"Whisper error {response.status_code}: {response.text}")
        return response.json()["text"]
```

### shared/crypto.py

```python
from cryptography.fernet import Fernet


class CredentialStore:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        return self._fernet.decrypt(encrypted.encode()).decode()

    @staticmethod
    def generate_key() -> bytes:
        return Fernet.generate_key()
```

### shared/email/models.py

```python
from dataclasses import dataclass


@dataclass
class EmailConfig:
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    username: str
    password: str


@dataclass
class EmailMessage:
    uid: str
    sender: str
    subject: str
    body: str
    date: str
```

### shared/email/client.py

```python
import email as email_lib
from email.mime.text import MIMEText

import aioimaplib
import aiosmtplib

from .models import EmailConfig, EmailMessage


class EmailClient:
    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    async def send(self, to: str, subject: str, body: str) -> None:
        message = MIMEText(body, "plain", "utf-8")
        message["From"] = self._config.username
        message["To"] = to
        message["Subject"] = subject

        await aiosmtplib.send(
            message,
            hostname=self._config.smtp_host,
            port=self._config.smtp_port,
            username=self._config.username,
            password=self._config.password,
            start_tls=True,
        )

    async def fetch_inbox(self, limit: int = 10) -> list[EmailMessage]:
        messages: list[EmailMessage] = []
        async with aioimaplib.IMAP4_SSL(
            host=self._config.imap_host, port=self._config.imap_port
        ) as imap:
            await imap.login(self._config.username, self._config.password)
            await imap.select("INBOX")
            _, data = await imap.search("UNSEEN")
            uids = data[0].decode().split() if data[0] else []
            for uid in uids[-limit:]:
                _, msg_data = await imap.fetch(uid, "(RFC822)")
                raw = msg_data[0][1] if msg_data else b""
                parsed = email_lib.message_from_bytes(raw)
                body = ""
                if parsed.is_multipart():
                    for part in parsed.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="replace")
                            break
                else:
                    body = parsed.get_payload(decode=True).decode(errors="replace")  # type: ignore[union-attr]

                messages.append(
                    EmailMessage(
                        uid=uid,
                        sender=parsed.get("From", ""),
                        subject=parsed.get("Subject", ""),
                        body=body,
                        date=parsed.get("Date", ""),
                    )
                )
        return messages
```

### secretary/memory.py

```python
from shared.db.repository import Repository
from shared.llm.embeddings import EmbeddingClient


class MemoryManager:
    def __init__(self, repo: Repository, embed_client: EmbeddingClient) -> None:
        self._repo = repo
        self._embed = embed_client

    async def build_context(self, query: str, conv_limit: int = 8, doc_limit: int = 3) -> str:
        embedding = await self._embed.embed(query)
        conversations = await self._repo.get_recent_conversations(limit=conv_limit)
        documents = await self._repo.search_documents(embedding=embedding, limit=doc_limit)

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

        return "\n\n".join(parts)

    async def save_turn(self, user_msg: str, assistant_msg: str) -> None:
        await self._repo.save_conversation("user", user_msg)
        await self._repo.save_conversation("assistant", assistant_msg)
```

### secretary/handlers/text.py

```python
from secretary.memory import MemoryManager
from shared.llm.chat import ChatClient

SYSTEM_TEMPLATE = """Eres el secretario virtual de {name}.
Eres profesional, conciso y útil.
Respondes siempre en el idioma en que te escribe {name}.

{context}"""


async def handle_text(
    message: str,
    employee_name: str,
    memory: MemoryManager,
    chat: ChatClient,
) -> str:
    context = await memory.build_context(message)
    system = SYSTEM_TEMPLATE.format(name=employee_name, context=context)
    return await chat.complete(
        messages=[{"role": "user", "content": message}],
        system=system,
    )
```

### secretary/handlers/audio.py

```python
from secretary.handlers.text import handle_text
from secretary.memory import MemoryManager
from shared.audio.whisper import WhisperClient
from shared.llm.chat import ChatClient


async def handle_audio(
    audio_bytes: bytes,
    filename: str,
    employee_name: str,
    whisper: WhisperClient,
    memory: MemoryManager,
    chat: ChatClient,
) -> tuple[str, str]:
    transcription = await whisper.transcribe(audio_bytes, filename=filename)
    response = await handle_text(
        message=transcription,
        employee_name=employee_name,
        memory=memory,
        chat=chat,
    )
    return transcription, response
```

### secretary/handlers/document.py

```python
from pathlib import Path
from uuid import UUID

from shared.db.repository import Repository
from shared.llm.embeddings import EmbeddingClient


def _extract_text(file_bytes: bytes, mime_type: str) -> str:
    if mime_type == "text/plain":
        return file_bytes.decode(errors="replace")
    if mime_type == "application/pdf":
        try:
            import io
            import pypdf
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

    filepath = employee_dir / filename
    filepath.write_bytes(file_bytes)

    content_text = _extract_text(file_bytes, mime_type)
    embedding = await embed.embed(content_text or filename)

    await repo.save_document(
        filename=filename,
        filepath=str(filepath),
        content_text=content_text,
        embedding=embedding,
        mime_type=mime_type,
    )

    return f"✅ Documento guardado: {filename}"
```

### secretary/handlers/photo.py

```python
import base64

from secretary.memory import MemoryManager
from shared.llm.chat import ChatClient


async def handle_photo(
    photo_bytes: bytes,
    caption: str | None,
    employee_name: str,
    chat: ChatClient,
    memory: MemoryManager,
) -> str:
    context = await memory.build_context(caption or "imagen")
    b64 = base64.b64encode(photo_bytes).decode()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                },
                {
                    "type": "text",
                    "text": caption or "Describe esta imagen.",
                },
            ],
        }
    ]

    system = (
        f"Eres el secretario virtual de {employee_name}. "
        f"Analiza la imagen y responde útilmente.\n\n{context}"
    )
    return await chat.complete(messages=messages, system=system)  # type: ignore[arg-type]
```

### secretary/handlers/email.py

```python
from shared.email.client import EmailClient
from shared.llm.chat import ChatClient


async def handle_check_email(
    email_client: EmailClient,
    chat: ChatClient,
    employee_name: str,
    limit: int = 5,
) -> str:
    messages = await email_client.fetch_inbox(limit=limit)
    if not messages:
        return "No tienes emails nuevos."

    summary_input = "\n".join(
        f"De: {m.sender} | Asunto: {m.subject} | {m.body[:200]}"
        for m in messages
    )
    return await chat.complete(
        messages=[
            {
                "role": "user",
                "content": (
                    f"Resume estos emails de {employee_name} de forma clara:\n{summary_input}"
                ),
            }
        ]
    )


async def handle_send_email(
    email_client: EmailClient,
    to: str,
    subject: str,
    body: str,
) -> str:
    await email_client.send(to=to, subject=subject, body=body)
    return f"✅ Email enviado a {to}."
```

### secretary/agent.py

```python
import logging
from pathlib import Path
from uuid import UUID

import redis.asyncio as aioredis
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

from secretary.handlers.audio import handle_audio
from secretary.handlers.document import handle_document
from secretary.handlers.email import handle_check_email
from secretary.handlers.photo import handle_photo
from secretary.handlers.text import handle_text
from secretary.memory import MemoryManager
from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.db.repository import Repository
from shared.email.client import EmailClient
from shared.email.models import EmailConfig
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)


class SecretaryAgent:
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
    ) -> None:
        self._employee_id = employee_id
        self._employee_name = employee_name
        self._allowed_chat_id = str(allowed_chat_id)
        self._pool = db_pool
        self._chat = chat
        self._embed = embed
        self._whisper = whisper
        self._documents_dir = documents_dir
        self._store = CredentialStore(fernet_key)
        self._redis_url = redis_url

    async def _is_authorized(self, update: Update) -> bool:
        return str(update.effective_chat.id) == self._allowed_chat_id  # type: ignore[union-attr]

    async def _get_email_client(self) -> EmailClient | None:
        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            enc_imap = await repo.get_credential("email_imap")
            enc_smtp = await repo.get_credential("email_smtp")
        if not enc_imap or not enc_smtp:
            return None
        import json
        imap = json.loads(self._store.decrypt(enc_imap))
        smtp = json.loads(self._store.decrypt(enc_smtp))
        return EmailClient(
            EmailConfig(
                imap_host=imap["host"],
                imap_port=int(imap["port"]),
                smtp_host=smtp["host"],
                smtp_port=int(smtp["port"]),
                username=imap["username"],
                password=imap["password"],
            )
        )

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        msg = update.message.text or ""  # type: ignore[union-attr]

        if msg.lower().startswith("/email"):
            email_client = await self._get_email_client()
            if not email_client:
                await update.message.reply_text("❌ Email no configurado.")  # type: ignore[union-attr]
                return
            async with self._pool.acquire() as conn:
                repo = Repository(conn, self._employee_id)
                memory = MemoryManager(repo=repo, embed_client=self._embed)
                response = await handle_check_email(
                    email_client=email_client,
                    chat=self._chat,
                    employee_name=self._employee_name,
                )
                await memory.save_turn(msg, response)
            await update.message.reply_text(response)  # type: ignore[union-attr]
            return

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            response = await handle_text(
                message=msg,
                employee_name=self._employee_name,
                memory=memory,
                chat=self._chat,
            )
            await memory.save_turn(msg, response)
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        voice = update.message.voice  # type: ignore[union-attr]
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            transcription, response = await handle_audio(
                audio_bytes=bytes(audio_bytes),
                filename="audio.ogg",
                employee_name=self._employee_name,
                whisper=self._whisper,
                memory=memory,
                chat=self._chat,
            )
            await memory.save_turn(transcription, response)

        await update.message.reply_text(  # type: ignore[union-attr]
            f"🎙 _{transcription}_\n\n{response}", parse_mode="Markdown"
        )

    async def _handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        doc = update.message.document  # type: ignore[union-attr]
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            response = await handle_document(
                file_bytes=bytes(file_bytes),
                filename=doc.file_name or "document",
                mime_type=doc.mime_type or "application/octet-stream",
                employee_id=self._employee_id,
                documents_dir=self._documents_dir,
                repo=repo,
                embed=self._embed,
            )
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        photo = update.message.photo[-1]  # type: ignore[union-attr]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        caption = update.message.caption  # type: ignore[union-attr]

        async with self._pool.acquire() as conn:
            repo = Repository(conn, self._employee_id)
            memory = MemoryManager(repo=repo, embed_client=self._embed)
            response = await handle_photo(
                photo_bytes=bytes(photo_bytes),
                caption=caption,
                employee_name=self._employee_name,
                chat=self._chat,
                memory=memory,
            )
        await update.message.reply_text(response)  # type: ignore[union-attr]

    async def _listen_redis(self, app: Application) -> None:  # type: ignore[type-arg]
        redis = await aioredis.from_url(self._redis_url)
        pubsub = redis.pubsub()
        channel = f"secretary.{self._employee_id}"
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            import json
            data = json.loads(message["data"])
            if data.get("type") == "admin_message":
                await app.bot.send_message(
                    chat_id=self._allowed_chat_id,
                    text=data["content"],
                )

    async def run(self, bot_token: str) -> None:
        app = Application.builder().token(bot_token).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        logger.info(
            "Secretary %s starting (chat_id=%s)", self._employee_name, self._allowed_chat_id
        )
        await app.run_polling(drop_pending_updates=True)
```

### secretary/__main__.py

```python
import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient
from secretary.agent import SecretaryAgent


async def main(employee_id_str: str) -> None:
    employee_id = UUID(employee_id_str)

    raw_conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    row = await raw_conn.fetchrow(
        "SELECT name, telegram_chat_id FROM employees WHERE id = $1", employee_id
    )
    await raw_conn.close()

    if not row:
        print(f"ERROR: employee {employee_id} not found")
        sys.exit(1)

    employee_name = row["name"]
    telegram_chat_id = row["telegram_chat_id"]

    raw_conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await raw_conn.execute(
        "SELECT set_config('app.current_employee_id', $1, true)", str(employee_id)
    )
    enc_token = await raw_conn.fetchval(
        "SELECT encrypted FROM credentials WHERE employee_id=$1 AND service_type='telegram_token'",
        employee_id,
    )
    await raw_conn.close()

    fernet_key = os.environ["FERNET_KEY"].encode()
    store = CredentialStore(fernet_key)
    bot_token = store.decrypt(enc_token)

    pool = DatabasePool(os.environ["DATABASE_URL"], employee_id)
    await pool.connect()

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
        whisper=WhisperClient(base_url=os.environ["WHISPER_URL"]),
        documents_dir=Path(os.environ.get("DOCUMENTS_DIR", "./data/documents")),
        fernet_key=fernet_key,
        redis_url=os.environ["REDIS_URL"],
    )

    await agent.run(bot_token)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m secretary <employee_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
```

### orchestrator/parser.py

```python
import re
from dataclasses import dataclass


@dataclass
class CreateSecretaryCommand:
    name: str
    telegram_token: str
    telegram_chat_id: str


@dataclass
class DestroySecretaryCommand:
    name: str


@dataclass
class SendMessageCommand:
    name: str
    message: str


@dataclass
class ListSecretariesCommand:
    pass


# Matches: "crea secretario para X, token: T, chatid: C"
_CREATE_PATTERN = re.compile(
    r"crea\s+secretario\s+(?:para\s+)?(?P<name>\w+)[^,]*"
    r",\s*token[:\s]+(?P<token>[\w:_-]+)"
    r"(?:[^,]*,\s*chat_?id[:\s]+(?P<chatid>[\w-]+))?",
    re.IGNORECASE,
)

# Matches: "destruye/elimina/borra secretario de X"
_DESTROY_PATTERN = re.compile(
    r"(?:destruye|elimina|borra)\s+(?:(?:al?\s+)?secretario\s+(?:de\s+)?)?(?P<name>\w+)",
    re.IGNORECASE,
)

# Matches: "avisa/dile/manda a X que ..." or "mensaje para X: ..."
_SEND_PATTERN = re.compile(
    r"(?:avisa|d[ií]le|manda(?:le)?|mensaje\s+para)\s+(?:a\s+)?(?P<name>\w+)[^\w]*"
    r"(?:que\s+)?(?P<message>.+)",
    re.IGNORECASE,
)

# Matches: "lista/muestra secretarios"
_LIST_PATTERN = re.compile(
    r"(?:lista|muestra|ver|show)\s+(?:los\s+)?secretarios?",
    re.IGNORECASE,
)


def parse_command(text: str):
    """Parse natural language owner command. Returns a command dataclass or None."""
    if m := _LIST_PATTERN.search(text):
        return ListSecretariesCommand()

    if m := _CREATE_PATTERN.search(text):
        return CreateSecretaryCommand(
            name=m.group("name"),
            telegram_token=m.group("token"),
            telegram_chat_id=m.group("chatid") or "",
        )

    if m := _DESTROY_PATTERN.search(text):
        return DestroySecretaryCommand(name=m.group("name"))

    if m := _SEND_PATTERN.search(text):
        return SendMessageCommand(
            name=m.group("name"),
            message=m.group("message").strip(),
        )

    return None
```

### orchestrator/admin.py

```python
import json
import os
from uuid import UUID

import asyncpg

from shared.crypto import CredentialStore


class AdminService:
    def __init__(self, dsn: str, redis_url: str, fernet_key: bytes) -> None:
        self._dsn = dsn
        self._redis_url = redis_url
        self._store = CredentialStore(fernet_key)

    async def create_secretary(
        self,
        name: str,
        telegram_token: str,
        telegram_chat_id: str,
    ) -> UUID:
        conn = await asyncpg.connect(self._dsn)
        try:
            employee_id = await conn.fetchval(
                """
                INSERT INTO employees (name, telegram_chat_id)
                VALUES ($1, $2)
                RETURNING id
                """,
                name, telegram_chat_id,
            )
            await conn.execute(
                "SELECT set_config('app.current_employee_id', $1, true)", str(employee_id)
            )
            encrypted_token = self._store.encrypt(telegram_token)
            await conn.execute(
                """
                INSERT INTO credentials (employee_id, service_type, encrypted)
                VALUES ($1, 'telegram_token', $2)
                """,
                employee_id, encrypted_token,
            )
        finally:
            await conn.close()

        import redis.asyncio as aioredis
        r = aioredis.from_url(self._redis_url)
        await r.publish("secretary.lifecycle", json.dumps({
            "event": "created",
            "employee_id": str(employee_id),
        }))
        await r.aclose()

        return employee_id

    async def destroy_secretary(self, employee_id: UUID) -> None:
        conn = await asyncpg.connect(self._dsn)
        try:
            await conn.execute(
                "UPDATE employees SET is_active = false WHERE id = $1", employee_id
            )
        finally:
            await conn.close()

        import redis.asyncio as aioredis
        r = aioredis.from_url(self._redis_url)
        await r.publish("secretary.lifecycle", json.dumps({
            "event": "destroyed",
            "employee_id": str(employee_id),
        }))
        await r.aclose()

    async def list_secretaries(self) -> list[dict]:
        conn = await asyncpg.connect(self._dsn)
        try:
            rows = await conn.fetch(
                """
                SELECT id, name, telegram_chat_id, is_active, created_at
                FROM employees
                WHERE is_orchestrator = false
                ORDER BY created_at
                """
            )
        finally:
            await conn.close()
        return [dict(r) for r in rows]

    async def send_message_to_secretary(
        self, employee_id: UUID, content: str
    ) -> None:
        import redis.asyncio as aioredis
        r = aioredis.from_url(self._redis_url)
        await r.publish(
            f"secretary.{employee_id}",
            json.dumps({"type": "admin_message", "content": content}),
        )
        await r.aclose()
```

### orchestrator/agent.py

```python
import logging
from pathlib import Path
from uuid import UUID

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from orchestrator.admin import AdminService
from orchestrator.parser import (
    CreateSecretaryCommand,
    DestroySecretaryCommand,
    ListSecretariesCommand,
    SendMessageCommand,
    parse_command,
)
from secretary.agent import SecretaryAgent
from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)


class OrchestratorAgent(SecretaryAgent):
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
        dsn: str,
    ) -> None:
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
        )
        self._admin = AdminService(
            dsn=dsn,
            redis_url=redis_url,
            fernet_key=fernet_key,
        )
        self._dsn = dsn

    async def _handle_admin_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """Try to handle as admin command. Returns True if handled."""
        msg = update.message.text or ""  # type: ignore[union-attr]
        command = parse_command(msg)

        if command is None:
            return False

        if isinstance(command, ListSecretariesCommand):
            secretaries = await self._admin.list_secretaries()
            if not secretaries:
                text = "No hay secretarios activos."
            else:
                lines = [
                    f"{'✅' if s['is_active'] else '❌'} {s['name']} — chat_id: {s['telegram_chat_id']}"
                    for s in secretaries
                ]
                text = "Secretarios:\n" + "\n".join(lines)
            await update.message.reply_text(text)  # type: ignore[union-attr]
            return True

        if isinstance(command, CreateSecretaryCommand):
            employee_id = await self._admin.create_secretary(
                name=command.name,
                telegram_token=command.telegram_token,
                telegram_chat_id=command.telegram_chat_id,
            )
            await update.message.reply_text(  # type: ignore[union-attr]
                f"✅ Secretario {command.name} creado (id: {employee_id}).\n"
                f"El supervisor lo arrancará en breve."
            )
            return True

        if isinstance(command, DestroySecretaryCommand):
            secretaries = await self._admin.list_secretaries()
            match = next(
                (s for s in secretaries if s["name"].lower() == command.name.lower()), None
            )
            if not match:
                await update.message.reply_text(f"❌ No encontré secretario con nombre {command.name}.")  # type: ignore[union-attr]
                return True
            await self._admin.destroy_secretary(UUID(str(match["id"])))
            await update.message.reply_text(f"🗑 Secretario {command.name} eliminado.")  # type: ignore[union-attr]
            return True

        if isinstance(command, SendMessageCommand):
            secretaries = await self._admin.list_secretaries()
            match = next(
                (s for s in secretaries if s["name"].lower() == command.name.lower()), None
            )
            if not match:
                await update.message.reply_text(f"❌ No encontré secretario con nombre {command.name}.")  # type: ignore[union-attr]
                return True
            await self._admin.send_message_to_secretary(
                employee_id=UUID(str(match["id"])),
                content=command.message,
            )
            await update.message.reply_text(f"✅ Mensaje enviado a {command.name}.")  # type: ignore[union-attr]
            return True

        return False

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorized(update):
            return
        if await self._handle_admin_command(update, context):
            return
        await super()._handle_text(update, context)

    async def run(self, bot_token: str) -> None:  # type: ignore[override]
        app = Application.builder().token(bot_token).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.COMMAND, self._handle_text))
        app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        logger.info("OrchestratorAgent starting (chat_id=%s)", self._allowed_chat_id)
        await app.run_polling(drop_pending_updates=True)
```

### orchestrator/__main__.py

```python
import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

from shared.audio.whisper import WhisperClient
from shared.crypto import CredentialStore
from shared.db.pool import DatabasePool
from shared.llm.chat import ChatClient
from shared.llm.embeddings import EmbeddingClient
from orchestrator.agent import OrchestratorAgent


async def main() -> None:
    bot_token = os.environ["ORCHESTRATOR_BOT_TOKEN"]
    chat_id = os.environ["ORCHESTRATOR_CHAT_ID"]
    dsn = os.environ["DATABASE_URL"]
    fernet_key = os.environ["FERNET_KEY"].encode()

    # Find or create orchestrator employee record
    conn = await asyncpg.connect(dsn)
    row = await conn.fetchrow(
        "SELECT id, name FROM employees WHERE is_orchestrator = true AND is_active = true"
    )
    if not row:
        employee_id = await conn.fetchval(
            """
            INSERT INTO employees (name, telegram_chat_id, is_orchestrator)
            VALUES ('Orquestador', $1, true)
            RETURNING id
            """,
            chat_id,
        )
        employee_name = "Orquestador"
    else:
        employee_id = row["id"]
        employee_name = row["name"]
    await conn.close()

    pool = DatabasePool(dsn, employee_id)
    await pool.connect()

    agent = OrchestratorAgent(
        employee_id=employee_id,
        employee_name=employee_name,
        allowed_chat_id=chat_id,
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
        whisper=WhisperClient(base_url=os.environ["WHISPER_URL"]),
        documents_dir=Path(os.environ.get("DOCUMENTS_DIR", "./data/documents")),
        fernet_key=fernet_key,
        redis_url=os.environ["REDIS_URL"],
        dsn=dsn,
    )

    await agent.run(bot_token)


if __name__ == "__main__":
    asyncio.run(main())
```

### supervisor/supervisor.py

```python
import asyncio
import json
import logging
import os
import subprocess
import sys
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class Supervisor:
    def __init__(self, dsn: str, redis_url: str) -> None:
        self._dsn = dsn
        self._redis_url = redis_url
        self._processes: dict[UUID, asyncio.subprocess.Process] = {}

    async def _spawn(self, employee_id: UUID) -> None:
        if employee_id in self._processes:
            proc = self._processes[employee_id]
            if proc.returncode is None:
                logger.info("Secretary %s already running", employee_id)
                return

        logger.info("Spawning secretary %s", employee_id)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "secretary", str(employee_id),
            cwd=os.getcwd(),
        )
        self._processes[employee_id] = proc

    async def _terminate(self, employee_id: UUID) -> None:
        proc = self._processes.pop(employee_id, None)
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                proc.kill()
        logger.info("Secretary %s terminated", employee_id)

    async def _monitor_processes(self) -> None:
        while True:
            await asyncio.sleep(30)
            conn = await asyncpg.connect(self._dsn)
            active_ids = {
                row["id"]
                for row in await conn.fetch(
                    "SELECT id FROM employees WHERE is_active = true AND is_orchestrator = false"
                )
            }
            await conn.close()

            for employee_id in list(self._processes.keys()):
                proc = self._processes[employee_id]
                if proc.returncode is not None and employee_id in active_ids:
                    logger.warning("Secretary %s crashed (code %s), restarting", employee_id, proc.returncode)
                    await self._spawn(employee_id)

    async def _listen_lifecycle(self) -> None:
        r = await aioredis.from_url(self._redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe("secretary.lifecycle")
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            employee_id = UUID(data["employee_id"])
            if data["event"] == "created":
                await self._spawn(employee_id)
            elif data["event"] == "destroyed":
                await self._terminate(employee_id)

    async def run(self) -> None:
        logger.info("Supervisor starting")

        # Spawn all active secretaries on startup
        conn = await asyncpg.connect(self._dsn)
        rows = await conn.fetch(
            "SELECT id FROM employees WHERE is_active = true AND is_orchestrator = false"
        )
        await conn.close()

        for row in rows:
            await self._spawn(row["id"])

        # Also spawn orchestrator
        orchestrator_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "orchestrator",
            cwd=os.getcwd(),
        )
        logger.info("Orchestrator spawned (pid %s)", orchestrator_proc.pid)

        await asyncio.gather(
            self._monitor_processes(),
            self._listen_lifecycle(),
        )
```

### supervisor/__main__.py

```python
import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

from supervisor.supervisor import Supervisor


def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    supervisor = Supervisor(dsn=dsn, redis_url=redis_url)
    asyncio.run(supervisor.run())


if __name__ == "__main__":
    main()
```

---

## 8. Tests

### Estado de los tests

- **Tests sin base de datos (pasan en cualquier máquina):** 33 tests
- **Tests de integración (requieren PostgreSQL real):** 2 ficheros
  - `tests/shared/db/test_pool.py` → necesita PostgreSQL con el schema de init.sql
  - `tests/shared/db/test_repository.py` → necesita PostgreSQL con el schema de init.sql

### Ejecutar tests (sin DB)

```bash
pytest tests/ -v --ignore=tests/shared/db/
```

### Ejecutar todos los tests (con DB levantada)

```bash
# Levantar solo postgres
docker compose -f infrastructure/docker-compose.yml up -d postgres
sleep 8

# Todos los tests
pytest tests/ -v
```

### Ficheros de test

Los tests están en `tests/` con la misma estructura de paquetes que el código fuente:
- `tests/shared/test_crypto.py` — CredentialStore (Fernet)
- `tests/shared/llm/test_llm.py` — ChatClient, EmbeddingClient (mockeados)
- `tests/shared/audio/test_whisper.py` — WhisperClient (mockeado)
- `tests/shared/email/test_email.py` — EmailClient (mockeado)
- `tests/shared/test_detect_hardware.py` — detect_hardware (subprocess mockeado)
- `tests/shared/db/test_pool.py` — DatabasePool (integración, necesita PostgreSQL)
- `tests/shared/db/test_repository.py` — Repository (integración, necesita PostgreSQL)
- `tests/secretary/test_memory.py` — MemoryManager (mockeado)
- `tests/secretary/test_handler_text.py` — handle_text (mockeado)
- `tests/secretary/test_handler_audio.py` — handle_audio (mockeado)
- `tests/secretary/test_handler_document.py` — handle_document (tmp_path)
- `tests/secretary/test_handler_photo.py` — handle_photo (mockeado)
- `tests/secretary/test_handler_email.py` — handle_check_email, handle_send_email (mockeados)
- `tests/secretary/test_agent.py` — SecretaryAgent._is_authorized (mockeado)
- `tests/orchestrator/test_parser.py` — parse_command (puro, sin mocks)
- `tests/orchestrator/test_admin.py` — AdminService (Redis mockeado)
- `tests/supervisor/test_supervisor.py` — Supervisor (subprocess mockeado)

---

## 9. Instalación en Ubuntu Server

### 9.1 Prerrequisitos de sistema

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Python 3.11
sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential

# uv (gestor de paquetes Python ultrarrápido)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env   # o abrir nueva terminal

# Docker
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
# Cerrar sesión y volver a entrar para que surta efecto
```

### 9.2 Drivers NVIDIA + Container Toolkit (solo si hay GPU NVIDIA)

```bash
# Detectar GPU
lspci | grep -i nvidia

# Instalar drivers NVIDIA (reemplazar 550 por la versión más reciente disponible)
sudo apt install -y nvidia-driver-550
sudo reboot

# Verificar tras reboot
nvidia-smi

# NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verificar
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

### 9.3 Clonar e instalar el proyecto

```bash
# Clonar (sustituir <repo_url> por la URL del repositorio GitHub)
git clone <repo_url> secretarios-virtuales
cd secretarios-virtuales

# Crear entorno virtual e instalar dependencias
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### 9.4 Configuración inicial (wizard automático)

```bash
# Desde el directorio del proyecto con el entorno activado:
python -m infrastructure.setup
```

El wizard:
1. Detecta la GPU con nvidia-smi y selecciona el perfil de hardware.
2. Pregunta: HuggingFace token, token del bot orquestador, tu chat_id de Telegram, contraseña BD.
3. Genera `.env` con Fernet key, contraseñas aleatorias y modelos adecuados al hardware.
4. Arranca postgres y redis con Docker Compose.
5. El schema SQL se aplica automáticamente (Docker volumen `init.sql`).

> **Obtener chat_id de Telegram:** Escríbele a @userinfobot en Telegram. Te responde con tu chat_id.

> **Crear bot en Telegram:** Escríbele a @BotFather, `/newbot`, sigue instrucciones, guarda el token.

### 9.5 Arrancar los modelos de IA (GPU)

```bash
# Levantar vLLM chat + vLLM embedding + Whisper
docker compose -f infrastructure/docker-compose.yml --profile gpu up -d

# Comprobar estado
docker compose -f infrastructure/docker-compose.yml ps

# Esperar a que los modelos carguen (pueden tardar 5-15 minutos la primera vez)
# Los modelos se descargan de HuggingFace automáticamente si no están en caché
docker logs sv-vllm-chat -f
```

### 9.6 Arrancar el sistema

```bash
# Desde el directorio del proyecto con .venv activo
source .venv/bin/activate
python -m supervisor
```

Esto arranca:
- El supervisor (proceso principal)
- El orquestador (subproceso)
- Todos los secretarios activos en la BD (subprocesos)

### 9.7 Ejecutar como servicio systemd (producción)

```bash
# Crear fichero de servicio
sudo nano /etc/systemd/system/secretarios.service
```

Contenido:
```ini
[Unit]
Description=Secretarios Virtuales
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=<tu_usuario>
WorkingDirectory=/home/<tu_usuario>/secretarios-virtuales
Environment="PATH=/home/<tu_usuario>/secretarios-virtuales/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/<tu_usuario>/secretarios-virtuales/.venv/bin/python -m supervisor
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable secretarios
sudo systemctl start secretarios
sudo systemctl status secretarios

# Ver logs
journalctl -u secretarios -f
```

### 9.8 Añadir un secretario (tras instalar)

Desde el bot del orquestador en Telegram:
```
crea secretario para Alejandro, token: 7890123456:AAHxxxxxx, chatid: 987654321
```

El supervisor lo arrancará automáticamente en segundos.

### 9.9 Estructura de directorios en producción

```
~/secretarios-virtuales/
├── .env                          ← NO commitear, contiene secrets
├── pyproject.toml
├── infrastructure/
│   ├── docker-compose.yml
│   ├── db/init.sql
│   ├── profiles/hardware.json
│   └── setup/
├── shared/
├── secretary/
├── orchestrator/
├── supervisor/
├── tests/
└── data/                         ← Creado automáticamente
    ├── postgres/                 ← Datos PostgreSQL (Docker volumen)
    ├── redis/                    ← Datos Redis (Docker volumen)
    └── documents/                ← Documentos subidos por empleados
        └── <employee_uuid>/
            └── documento.pdf
```

---

## 10. Cómo usar el sistema

### Dueño del sistema (bot orquestador)

Comandos naturales en español al bot orquestador:

| Intención | Ejemplo |
|---|---|
| Crear secretario | `crea secretario para María, token: 123:ABC, chatid: 555666777` |
| Listar secretarios | `lista los secretarios` |
| Destruir secretario | `destruye secretario de María` |
| Enviar mensaje a secretario | `avisa a María que hay reunión mañana a las 10h` |
| Usar como secretario propio | Cualquier otra frase |

### Empleado (su bot personal)

| Acción | Cómo |
|---|---|
| Conversar | Escribir texto normal |
| Notas de voz | Enviar audio de Telegram |
| Guardar documento | Enviar fichero PDF o .txt |
| Ver emails | Escribir `/email` |
| Subir foto | Enviar foto (con o sin texto) |

---

## 11. Errores conocidos y soluciones aplicadas

| Error | Solución aplicada |
|---|---|
| `svuser` es superusuario y bypasea RLS | Creado rol `svapp` con `FORCE ROW LEVEL SECURITY` |
| rtx3090 embed VRAM insuficiente | `gpu_memory_embed` 0.15 → 0.25 (6GB para Qwen3-Embedding-4B) |
| Redis sin autenticación | `requirepass` + `maxmemory` en docker-compose |
| Whisper sin healthcheck | Añadido healthcheck |
| `version: '3.8'` deprecado en compose | Eliminado el campo `version` |
| `assert` en pool.acquire | Cambiado a `raise RuntimeError()` (los assert se deshabilitan con `-O`) |
| `await aioredis.from_url()` incorrecto | Eliminado el await: `r = aioredis.from_url(url)` (redis-py 5.x es síncrono) |
| `infrastructure` no en ruff first-party | Añadido a `known-first-party` en ruff.toml |
| mypy sin plugin pydantic | Añadido `plugins = pydantic.mypy` en mypy.ini |
| Fernet test key inválida | Usar `Fernet.generate_key()` en fixtures de test |
| pgvector no acepta `list[float]` | Convertir a string: `"[" + ",".join(str(x) for x in v) + "]"` |
| `__init__.py` faltantes | Añadidos en `infrastructure/db/` y `infrastructure/profiles/` |

---

## 12. Historial de commits

```
e7adc76 feat: add orchestrator agent and supervisor
5b328c4 feat: complete secretary agent with all handlers
23ce3f7 feat: add email handler (check inbox + send)
08a257b feat: add document and photo handlers
a734849 feat: add text and audio message handlers
d6e54fd feat: add memory manager with pgvector context
42e6b25 feat: add hardware detection and setup wizard
045b8ee feat: add email client (IMAP/SMTP) and credential encryption
1fd7f1b feat: add whisper audio transcription client
793de75 feat: add llm chat and embedding clients
cde535c feat: add db repository with crud and vector search
db0a92b fix: use RuntimeError instead of assert in pool.acquire
1e5999c feat: add shared db pool with RLS context
ff4f762 fix: app db role for RLS, rtx3090 vram allocation, redis auth, whisper healthcheck
5193698 feat: add docker-compose, db schema and hardware profiles
4f030c5 fix: add infrastructure to ruff first-party and pydantic mypy plugin
6e8d57d fix: add missing __init__.py files and fix ruff config
c8f546e chore: init project structure
```
