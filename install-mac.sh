#!/usr/bin/env bash
# install-mac.sh — Secretarios Virtuales macOS
# Detecta el hardware, elige el modelo adecuado e instala todo.
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✅  $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️   $*${NC}"; }
err()  { echo -e "${RED}❌  $*${NC}" >&2; exit 1; }
info() { echo -e "${CYAN}ℹ   $*${NC}"; }
step() { echo -e "\n${BOLD}${BLUE}── $* ──${NC}"; }
ask()  {
    local _var="$1" _prompt="$2" _default="${3:-}"
    printf "${CYAN}▶  $_prompt${_default:+ [${_default}]}${NC}: "
    read -r _input
    eval "$_var=\"\${_input:-$_default}\""
}
ask_secret() {
    local _var="$1" _prompt="$2"
    printf "${CYAN}▶  $_prompt${NC}: "
    read -rs _input; echo
    eval "$_var=\"$_input\""
}

# ─── Precondiciones ──────────────────────────────────────────────────
[[ "$(uname -s)" == "Darwin" ]] || err "Este script solo funciona en macOS."
[[ "$(id -u)" -ne 0 ]]          || err "No ejecutes como root (sin sudo)."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$SCRIPT_DIR/pyproject.toml" ]] || err "Ejecuta desde la raíz del repositorio clonado."

echo -e "${BOLD}${CYAN}"
cat << 'BANNER'
╔═════════════════════════════════════════════╗
║  SECRETARIOS VIRTUALES — Instalador macOS  ║
╚═════════════════════════════════════════════╝
BANNER
echo -e "${NC}"

# ─── 1/8 · Detectar hardware ─────────────────────────────────────────
step "1/8 · Detectando hardware"

ARCH=$(uname -m)
IS_ARM=false
[[ "$ARCH" == "arm64" ]] && IS_ARM=true

if $IS_ARM; then
    CHIP=$(system_profiler SPHardwareDataType 2>/dev/null \
        | awk -F': ' '/Chip:/{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2}')
    [[ -z "$CHIP" ]] && CHIP="Apple Silicon"
else
    CHIP=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Intel")
fi

RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
DISK_FREE_GB=$(df -g / 2>/dev/null | awk 'NR==2{print $4}')
CORES=$(sysctl -n hw.logicalcpu)
MACOS_VER=$(sw_vers -productVersion)

printf "  %-16s %s\n"   "Chip:"         "$CHIP"
printf "  %-16s %s GB\n" "Memoria RAM:"  "$RAM_GB"
printf "  %-16s %s GB\n" "Disco libre:"  "$DISK_FREE_GB"
printf "  %-16s %s cores\n" "CPU:"       "$CORES"
printf "  %-16s %s\n"   "macOS:"         "$MACOS_VER"

# ─── 2/8 · Elegir perfil de modelos ──────────────────────────────────
step "2/8 · Seleccionando perfil de modelos"

# Apple Silicon: memoria unificada → RAM completa disponible para el modelo.
# Intel: solo ~40 % de la RAM es usable para inferencia (el resto lo usa el SO y la GPU discreta).
if $IS_ARM; then
    EFF=$RAM_GB
else
    EFF=$(( RAM_GB * 4 / 10 ))
    warn "Intel Mac detectado: la inferencia será más lenta que en Apple Silicon."
fi

[[ $RAM_GB -ge 8 ]]        || err "Mínimo 8 GB de RAM. Este equipo tiene ${RAM_GB} GB."
[[ $DISK_FREE_GB -ge 15 ]] || err "Mínimo 15 GB libres en disco. Disponible: ${DISK_FREE_GB} GB."

if [[ $EFF -ge 48 ]]; then
    PROFILE="spark";   CHAT_MODEL="qwen2.5:32b";  EMBED_MODEL="mxbai-embed-large"
    EMBED_DIM=1024;    WHISPER_MODEL="large-v3";   MAX_USERS=15; MODEL_GB=22
