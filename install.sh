#!/usr/bin/env bash
# install.sh — Secretarios Virtuales
# Uso: cd secretarios-virtuales && bash install.sh
# Requiere: Ubuntu 22.04/24.04, conexión a internet, GPU NVIDIA recomendada.

set -euo pipefail

# ─── Colores ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $*${NC}"; }
info() { echo -e "${CYAN}ℹ  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
fail() { echo -e "${RED}❌ $*${NC}"; exit 1; }
step() { echo -e "\n${BOLD}══ $* ${NC}"; }

# ─── Variables globales ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="secretarios"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN=""
GPU_AVAILABLE=false

# ─── Comprobación inicial ────────────────────────────────────────────────────
echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║        SECRETARIOS VIRTUALES — INSTALADOR           ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}\n"

# Detectar ejecución via bash <(curl...) — SCRIPT_DIR sería /dev/fd o similar
if [[ ! -f "$SCRIPT_DIR/pyproject.toml" ]]; then
    echo -e "${RED}❌ Ejecuta el script desde dentro del repositorio clonado:${NC}"
    echo ""
    echo -e "  git clone https://github.com/juanlusoft/secretarios-virtuales.git"
    echo -e "  cd secretarios-virtuales"
    echo -e "  bash install.sh"
    echo ""
    exit 1
fi

if [[ $EUID -eq 0 ]]; then
    fail "No ejecutes este script como root. Ejecútalo con tu usuario normal."
fi

if ! command -v sudo &>/dev/null; then
    fail "sudo no está disponible. Instálalo primero: apt install sudo"
fi

# Actualizar repo si estamos en git
if [[ -d "$SCRIPT_DIR/.git" ]]; then
    info "Actualizando repositorio..."
    git -C "$SCRIPT_DIR" pull --ff-only 2>/dev/null && ok "Repositorio actualizado" || warn "No se pudo hacer git pull (continuando)"
fi

# ─── 1. Sistema base ─────────────────────────────────────────────────────────
step "1/7 · Actualizando lista de paquetes"
sudo apt-get update -qq
ok "Lista de paquetes actualizada"

# ─── 2. Python 3.11+ ────────────────────────────────────────────────────────
step "2/7 · Python 3.11+"

if command -v python3.11 &>/dev/null; then
    ok "Python 3.11 ya instalado: $(python3.11 --version)"
    PYTHON_BIN="$(command -v python3.11)"
elif command -v python3.12 &>/dev/null; then
    ok "Python 3.12 detectado (compatible): $(python3.12 --version)"
    PYTHON_BIN="$(command -v python3.12)"
    sudo apt-get install -y python3.12-venv python3.12-dev build-essential
else
    info "Python 3.11 no encontrado. Instalando via deadsnakes PPA..."
    sudo apt-get install -y software-properties-common
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt-get update -qq
    sudo apt-get install -y python3.11 python3.11-venv python3.11-dev build-essential
    ok "Python 3.11 instalado"
    PYTHON_BIN="$(command -v python3.11)"
fi

# ─── 3. uv ──────────────────────────────────────────────────────────────────
step "3/7 · uv (gestor de paquetes Python)"

# Asegurar rutas de uv en PATH
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if command -v uv &>/dev/null; then
    ok "uv ya instalado: $(uv --version)"
else
    info "Instalando uv (última versión estable)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Cargar env si existe
    [[ -f "$HOME/.local/bin/env" ]] && source "$HOME/.local/bin/env" || true
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv &>/dev/null || fail "No se pudo localizar uv. Abre una nueva terminal y vuelve a ejecutar el script."
    ok "uv instalado: $(uv --version)"
fi

# ─── 4. Docker ───────────────────────────────────────────────────────────────
step "4/7 · Docker"

if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    ok "Docker ya instalado y en ejecución: $(docker --version)"
else
    if command -v docker &>/dev/null; then
        warn "Docker está instalado pero no accesible. Añadiendo usuario al grupo docker..."
        sudo usermod -aG docker "$USER"
        warn "Puede que necesites cerrar sesión y volver a entrar."
    else
        info "Docker no encontrado. Instalando..."
        curl -fsSL https://get.docker.com | sudo bash
        sudo usermod -aG docker "$USER"
        ok "Docker instalado"
        warn "Se te ha añadido al grupo 'docker'. Si falla por permisos, cierra sesión y vuelve a entrar."
    fi
    if ! docker info &>/dev/null 2>&1; then
        sudo docker info &>/dev/null 2>&1 && DOCKER_CMD="sudo docker" || DOCKER_CMD="docker"
    fi
