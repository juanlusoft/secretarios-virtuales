#!/bin/bash
# One-time server setup script. Run as: sudo bash infrastructure/setup-server.sh
set -e

BASE="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="${1:-mipc}"

echo "=== Setup servidor secretarios-virtuales ==="
echo "Directorio: $BASE"
echo "Usuario de servicio: $SERVICE_USER"
echo ""

# 1. Sudoers — permite systemctl y systemd-run sin contraseña
SUDOERS_FILE=/etc/sudoers.d/sv-nopasswd
echo "$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/systemd-run" > "$SUDOERS_FILE"
chmod 440 "$SUDOERS_FILE"
echo "✓ sudoers configurado ($SUDOERS_FILE)"

# 2. Instalar timers systemd
SYSTEMD_DIR="$BASE/infrastructure/systemd"
for f in weekly-summary.service weekly-summary.timer morning-digest.service morning-digest.timer; do
    if [ -f "$SYSTEMD_DIR/$f" ]; then
        cp "$SYSTEMD_DIR/$f" /etc/systemd/system/
        echo "✓ Copiado $f"
    fi
done
systemctl daemon-reload
systemctl enable --now weekly-summary.timer morning-digest.timer 2>/dev/null || true
echo "✓ Timers instalados y activos"

# 3. Verificar servicios activos
echo ""
echo "=== Estado de servicios ==="
systemctl is-active web-admin && echo "✓ web-admin activo" || echo "✗ web-admin no está activo"
systemctl list-timers --all | grep -E "weekly|digest" || echo "(timers no visibles aún)"

echo ""
echo "=== Setup completado ==="