elif [[ $EFF -ge 24 ]]; then
    PROFILE="potente"; CHAT_MODEL="qwen2.5:14b";  EMBED_MODEL="mxbai-embed-large"
    EMBED_DIM=1024;    WHISPER_MODEL="medium";     MAX_USERS=8;  MODEL_GB=10
elif [[ $EFF -ge 14 ]]; then
    PROFILE="medio";   CHAT_MODEL="qwen2.5:7b";   EMBED_MODEL="nomic-embed-text"
    EMBED_DIM=768;     WHISPER_MODEL="base";       MAX_USERS=5;  MODEL_GB=5
else
    PROFILE="basico";  CHAT_MODEL="qwen2.5:3b";   EMBED_MODEL="nomic-embed-text"
    EMBED_DIM=768;     WHISPER_MODEL="tiny";       MAX_USERS=2;  MODEL_GB=3
fi

NEEDED_GB=$(( MODEL_GB + 5 ))
[[ $DISK_FREE_GB -ge $NEEDED_GB ]] || \
    err "El perfil '${PROFILE}' necesita ~${NEEDED_GB} GB libres. Disponible: ${DISK_FREE_GB} GB."

echo ""
echo -e "  ${BOLD}Perfil elegido: ${GREEN}${PROFILE}${NC}"
echo   "  ├─ Chat:        $CHAT_MODEL"
echo   "  ├─ Embeddings:  $EMBED_MODEL  (${EMBED_DIM}d)"
echo   "  ├─ Whisper:     $WHISPER_MODEL"
echo   "  └─ Max usuarios: $MAX_USERS"
echo ""
ok "Perfil seleccionado"

# ─── 3/8 · Homebrew ──────────────────────────────────────────────────
step "3/8 · Homebrew"

if ! command -v brew &>/dev/null; then
    info "Instalando Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if $IS_ARM; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        grep -q 'brew shellenv' ~/.zprofile 2>/dev/null || \
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    fi
fi
ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"

# ─── 4/8 · Python + uv ───────────────────────────────────────────────
step "4/8 · Python y uv"

PYTHON_BIN=""
for py in python3.12 python3.11; do
    if command -v "$py" &>/dev/null; then
        MAJ=$("$py" -c "import sys; print(sys.version_info.major)")
        MIN=$("$py" -c "import sys; print(sys.version_info.minor)")
        [[ $MAJ -eq 3 && $MIN -ge 11 ]] && { PYTHON_BIN="$py"; break; }
    fi
done
if [[ -z "$PYTHON_BIN" ]]; then
    info "Instalando Python 3.12 via Homebrew..."
    brew install python@3.12
    PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
fi
ok "Python: $($PYTHON_BIN --version)"

if ! command -v uv &>/dev/null; then
    info "Instalando uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
ok "uv: $(uv --version)"

# ─── 5/8 · Ollama ────────────────────────────────────────────────────
step "5/8 · Ollama (motor de inferencia local)"

if ! command -v ollama &>/dev/null; then
    info "Instalando Ollama via Homebrew..."
    brew install --cask ollama
fi

# Arrancar si no está corriendo
if ! curl -sf http://localhost:11434 &>/dev/null; then
    info "Iniciando Ollama..."
    open -a Ollama 2>/dev/null || (ollama serve > /tmp/ollama-mac.log 2>&1 &)
    for i in {1..20}; do
        curl -sf http://localhost:11434 &>/dev/null && break
        sleep 2
        [[ $i -eq 20 ]] && err "Ollama no responde tras 40s. Ábrelo manualmente e intenta de nuevo."
    done
fi
ok "Ollama activo en localhost:11434"

# ─── 6/8 · Docker Desktop ────────────────────────────────────────────
step "6/8 · Docker Desktop (PostgreSQL + Redis)"

