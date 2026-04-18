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