fi
DOCKER_CMD="${DOCKER_CMD:-docker}"

# ─── 5. GPU NVIDIA ───────────────────────────────────────────────────────────
step "5/7 · GPU NVIDIA y Container Toolkit"

detect_nvidia_smi() {
    command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1
}

detect_gpu_pci() {
    lspci 2>/dev/null | grep -qi nvidia
}

install_nvidia_drivers() {
    info "Detectando GPU NVIDIA via PCI..."
    if ! detect_gpu_pci; then
        warn "No se detectó ninguna GPU NVIDIA en el sistema."
        warn "El sistema puede ejecutarse en modo CPU pero los modelos LLM serán muy lentos."
        read -rp "  ¿Continuar sin GPU? [s/N] " ans
        [[ "${ans,,}" == "s" ]] || fail "Instalación cancelada por el usuario."
        return
    fi

    ok "GPU NVIDIA detectada por PCI"
    info "Buscando versión de driver recomendada..."

    if ! command -v ubuntu-drivers &>/dev/null; then
        sudo apt-get install -y ubuntu-drivers-common
    fi

    RECOMMENDED=$(ubuntu-drivers devices 2>/dev/null | grep recommended | awk '{print $3}' | head -1)
    if [[ -z "$RECOMMENDED" ]]; then
        RECOMMENDED="nvidia-driver-550"
        warn "No se pudo determinar el driver recomendado. Usando: $RECOMMENDED"
    else
        info "Driver recomendado: $RECOMMENDED"
    fi

    read -rp "  ¿Instalar $RECOMMENDED ahora? (requiere reinicio) [S/n] " ans
    if [[ "${ans,,}" != "n" ]]; then
        sudo apt-get install -y "$RECOMMENDED"
        ok "Driver $RECOMMENDED instalado."
        echo -e "\n${YELLOW}${BOLD}El sistema necesita reiniciarse para activar los drivers NVIDIA.${NC}"
        echo -e "${YELLOW}Tras el reinicio, vuelve a ejecutar: ${BOLD}bash install.sh${NC}"
        read -rp "  ¿Reiniciar ahora? [S/n] " reboot_ans
        [[ "${reboot_ans,,}" == "n" ]] || sudo reboot
        exit 0
    else
        warn "Saltando instalación de drivers. Continuando sin GPU."
    fi
}

install_nvidia_container_toolkit() {
    info "Instalando NVIDIA Container Toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
    ok "NVIDIA Container Toolkit instalado"
}

if detect_nvidia_smi; then
    ok "Drivers NVIDIA ya instalados: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
    GPU_AVAILABLE=true
else
    install_nvidia_drivers
    if detect_nvidia_smi; then
        GPU_AVAILABLE=true
    fi
fi

if $GPU_AVAILABLE; then
    if dpkg -l nvidia-container-toolkit &>/dev/null 2>&1; then
        ok "NVIDIA Container Toolkit ya instalado"
    else
        install_nvidia_container_toolkit
    fi

    info "Verificando acceso GPU desde Docker..."
    if $DOCKER_CMD run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
        ok "Docker accede correctamente a la GPU"
    else
        warn "Docker no pudo acceder a la GPU. Si persiste: sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
    fi
fi

# ─── 6. Entorno Python del proyecto ─────────────────────────────────────────
step "6/7 · Entorno Python y dependencias del proyecto"

cd "$SCRIPT_DIR"

# Corregir permisos de carpetas que Docker crea como root
if [[ -d "$SCRIPT_DIR/infrastructure/data" ]]; then
    sudo chown -R "$(id -u):$(id -g)" "$SCRIPT_DIR/infrastructure/data" 2>/dev/null || true
fi

if [[ -d "$VENV_DIR" ]]; then
    ok "Entorno virtual ya existe en $VENV_DIR"
