# Fixes de Auditoría (Plan de Remediación)

Fecha: 2026-04-18  
Repositorio: `juanlusoft/secretarios-virtuales`

## Objetivo
Aplicar correcciones priorizadas para cerrar riesgos de seguridad, disponibilidad y fiabilidad detectados en la auditoría.

## Prioridad P0 (inmediata)

### 1) Bloquear path traversal en subida de documentos
Problema:
- Se usa `filename` sin saneado al construir `filepath`.
- Riesgo de escribir fuera de `DOCUMENTS_DIR`.

Fix:
- Normalizar el nombre con `Path(filename).name`.
- Rechazar nombres vacíos o reservados.
- Resolver ruta final y validar que quede dentro de `employee_dir`.

Aceptación:
- Un nombre como `../../etc/passwd` no debe escapar del directorio del empleado.
- Test unitario específico de traversal.

---

### 2) Activar listener Redis en cada secretario
Problema:
- `_listen_redis()` existe pero no se lanza en `run()`.
- Los mensajes admin publicados no llegan al secretario.

Fix:
- Arrancar listener y polling de Telegram en paralelo.
- Cerrar recursos Redis en shutdown.
- Manejar reconexión en caídas de Redis.

Aceptación:
- `send_message_to_secretary()` provoca entrega al chat del empleado.
- Test de integración con `publish -> consume`.

---

### 3) Usar rol DB de aplicación (`APP_DB_URL`) para runtime
Problema:
- Runtime usa `DATABASE_URL` (rol más privilegiado).
- `APP_DB_URL` está definido pero no usado.

Fix:
- `secretary`, `orchestrator` y `supervisor` deben usar `APP_DB_URL`.
- Mantener `DATABASE_URL` sólo para bootstrap/administración.
- Verificar permisos mínimos necesarios del rol `svapp`.

Aceptación:
- Servicios funcionales con `APP_DB_URL`.
- Consultas y escrituras pasan bajo RLS y mínimo privilegio.

## Prioridad P1 (esta semana)

### 4) Declarar `pypdf` en dependencias
Problema:
- Se importa `pypdf` pero no está en `pyproject.toml`.

Fix:
- Añadir `pypdf` en dependencias de runtime.
- Añadir test que valide extracción de texto PDF real simple.

Aceptación:
- Entorno limpio instala todo y procesa PDF sin fallback silencioso.

---

### 5) Supervisar y reiniciar orquestador si cae
Problema:
- El proceso orquestador se crea pero no se monitoriza para autorestart.

Fix:
- Extender `_monitor_processes()` para cubrir `orchestrator_proc`.
- Aplicar backoff/retry y logging de causa.

Aceptación:
- Simular caída del orquestador y verificar reinicio automático.

---

### 6) Forzar `chat_id` obligatorio al crear secretario
Problema:
- Parser permite crear secretario sin `chat_id` (`""`).

Fix:
- Hacer `chat_id` obligatorio en parser y validación de servicio.
- Mensaje de error claro al operador.

Aceptación:
- Comando sin `chat_id` devuelve error y no crea empleado.

## Prioridad P2 (hardening)

### 7) Endurecer instalación (`curl | sh`)
Problema:
- Instalación de `uv` sin verificación de integridad.

Fix:
- Añadir validación de checksum/firma o método de instalación paquetizado.
- Documentar versión fija soportada.

Aceptación:
- Instalación reproducible y verificable.

## Cambios de tests recomendados

- `tests/secretary/test_handler_document.py`
  - Caso traversal con `../`.
  - Caso nombre vacío/normalizado.
- `tests/secretary/test_agent.py`
  - Caso de arranque de listener Redis y entrega de mensaje admin.
- `tests/supervisor/test_supervisor.py`
  - Caso de reinicio de orquestador tras caída.
- `tests/orchestrator/test_parser.py`
  - Comando create sin `chat_id` debe fallar.

## Orden de implementación sugerido

1. P0.1 Path traversal  
2. P0.2 Listener Redis  
3. P0.3 APP_DB_URL  
4. P1.4 pypdf  
5. P1.5 restart orquestador  
6. P1.6 chat_id obligatorio  
7. P2.7 hardening instalador

## Criterio de cierre

- Todos los fixes P0 y P1 merged.
- Tests nuevos y existentes en verde.
- Validación manual mínima:
  - envío admin via Redis,
  - subida de documento con nombre malicioso,
  - arranque de servicios con `APP_DB_URL`.
