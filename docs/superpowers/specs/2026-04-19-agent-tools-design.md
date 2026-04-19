# Agent Tools — Design Spec

## Goal

Añadir capacidades de ejecución real al orquestador y a secretarios con permisos: bash local, SSH remoto y operaciones de ficheros. El LLM decide qué herramienta usar mediante function calling (OpenAI tool_choice), ejecuta en silencio y entrega un resumen al final.

## Architecture

### Nuevo módulo `shared/tools/`

| Fichero | Responsabilidad |
|---------|----------------|
| `definitions.py` | Esquemas JSON de las 7 herramientas (formato OpenAI functions) |
| `executor.py` | `ToolExecutor`: ejecuta bash local, SSH remoto, ops de ficheros |
| `ssh_store.py` | Guarda/carga conexiones SSH cifradas en `credentials` |
| `safety.py` | Detecta comandos destructivos para pedir confirmación |

### Cambios en código existente

- **`shared/llm/chat.py`** — `complete()` acepta parámetro opcional `tools: list[dict] | None`. Si se pasa, activa el bucle de herramientas (máx. 10 iteraciones).
- **`secretary/agent.py`** — Añade `/superuser`, timer de inactividad, flag `_tools_enabled`, y lógica de confirmación para destructivos.
- **`orchestrator/agent.py`** — Herramientas siempre activas, se pasa `ToolExecutor` al construir.
- **`orchestrator/admin.py`** — `create_secretary()` acepta `tools_enabled: bool`. Se guarda como `credentials(service_type='tools_enabled', encrypted='true')`.
- **`secretary/__main__.py`** — Lee `tools_enabled` de credentials al arrancar y pasa el flag al agente.

---

## Herramientas (7)

### `bash`
```json
{
  "name": "bash",
  "description": "Ejecuta un comando bash en el servidor local donde corre el agente.",
  "parameters": {
    "command": { "type": "string" }
  }
}
```
- Ejecuta con `asyncio.create_subprocess_shell`, timeout 60s.
- Devuelve stdout + stderr (truncado a 4000 chars si excede).

### `ssh_exec`
```json
{
  "name": "ssh_exec",
  "description": "Ejecuta un comando en una conexión SSH guardada por nombre.",
  "parameters": {
    "name": { "type": "string", "description": "Nombre de la conexión guardada" },
    "command": { "type": "string" }
  }
}
```
- Carga credenciales de `credentials(service_type='ssh:{name}')`.
- Usa `asyncssh` para conectar y ejecutar.
- Devuelve stdout + stderr.

### `ssh_save`
```json
{
  "name": "ssh_save",
  "description": "Guarda una nueva conexión SSH cifrada para uso futuro.",
  "parameters": {
    "name": { "type": "string", "description": "Nombre identificador de la conexión" },
    "host": { "type": "string" },
    "user": { "type": "string" },
    "password": { "type": "string", "description": "Contraseña (opcional si se usa ssh_key)" },
    "ssh_key": { "type": "string", "description": "Clave privada SSH en texto (opcional)" },
    "port": { "type": "integer", "default": 22 }
  }
}
```
- Guarda JSON cifrado con Fernet en `credentials(service_type='ssh:{name}')`.

### `ssh_list`
```json
{
  "name": "ssh_list",
  "description": "Lista todas las conexiones SSH guardadas (sin mostrar credenciales)."
}
```
- Busca en `credentials` todas las filas donde `service_type LIKE 'ssh:%'`.
- Devuelve lista de nombres + host.

### `read_file`
```json
{
  "name": "read_file",
  "description": "Lee el contenido de un fichero del servidor.",
  "parameters": {
    "path": { "type": "string" }
  }
}
```
- Limita a 8000 chars. Si excede, devuelve los primeros 8000 con aviso.

### `write_file`
```json
{
  "name": "write_file",
  "description": "Crea o sobreescribe un fichero con el contenido dado.",
  "parameters": {
    "path": { "type": "string" },
    "content": { "type": "string" }
  }
}
```
- Crea directorios intermedios si no existen (`mkdir -p`).

