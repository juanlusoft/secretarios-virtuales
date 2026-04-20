#!/usr/bin/env bash
set -e

# Auto-detect user and project path
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(whoami)"
VENV="$PROJECT_DIR/.venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "==> Proyecto: $PROJECT_DIR"
echo "==> Usuario:  $CURRENT_USER"
echo "==> Python:   $PYTHON"

# 1. Pull latest code
echo ""
echo "==> Actualizando código..."
git -C "$PROJECT_DIR" pull

# 2. Install dependencies
echo ""
echo "==> Instalando dependencias..."
"$PIP" install -e ".[dev]" -q

# 2b. Run database migrations
echo ""
echo "==> Ejecutando migraciones de base de datos..."
"$PYTHON" -m shared.db.migrate

# 3. Write systemd services with correct paths
echo ""
echo "==> Configurando servicios systemd..."

write_service() {
    local name="$1"
    local desc="$2"
    local exec_cmd="$3"
    local restart="$4"
    local restart_sec="$5"

    sudo tee /etc/systemd/system/"$name".service > /dev/null << EOF
[Unit]
Description=$desc
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PYTHON $exec_cmd
Restart=$restart
RestartSec=$restart_sec

[Install]
WantedBy=multi-user.target
EOF
    echo "    Escrito: /etc/systemd/system/$name.service"
}

write_service "web-admin"      "SV Web Admin Panel"   "-m web"               "on-failure" "5"
write_service "obsidian-sync"  "SV Obsidian Sync"     "-m shared.vault.cron" "always"     "30"
write_service "calendar-remind" "SV Calendar Reminder" "-m shared.calendar.remind" "always" "30"

# Install backup timer (not a long-running service)
echo "    Instalando timer de backup..."
sudo cp "$PROJECT_DIR/infrastructure/systemd/backup-db.service" /etc/systemd/system/
sudo cp "$PROJECT_DIR/infrastructure/systemd/backup-db.timer" /etc/systemd/system/

# 4. Setup Obsidian vaults directory
echo ""
echo "==> Configurando vaults de Obsidian..."
VAULTS_DIR="$HOME/vaults"
mkdir -p "$VAULTS_DIR/shared"
echo "    Vaults: $VAULTS_DIR"

ENV_FILE="$PROJECT_DIR/.env"
if ! grep -q "OBSIDIAN_VAULTS_DIR" "$ENV_FILE" 2>/dev/null; then
    echo "OBSIDIAN_VAULTS_DIR=$VAULTS_DIR" >> "$ENV_FILE"
    echo "    Añadido OBSIDIAN_VAULTS_DIR al .env"
else
    echo "    OBSIDIAN_VAULTS_DIR ya está en .env"
fi

# 5. Reload and restart
echo ""
echo "==> Recargando systemd..."
sudo systemctl daemon-reload
sudo systemctl enable --now backup-db.timer 2>/dev/null || true
echo "    Timer backup-db activado"

for svc in web-admin obsidian-sync calendar-remind; do
    echo "==> Activando $svc..."
    sudo systemctl enable "$svc" 2>/dev/null || true
    sudo systemctl restart "$svc"
done

# 5. Status
echo ""
echo "==> Estado de los servicios:"
sudo systemctl status web-admin obsidian-sync calendar-remind --no-pager -l | grep -E "(Active|Main PID|error|Error|ModuleNot)" || true

echo ""
echo "✓ Despliegue completado."
echo "  Panel web: http://$(hostname -I | awk '{print $1}'):8080"
