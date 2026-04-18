# Secretarios Virtuales

Sistema multi-agente de secretarios virtuales vía Telegram con LLMs locales, PostgreSQL/pgvector y procesamiento de audio, documentos e imágenes.

Cada empleado dispone de su propio bot de Telegram con memoria semántica, búsqueda de documentos y transcripción de voz — todo ejecutándose en tu propio hardware, sin enviar datos a terceros.

---

## Características

- **Bot personal por empleado** — cada usuario interactúa con su propio bot de Telegram
- **Memoria semántica** — recuerda conversaciones anteriores y busca en documentos mediante pgvector
- **Voz a texto** — transcripción de mensajes de audio con Faster-Whisper
- **Análisis de documentos** — sube PDFs y consulta su contenido con lenguaje natural
- **Análisis de imágenes** — descripción e interpretación de fotos con LLM multimodal
- **Integración de email** — consulta y resumen del buzón de correo
- **100% local** — los modelos LLM se ejecutan en tu GPU con vLLM; ningún dato sale de tu servidor
- **Aislamiento multi-tenant** — Row-Level Security en PostgreSQL garantiza que cada empleado solo accede a sus datos
- **Alta disponibilidad** — el Supervisor reinicia automáticamente cualquier bot que falle

---

## Arquitectura

```
Supervisor (gestor de procesos)
├── Orchestrator (bot admin)       ← tú lo controlas
├── Secretario_1 (bot empleado 1)
├── Secretario_2 (bot empleado 2)
└── ...

Servicios Docker
├── PostgreSQL 16 + pgvector   (puerto 5432)
├── Redis 7                    (puerto 6379)
├── vLLM Chat                  (puerto 8000)
├── vLLM Embeddings            (puerto 8001)
└── Faster-Whisper             (puerto 9000)
```

Cada secretario es un proceso Python independiente. Los fallos están aislados: si un bot cae, los demás siguen funcionando. El Supervisor lo detecta y lo reinicia.

---

## Requisitos

| Componente | Mínimo |
|-----------|--------|
| SO | Ubuntu 22.04 / 24.04 Server |
| GPU | NVIDIA con 8 GB VRAM (recomendado 24 GB+) |
| RAM | 16 GB |
| Disco | 100 GB libres (modelos LLM) |
| Python | 3.11+ |
| Docker | 24.0+ |

### Perfiles de hardware

El instalador detecta la GPU automáticamente y selecciona los modelos adecuados:

| Perfil | VRAM | Modelo Chat | Modelo Embeddings | Usuarios |
|--------|------|------------|-------------------|----------|
| `spark` | 48 GB+ | Qwen3-30B-A3B-FP8 | Qwen3-Embedding-4B | 20 |
| `rtx3090` | 24 GB | Qwen2.5-14B-FP8 | Qwen3-Embedding-4B | 10 |
| `rtx3080_12gb` | 12 GB | Qwen2.5-7B-FP8 | BAAI/bge-m3 | 5 |
| `rtx3080ti_8gb` | 8 GB | Qwen2.5-3B-FP8 | BAAI/bge-small-en | 3 |

---

## Instalación

### Instalación automática (recomendada)

```bash
git clone https://github.com/juanlusoft/secretarios-virtuales.git
cd secretarios-virtuales
bash install.sh
```

El script se encarga de:
1. Instalar Python 3.11+ (compatible con Ubuntu 22.04 y 24.04)
2. Instalar Docker y NVIDIA Container Toolkit
3. Instalar drivers NVIDIA (pide reinicio si es necesario)
4. Crear el entorno virtual e instalar dependencias
5. Lanzar el wizard de configuración (genera `.env`)
6. Registrar el servicio systemd para arranque automático

### Instalación manual

```bash
# 1. Clonar el repositorio
git clone https://github.com/juanlusoft/secretarios-virtuales.git
cd secretarios-virtuales

# 2. Crear entorno virtual
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Instalar dependencias
pip install -e ".[dev]"

# 4. Configurar el entorno (wizard interactivo)
python -m infrastructure.setup

# 5. Arrancar servicios Docker
docker compose -f infrastructure/docker-compose.yml --profile gpu up -d

# 6. Arrancar el supervisor
python -m supervisor
```

---

## Configuración

Copia `.env.example` a `.env` y rellena los valores. El wizard de configuración (`python -m infrastructure.setup`) lo genera automáticamente.

### Variables principales

```env
# Base de datos
POSTGRES_USER=svuser
POSTGRES_PASSWORD=svpassword
DATABASE_URL=postgresql://svuser:svpassword@localhost:5432/secretarios
APP_DB_PASSWORD=<auto-generada por setup>
APP_DB_URL=postgresql://svapp:${APP_DB_PASSWORD}@localhost:5432/secretarios

# Redis
REDIS_PASSWORD=svredispass
REDIS_URL=redis://:svredispass@localhost:6379

# LLM (auto-configurado según hardware)
VLLM_CHAT_URL=http://localhost:8000/v1
VLLM_EMBED_URL=http://localhost:8001/v1
CHAT_MODEL=Qwen/Qwen2.5-14B-Instruct-FP8
EMBEDDING_MODEL=Qwen3-Embedding-4B

# HuggingFace (para descargar modelos)
HF_TOKEN=hf_xxxxxxxxxxxx

# Bot administrador (Orchestrator)
ORCHESTRATOR_BOT_TOKEN=<token del bot de Telegram>
ORCHESTRATOR_CHAT_ID=<tu chat ID de Telegram>

# Seguridad (auto-generado)
FERNET_KEY=<clave Fernet de 32 bytes en base64>

# Hardware
HARDWARE_PROFILE=rtx3090
```