if ! command -v docker &>/dev/null; then
    info "Instalando Docker Desktop via Homebrew..."
    brew install --cask docker
    warn "Docker Desktop instalado."
    warn "Ábrelo una vez para completar la configuración, luego vuelve a ejecutar este script."
    open -a Docker
    exit 0
fi

if ! docker info &>/dev/null; then
    info "Arrancando Docker Desktop..."
    open -a Docker 2>/dev/null || true
    for i in {1..20}; do
        docker info &>/dev/null && break
        sleep 3
        info "  esperando Docker... (${i}/20)"
        [[ $i -eq 20 ]] && err "Docker no disponible. Asegúrate de que Docker Desktop está corriendo."
    done
fi
ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'activo')"

# ─── 7/8 · Configuración ─────────────────────────────────────────────
step "7/8 · Configuración"

SKIP_CONFIG=false
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    warn ".env ya existe."
    ask OVERWRITE "¿Sobreescribir? (s/n)" "n"
    [[ "$OVERWRITE" == "s" ]] || { info "Manteniendo .env existente."; SKIP_CONFIG=true; }
fi

if [[ "$SKIP_CONFIG" == "false" ]]; then
    echo ""
    info "Necesito algunos datos de configuración:"
    echo ""
    ask        HF_TOKEN        "Token HuggingFace (opcional, Enter para omitir)" ""
    ask_secret TG_ADMIN_TOKEN  "Token del bot Telegram del ORQUESTADOR (admin)"
    ask        TG_ADMIN_ID     "Tu chat ID de Telegram (admin)"
    ask_secret DB_PASS         "Contraseña base de datos (Enter = auto-generar)"  ""

    [[ -z "$DB_PASS" ]] && DB_PASS=$($PYTHON_BIN -c "import secrets; print(secrets.token_urlsafe(16))")
    REDIS_PASS=$($PYTHON_BIN -c "import secrets; print(secrets.token_urlsafe(16))")
    FERNET_KEY=$($PYTHON_BIN -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

    cat > "$SCRIPT_DIR/.env" << ENV
# Auto-generado por install-mac.sh — $(date)
# Perfil: ${PROFILE} | Chip: ${CHIP} | RAM: ${RAM_GB} GB

# ── Telegram ──────────────────────────────────────────────────────────
ADMIN_BOT_TOKEN=${TG_ADMIN_TOKEN}
ADMIN_CHAT_ID=${TG_ADMIN_ID}

# ── HuggingFace ───────────────────────────────────────────────────────
HUGGINGFACE_TOKEN=${HF_TOKEN}

# ── Base de datos ─────────────────────────────────────────────────────
POSTGRES_USER=svuser
POSTGRES_PASSWORD=${DB_PASS}
POSTGRES_DB=secretarios
APP_DB_USER=svapp
APP_DB_PASSWORD=${DB_PASS}
DATABASE_URL=postgresql+asyncpg://svapp:${DB_PASS}@localhost:5432/secretarios

# ── Redis ─────────────────────────────────────────────────────────────
REDIS_PASSWORD=${REDIS_PASS}
REDIS_URL=redis://:${REDIS_PASS}@localhost:6379/0

# ── LLM — Ollama (backend macOS, API compatible con OpenAI) ──────────
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
CHAT_MODEL=${CHAT_MODEL}
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_API_KEY=ollama
EMBEDDING_MODEL=${EMBED_MODEL}
EMBEDDING_DIM=${EMBED_DIM}

# ── Whisper ───────────────────────────────────────────────────────────
WHISPER_URL=http://localhost:9000
WHISPER_MODEL=${WHISPER_MODEL}

# ── Sistema ───────────────────────────────────────────────────────────
DOCUMENTS_DIR=./data/documents
HARDWARE_PROFILE=${PROFILE}
MAX_CONCURRENT_USERS=${MAX_USERS}
ENCRYPTION_KEY=${FERNET_KEY}
ENV

    ok ".env generado"
fi

# ─── Servicios Docker (solo postgres + redis, sin GPU) ───────────────
info "Iniciando PostgreSQL y Redis..."
mkdir -p "$SCRIPT_DIR/data/documents" "$SCRIPT_DIR/logs"

# Sin --profile gpu: docker-compose arranca únicamente postgres y redis
docker compose \
    -f "$SCRIPT_DIR/infrastructure/docker-compose.yml" \
    --env-file "$SCRIPT_DIR/.env" \
    up -d --remove-orphans

# Esperar a que PostgreSQL esté listo
for i in {1..20}; do
    docker compose \
        -f "$SCRIPT_DIR/infrastructure/docker-compose.yml" \
        exec -T postgres pg_isready -U svuser -d secretarios &>/dev/null && break
    sleep 2
    [[ $i -eq 20 ]] && err "PostgreSQL no arrancó a tiempo."
done
ok "PostgreSQL y Redis activos"

# Actualizar contraseña del usuario svapp
docker compose \
    -f "$SCRIPT_DIR/infrastructure/docker-compose.yml" \
    exec -T postgres psql -U svuser -d secretarios \
    -c "ALTER USER svapp WITH PASSWORD '$(grep APP_DB_PASSWORD "$SCRIPT_DIR/.env" | cut -d= -f2)';" \
    &>/dev/null || true

# ─── 8/8 · Descargar modelos + entorno Python + launchd ──────────────
step "8/8 · Modelos, entorno Python e inicio automático"

# Entorno Python
cd "$SCRIPT_DIR"
[[ -d .venv ]] || uv venv --python "$PYTHON_BIN" .venv
source .venv/bin/activate
uv pip install -e ".[dev]" -q
ok "Dependencias Python instaladas"

# Modelos Ollama (esto puede tardar dependiendo de la conexión)
info "Descargando modelo de chat: ${CHAT_MODEL}"
ollama pull "$CHAT_MODEL"
info "Descargando modelo de embeddings: ${EMBED_MODEL}"
ollama pull "$EMBED_MODEL"
ok "Modelos listos"

# launchd — arranque automático al iniciar sesión
PLIST="$HOME/Library/LaunchAgents/ai.secretariosvirtuales.supervisor.plist"
launchctl unload "$PLIST" 2>/dev/null || true

cat > "$PLIST" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.secretariosvirtuales.supervisor</string>
    <key>ProgramArguments</key>
    <array>
        <string>${SCRIPT_DIR}/.venv/bin/python</string>
        <string>-m</string>
        <string>supervisor</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>PYTHONPATH</key>
        <string>${SCRIPT_DIR}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/logs/supervisor.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/logs/supervisor.error.log</string>
</dict>
</plist>
PLIST

launchctl load "$PLIST"
ok "Servicio launchd registrado (arranca automáticamente al login)"

# ─── Resumen final ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}"
cat << 'EOF'
╔═══════════════════════════════════════════════╗
║   ✅  Instalación completada                  ║
╚═══════════════════════════════════════════════╝
EOF
echo -e "${NC}"
echo   "  Perfil activo:   ${BOLD}${PROFILE}${NC}  —  ${CHIP}  ${RAM_GB} GB RAM"
echo   "  Modelo chat:     ${CHAT_MODEL}"
echo   "  Embeddings:      ${EMBED_MODEL}  (${EMBED_DIM}d)"
echo   "  Whisper:         ${WHISPER_MODEL}"
echo ""
echo -e "  ${CYAN}Ver logs:${NC}"
echo   "    tail -f ${SCRIPT_DIR}/logs/supervisor.log"
echo ""
echo -e "  ${CYAN}Parar el servicio:${NC}"
echo   "    launchctl unload ${PLIST}"
echo ""
echo -e "  ${CYAN}Arrancar manualmente:${NC}"
echo   "    source ${SCRIPT_DIR}/.venv/bin/activate && python -m supervisor"
echo ""
