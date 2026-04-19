import subprocess
import sys
import time
from pathlib import Path

from .detect_hardware import detect_hardware
from .generate_config import generate_env


def ask(prompt: str, secret: bool = False) -> str:
    import getpass

    if secret:
        return getpass.getpass(f"  {prompt}: ").strip()
    return input(f"  {prompt}: ").strip()


def main() -> None:
    print("\n============================================")
    print("  SECRETARIOS VIRTUALES - INSTALACION")
    print("============================================\n")

    print("[1/5] Detectando hardware...")
    profile = detect_hardware()
    if profile.max_users == 0:
        print("ERROR: No se detecto GPU NVIDIA. Se necesita GPU para ejecutar modelos.")
        sys.exit(1)

    print(f"Perfil: {profile.name}")
    print(f"Modelo chat: {profile.chat_model}")
    print(f"Modelo embedding: {profile.embedding_model}")
    print(f"Usuarios maximos: {profile.max_users}\n")

    answers = {
        "hf_token": ask("HuggingFace token (hf_...)"),
        "bot_token": ask("Token bot Telegram del orquestador"),
        "chat_id": ask("Tu chat_id de Telegram"),
        "db_password": ask("Contrasena BD (Enter para generar automaticamente)"),
    }

    print("[2/5] Generando .env ...")
    env_content = generate_env(profile, answers)
    Path(".env").write_text(env_content, encoding="utf-8")

    app_db_password = ""
    for line in env_content.splitlines():
        if line.startswith("APP_DB_PASSWORD="):
            app_db_password = line.split("=", 1)[1].strip()
            break
    if not app_db_password:
        print("ERROR: APP_DB_PASSWORD no encontrado en .env")
        sys.exit(1)

    print("[3/5] Levantando PostgreSQL y Redis...")
    # Eliminar contenedores huérfanos con nombres de hash antes de levantar
    for name in ("sv-postgres", "sv-redis"):
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "infrastructure/docker-compose.yml",
            "up",
            "-d",
            "postgres",
            "redis",
            "--remove-orphans",
        ],
        check=True,
    )

    print("Esperando PostgreSQL...")
    time.sleep(8)

    print("[4/5] Configurando password segura de svapp...")
    escaped_password = app_db_password.replace("'", "''")
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "infrastructure/docker-compose.yml",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "svuser",
            "-d",
            "secretarios",
            "-c",
            f"ALTER ROLE svapp WITH PASSWORD '{escaped_password}';",
        ],
        check=True,
    )

    print("[5/5] Instalacion completada")
    print("Siguiente paso:")
    print("  python -m supervisor")


if __name__ == "__main__":
    main()