---

## Uso

### Para el administrador

Habla con el **bot Orchestrator** para gestionar los secretarios:

```
# Crear un secretario para un empleado
crea secretario para María, token: 123456:ABC..., chatid: 987654321

# Ver secretarios activos
lista los secretarios

# Enviar aviso a un empleado
avisa a María que el sistema se reinicia esta noche

# Dar de baja un secretario
destruye secretario de María
```

### Para los empleados

Cada empleado usa su propio bot de Telegram:

**Consultas de texto:**
```
Usuario: ¿Cuándo es la próxima reunión de equipo?
Bot: Según tus notas, la próxima reunión es el jueves a las 10:00...
```

**Notas de voz:**
```
Usuario: [audio] "Recuerda llamar a Carlos mañana por la mañana"
Bot: Anotado. Te recuerdo que tienes que llamar a Carlos mañana.
```

**Documentos:**
```
Usuario: [sube PDF] "Contrato_2024.pdf"
Usuario: ¿Cuál es la fecha de vencimiento del contrato?
Bot: Según el documento "Contrato_2024.pdf", el contrato vence el 31 de diciembre de 2024.
```

**Email:**
```
Usuario: /email
Bot: Tienes 2 correos nuevos:
  1. cliente@empresa.com — "Presupuesto aprobado"
  2. rrhh@empresa.com — "Recordatorio: evaluación anual"
```

---

## Gestión del servicio

```bash
# Estado del servicio
sudo systemctl status secretarios

# Ver logs en tiempo real
journalctl -u secretarios -f

# Reiniciar
sudo systemctl restart secretarios

# Parar
sudo systemctl stop secretarios

# Logs de los modelos LLM
docker logs sv-vllm-chat -f

# Estado de la GPU
nvidia-smi
```

---

## Estructura del proyecto

```
secretarios-virtuales/
├── secretary/              # Agente por empleado
│   ├── agent.py            # Lógica principal del bot
│   ├── memory.py           # Contexto semántico (RAG)
│   └── handlers/           # Manejadores por tipo de mensaje
│       ├── text.py
│       ├── audio.py
│       ├── document.py
│       ├── photo.py
│       └── email.py
├── orchestrator/           # Bot administrador
│   ├── agent.py
│   ├── parser.py           # Parsing de comandos en lenguaje natural
│   └── admin.py
├── supervisor/             # Gestor de procesos
│   └── supervisor.py
├── shared/                 # Utilidades compartidas
│   ├── llm/                # Clientes vLLM (chat + embeddings)
│   ├── db/                 # Pool de conexiones + repositorio con RLS
│   ├── audio/              # Cliente Whisper
│   ├── email/              # Cliente IMAP/SMTP async
│   └── crypto.py           # Cifrado Fernet para credenciales
├── infrastructure/
│   ├── docker-compose.yml
│   ├── db/init.sql         # Schema + RLS policies
│   ├── profiles/           # Perfiles de hardware
│   └── setup/              # Wizard de configuración
├── install.sh              # Instalador automático
└── .env.example            # Plantilla de configuración
```

---

## Seguridad

- **Aislamiento de datos:** PostgreSQL Row-Level Security garantiza que cada bot solo accede a los datos de su empleado, incluso compartiendo la misma base de datos.
- **Credenciales cifradas:** Los tokens de Telegram y credenciales de email se almacenan cifrados con Fernet.
- **Acceso restringido:** Cada bot solo responde al `chat_id` autorizado de su empleado.
- **Sin dependencias cloud:** Los LLMs se ejecutan localmente. Ningún mensaje sale de tu servidor.
- **Mínimo privilegio en runtime:** los procesos principales usan `APP_DB_URL` para operar con el rol `svapp` sujeto a RLS.
- **Resiliencia de control:** el listener de ciclo de vida en Redis (supervisor) reintenta con backoff automático ante fallos de red.

### Hardening aplicado (2026-04-19)

Cambios cerrados para producción:

1. **Redis lifecycle robusto**
   - Reintento con backoff exponencial en `supervisor._listen_lifecycle()` para reconectar automáticamente si Redis cae.
2. **Sin contraseña estática de `svapp`**
   - `init.sql` ya no define password hardcodeada.
   - `infrastructure.setup` genera `APP_DB_PASSWORD` aleatoria y ejecuta `ALTER ROLE svapp ...`.
3. **Instalación de `uv` con verificación de integridad**
   - `install.sh` valida SHA256 del instalador antes de ejecutarlo.
4. **Reducción de superficie privilegiada**
   - `secretary`, `orchestrator` y `supervisor` arrancan con `APP_DB_URL` (fallback a `DATABASE_URL` solo por compatibilidad).

Validación actual del repo tras hardening:

- `python -m ruff check .` -> OK
- `python -m mypy shared secretary orchestrator supervisor infrastructure` -> OK
- `python -m pytest -q` -> OK (`42 passed`, `5 skipped` por tests de integración DB si PostgreSQL local no está levantado)

---

## Licencia

MIT — consulta el archivo [LICENSE](LICENSE) para más detalles.
