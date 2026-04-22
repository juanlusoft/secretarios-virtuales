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
    {
        "type": "function",
        "function": {
            "name": "calendar_list",
            "description": "Lista los eventos del calendario en los próximos días.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "Número de días a mirar hacia adelante (por defecto 7)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create",
            "description": "Crea un nuevo evento en el calendario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título del evento"},
                    "start_iso": {"type": "string", "description": "Fecha y hora de inicio en ISO 8601 con zona horaria"},
                    "end_iso": {"type": "string", "description": "Fecha y hora de fin en ISO 8601 con zona horaria"},
                    "description": {"type": "string", "description": "Descripción opcional del evento"},
                    "location": {"type": "string", "description": "Lugar opcional del evento"},
                },
                "required": ["title", "start_iso", "end_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_modify",
            "description": "Modifica un evento existente en el calendario por su ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "ID del evento a modificar"},
                    "title": {"type": "string", "description": "Nuevo título (opcional)"},
                    "start_iso": {"type": "string", "description": "Nueva fecha/hora de inicio ISO 8601 (opcional)"},
                    "end_iso": {"type": "string", "description": "Nueva fecha/hora de fin ISO 8601 (opcional)"},
                    "description": {"type": "string", "description": "Nueva descripción (opcional)"},
                    "location": {"type": "string", "description": "Nuevo lugar (opcional)"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_cancel",
            "description": "Cancela y elimina un evento del calendario por su ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "ID del evento a cancelar"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_send",
            "description": "Envía un email a un destinatario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Dirección de email del destinatario"},
                    "subject": {"type": "string", "description": "Asunto del email"},
                    "body": {"type": "string", "description": "Cuerpo del email en texto plano"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_read",
            "description": "Lee los emails recientes de la bandeja de entrada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Número máximo de emails a leer (por defecto 5)"},
                },
            },
        },
    },
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
]
