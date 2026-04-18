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
