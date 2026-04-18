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