### `list_dir`
```json
{
  "name": "list_dir",
  "description": "Lista el contenido de un directorio.",
  "parameters": {
    "path": { "type": "string" }
  }
}
```

---

## Bucle de ejecución

```
1. Usuario envía mensaje
2. ChatClient.complete(messages, tools=TOOL_DEFS) → LLM
3. Si LLM devuelve tool_calls:
     a. Para cada tool_call:
        - safety.py comprueba si es destructivo
        - Si destructivo y no superuser: guardar pendiente, pedir confirmación al usuario
        - Si confirmado (o no destructivo o superuser): ToolExecutor.run(tool, args)
        - Añadir resultado al historial como role='tool'
     b. Volver al paso 2
4. Si LLM devuelve texto final (sin tool_calls): devolver texto + lista de herramientas usadas
5. Máx. 10 iteraciones (protección ante bucles infinitos)
```

### Confirmación de destructivos

El agente guarda el comando pendiente en `_pending_confirmation`. En el siguiente mensaje del usuario:
- Si dice "sí/si/yes/y" → ejecuta y continúa el bucle
- Cualquier otra cosa → cancela ese comando, informa al usuario

---

## Modo `/superuser`

- `/superuser` → activa modo, guarda `_superuser_until = now + 30min`
- Cada herramienta ejecutada → resetea `_superuser_until = now + 30min`
- Al verificar si está activo: `now < _superuser_until`
- Si expira: sin notificación, simplemente el siguiente destructivo pedirá confirmación
- Para reactivar: `/superuser` de nuevo

---

## Gestión de conexiones SSH — flujo completo

**Nueva conexión:**
```
Usuario: "conéctate a 192.168.1.10 usuario admin pass 1234"
LLM llama ssh_save con host/user/pass pero sin name
→ agente detecta name vacío → pregunta: "¿Qué nombre le pongo a esta conexión?"
Usuario: "servidor-web"
→ guarda ssh:servidor-web cifrado
→ ejecuta el comando original
```

**Reconexión:**
```
Usuario: "conéctate a servidor-web y dime el espacio en disco"
LLM llama ssh_exec("servidor-web", "df -h") directamente
→ carga credenciales → ejecuta → devuelve resultado
```

**Con SSH key:**
```
Usuario: pega clave privada en el chat + host + user
→ LLM llama ssh_save con ssh_key=<clave>
→ agente pide nombre → guarda cifrado
```

---

## Permisos por secretario

- Al crear un secretario con el orquestador: `"crea un secretario para María con herramientas"` → parser detecta "con herramientas" → `create_secretary(tools_enabled=True)`
- Se guarda: `credentials(service_type='tools_enabled', encrypted=encrypt('true'))`
- Al arrancar el secretario: `secretary/__main__.py` lee `tools_enabled`, pasa `ToolExecutor` al agente si es True

---

## Comandos destructivos detectados

`rm`, `rmdir`, `unlink`, `shred`, `wipefs`, `mkfs`, `dd if=`, `DROP TABLE`, `DROP DATABASE`, `DELETE FROM`, `TRUNCATE`, `kill`, `pkill`, `killall`, `shutdown`, `reboot`, `halt`, `poweroff`, `passwd`, `userdel`, `groupdel`

---

## Dependencias nuevas

- `asyncssh>=2.14,<3` — conexiones SSH async
- Sin más dependencias nuevas (bash local usa stdlib, ficheros usan pathlib)

---

## Ficheros a crear/modificar

**Crear:**
- `shared/tools/__init__.py`
- `shared/tools/definitions.py`
- `shared/tools/executor.py`
- `shared/tools/ssh_store.py`
- `shared/tools/safety.py`

**Modificar:**
- `shared/llm/chat.py` — bucle de tool calling
- `secretary/agent.py` — `/superuser`, `_tools_enabled`, confirmación
- `orchestrator/agent.py` — `ToolExecutor` siempre activo
- `orchestrator/admin.py` — `tools_enabled` en create_secretary
- `orchestrator/parser.py` — detectar "con herramientas" en create command
- `secretary/__main__.py` — leer tools_enabled al arrancar
- `pyproject.toml` — añadir asyncssh
