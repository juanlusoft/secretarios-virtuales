# Obsidian RAG Integration — Design Spec

## Goal

Sincronizar vaults de Obsidian (compartido + por secretario) con el sistema de embeddings existente en pgvector, de forma que los secretarios puedan consultar automáticamente las notas relevantes al responder.

## Architecture

Un servicio independiente (`obsidian-sync`) escanea los vaults cada 15 minutos, parsea los `.md`, genera embeddings y hace upsert en una nueva tabla `vault_notes`. El `MemoryManager` existente se extiende para buscar en paralelo en `documents` y `vault_notes`, combinando resultados antes de construir el contexto del LLM.

**Tech Stack:** Python 3.11+, `python-frontmatter`, asyncpg, pgvector, systemd, vLLM (embeddings BAAI/bge-m3 1024 dims).

---

## Estructura de vaults

```
$OBSIDIAN_VAULTS_DIR/          (por defecto: /vaults)
  shared/                      ← notas consultables por todos los secretarios
  maria/                       ← notas privadas de María (nombre en minúsculas)
  pedro/                       ← notas privadas de Pedro
  ...
```

El vault personal de cada secretario se resuelve como `{OBSIDIAN_VAULTS_DIR}/{employee_name.lower()}/`. Si el directorio no existe, se ignora sin error.

Solo se indexan ficheros `.md`. Subdirectorios se recorren recursivamente.

---

## Esquema de BD

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
```

- `vault_path`: ruta relativa dentro del vault, ej: `"proyectos/web.md"`
- `modified_at`: mtime del fichero en disco; usado para detectar si re-indexar
- `source`: `'shared'` para notas del vault compartido, `'personal'` para el vault del secretario
- RLS activa igual que en las otras tablas

---

## Módulos nuevos

| Fichero | Responsabilidad |
|---------|----------------|
| `shared/vault/__init__.py` | Exports |
| `shared/vault/parser.py` | `parse_note(path) -> NoteData` — extrae frontmatter, limpia markdown |
| `shared/vault/syncer.py` | `VaultSyncer` — sync de un employee (upsert + eliminación) |
| `shared/vault/cron.py` | Entry point: itera employees activos, llama a VaultSyncer |
| `infrastructure/db/migrations/002_vault_notes.sql` | Migración que crea la tabla |

---

## `shared/vault/parser.py`

```python
@dataclass
class NoteData:
    vault_path: str      # ruta relativa
    title: str           # del frontmatter["title"] o nombre del fichero sin extensión
    tags: list[str]      # del frontmatter["tags"], normalizado
    content_text: str    # cuerpo limpio
    modified_at: datetime
```

**Limpieza del cuerpo:**
1. Extraer frontmatter con `python-frontmatter` (elimina el bloque `---`)
2. Reemplazar `[[Texto del link]]` → `Texto del link` (regex `\[\[([^\]]+)\]\]` → `\1`)
3. Reemplazar `[[link|alias]]` → `alias`
4. Eliminar `#tags` al inicio de línea o como palabras sueltas (`\B#\w+`)
5. Colapsar líneas en blanco múltiples

**Título:** `frontmatter.get("title") or Path(path).stem`

**Tags:** `frontmatter.get("tags", [])` — acepta lista o string separado por comas.

---

## `shared/vault/syncer.py`

```python
class VaultSyncer:
    def __init__(self, pool, employee_id, employee_name, embed, store, vaults_dir)
    async def sync(self) -> SyncResult  # {added, updated, deleted, skipped}
```

**Flujo de `sync()`:**

1. Recopilar todos los `.md` de `vaults_dir/shared/` y `vaults_dir/{employee_name.lower()}/`
2. Para cada fichero:
   - `parse_note(path)` → `NoteData`
   - Consultar `modified_at` en BD para `(employee_id, source, vault_path)`
   - Si `mtime <= modified_at` en BD → skip
   - Si nuevo o modificado → `embed.embed(content_text)` → upsert en `vault_notes`
