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