else
    info "Creando entorno virtual con uv..."
    uv venv "$VENV_DIR" --python python3.11
    ok "Entorno virtual creado"
fi

info "Instalando dependencias Python..."
uv pip install --python "$VENV_DIR/bin/python" -e ".[dev]"
ok "Dependencias instaladas"

PYTHON_VENV="$VENV_DIR/bin/python"

# ─── 7. Configuración del proyecto ──────────────────────────────────────────
step "7/7 · Configuración del proyecto"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    ok ".env ya existe"
    read -rp "  ¿Volver a ejecutar el wizard de configuración? [s/N] " rerun_wizard
    if [[ "${rerun_wizard,,}" == "s" ]]; then
        "$PYTHON_VENV" -m infrastructure.setup
    fi
else
    info "Ejecutando wizard de configuración..."
    "$PYTHON_VENV" -m infrastructure.setup
fi

# ─── Servicio systemd ────────────────────────────────────────────────────────
step "Configurando arranque automático (systemd)"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CURRENT_USER="$USER"

info "Creando $SERVICE_FILE ..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Secretarios Virtuales
Documentation=https://github.com/juanlusoft/secretarios-virtuales
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=${CURRENT_USER}
Group=${CURRENT_USER}
WorkingDirectory=${SCRIPT_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=${SCRIPT_DIR}/.env
ExecStartPre=/bin/bash -c '${DOCKER_CMD} compose --env-file ${SCRIPT_DIR}/.env -f ${SCRIPT_DIR}/infrastructure/docker-compose.yml --profile gpu up -d --remove-orphans'
ExecStart=${VENV_DIR}/bin/python -m supervisor
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

ok "Fichero de servicio creado"

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
ok "Servicio '$SERVICE_NAME' habilitado para arranque automático"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    info "Limpiando contenedores huérfanos..."
    $DOCKER_CMD container prune -f &>/dev/null || true

    info "Arrancando servicios Docker (postgres, redis)..."
    $DOCKER_CMD compose --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/infrastructure/docker-compose.yml" up -d postgres redis --remove-orphans

    if $GPU_AVAILABLE; then
        info "Arrancando modelos de IA (vLLM + Whisper) en Docker..."
        $DOCKER_CMD compose --env-file "$SCRIPT_DIR/.env" -f "$SCRIPT_DIR/infrastructure/docker-compose.yml" --profile gpu up -d --remove-orphans
        info "Los modelos pueden tardar 5-15 minutos en cargar la primera vez."
        info "Progreso: docker logs sv-vllm-chat -f"
    else
        warn "Sin GPU: los servicios de IA no se han arrancado."
        warn "Cuando tengas GPU: docker compose -f infrastructure/docker-compose.yml --profile gpu up -d"
    fi

    info "Arrancando servicio systemd..."
    sudo systemctl start "$SERVICE_NAME"
    sleep 3
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Servicio '$SERVICE_NAME' arrancado correctamente"
    else
        warn "El servicio no está activo todavía. Comprueba: journalctl -u $SERVICE_NAME -f"
    fi
fi

# ─── Resumen final ────────────────────────────────────────────────────────────
echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              INSTALACIÓN COMPLETADA                 ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Comandos útiles:${NC}"
echo -e "  • Ver estado:     ${BOLD}sudo systemctl status $SERVICE_NAME${NC}"
echo -e "  • Ver logs:       ${BOLD}journalctl -u $SERVICE_NAME -f${NC}"
echo -e "  • Parar:          ${BOLD}sudo systemctl stop $SERVICE_NAME${NC}"
echo -e "  • Reiniciar:      ${BOLD}sudo systemctl restart $SERVICE_NAME${NC}"
echo -e "  • Logs vLLM:      ${BOLD}docker logs sv-vllm-chat -f${NC}"
echo -e "  • Logs Postgres:  ${BOLD}docker logs sv-postgres -f${NC}"
echo ""
if $GPU_AVAILABLE; then
    echo -e "  ${GREEN}GPU detectada — sistema listo para producción${NC}"
else
    echo -e "  ${YELLOW}Sin GPU — arranca los modelos cuando tengas hardware disponible${NC}"
fi
echo ""