3. Recopilar `vault_path`s presentes en disco; eliminar de BD los que ya no existen
4. Devolver `SyncResult`

**Upsert SQL:**
```sql
INSERT INTO vault_notes (employee_id, source, vault_path, title, tags, content_text, embedding, modified_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (employee_id, source, vault_path)
DO UPDATE SET title=$4, tags=$5, content_text=$6, embedding=$7, modified_at=$8, indexed_at=NOW()
WHERE vault_notes.modified_at < EXCLUDED.modified_at
```

---

## `shared/vault/cron.py`

Entry point del servicio systemd. Bucle infinito con sleep de `OBSIDIAN_SYNC_INTERVAL` segundos (default 900).

```python
async def run_once(pool, embed, store, vaults_dir):
    employees = await fetch_active_employees(pool)
    for emp in employees:
        syncer = VaultSyncer(pool, emp.id, emp.name, embed, store, vaults_dir)
        result = await syncer.sync()
        logger.info("Sync %s: +%d ~%d -%d skip%d", emp.name, result.added, ...)
```

Si `OBSIDIAN_VAULTS_DIR` no está definida, `cron.py` imprime aviso y termina sin error — **no rompe el resto del sistema**.

---

## Cambios en código existente

### `shared/db/repository.py`

Añadir método:
```python
async def search_vault_notes(self, embedding: list[float], limit: int = 3) -> list[VaultNote]:
    # SELECT ... ORDER BY embedding <=> $1 LIMIT $2
    # WHERE employee_id = current_employee_id (via RLS) OR source = 'shared'
```

Las notas `shared` requieren una consulta ligeramente distinta: se buscan con el `employee_id` del secretario pero sin filtro de RLS estricto en `shared`. Solución: la política RLS para `vault_notes` permite SELECT si `source='shared'` OR `employee_id = current_setting(...)`.

### `secretary/memory.py`

Extender `build_context()`:
```python
docs, vault_notes, convs = await asyncio.gather(
    repo.search_documents(embedding, limit=3),
    repo.search_vault_notes(embedding, limit=3),
    repo.get_recent_conversations(limit=8),
)
```

Formato en contexto:
- Notas `shared`: `[Base de conocimiento] {title}\n{content_text}`
- Notas `personal`: `[Notas personales] {title}\n{content_text}`

### `infrastructure/db/init.sql`

Añadir la tabla `vault_notes` y la política RLS al final del fichero de init.

### `pyproject.toml`

Añadir dependencia: `"python-frontmatter>=1.1,<2"`

### `infrastructure/systemd/obsidian-sync.service` (nuevo)

Servicio systemd que ejecuta `python -m shared.vault.cron` con las variables de entorno necesarias.

---

## Variables de entorno nuevas

| Variable | Descripción | Default |
|----------|-------------|---------|
| `OBSIDIAN_VAULTS_DIR` | Ruta base de los vaults en el servidor | (ninguno — feature desactivada si no se define) |
| `OBSIDIAN_SYNC_INTERVAL` | Segundos entre ciclos de sync | `900` |

---

## Política RLS para `vault_notes`

```sql
ALTER TABLE vault_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY vault_notes_isolation ON vault_notes
    USING (
        source = 'shared'
        OR employee_id = current_setting('app.current_employee_id')::uuid
    );
```

Esto permite que cualquier secretario lea las notas `shared`, pero solo las suyas `personal`.

---

## Dependencias nuevas

- `python-frontmatter>=1.1,<2` — parsing de frontmatter YAML en markdown

---

## Tests

| Fichero | Qué testea |
|---------|-----------|
| `tests/vault/test_parser.py` | `parse_note`: frontmatter, wikilinks, tags, título por defecto |
| `tests/vault/test_syncer.py` | Upsert, skip por mtime, eliminación de notas borradas (mocks de DB y embed) |
