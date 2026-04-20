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

# 4. Reload and restart
echo ""
echo "==> Recargando systemd..."
sudo systemctl daemon-reload

for svc in web-admin obsidian-sync; do
    echo "==> Activando $svc..."
    sudo systemctl enable "$svc" 2>/dev/null || true
    sudo systemctl restart "$svc"
done

# 5. Status
echo ""
echo "==> Estado de los servicios:"
sudo systemctl status web-admin obsidian-sync --no-pager -l | grep -E "(Active|Main PID|error|Error|ModuleNot)" || true

echo ""
echo "✓ Despliegue completado."
echo "  Panel web: http://$(hostname -I | awk '{print $1}'):8080"
