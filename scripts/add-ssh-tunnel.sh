#!/usr/bin/env bash
set -e

echo ""
echo "==> Añadiendo SSH al túnel Cloudflare..."

CONFIG="/etc/cloudflared/config.yml"

# Leer tunnel ID y hostname actuales
TUNNEL_ID=$(grep "^tunnel:" "$CONFIG" | awk '{print $2}')
CREDS_FILE=$(grep "credentials-file:" "$CONFIG" | awk '{print $2}')
HOSTNAME=$(grep "hostname:" "$CONFIG" | head -1 | awk '{print $3}')
# Extraer dominio base (ej: martos.jlu.app -> jlu.app, prefijo -> martos)
SSH_HOSTNAME="ssh.$HOSTNAME"

echo "    Túnel: $TUNNEL_ID"
echo "    Panel: $HOSTNAME"
echo "    SSH:   $SSH_HOSTNAME"

# Reescribir config con SSH añadido
sudo tee "$CONFIG" > /dev/null << EOF
tunnel: $TUNNEL_ID
credentials-file: $CREDS_FILE

ingress:
  - hostname: $HOSTNAME
    service: http://localhost:8080
  - hostname: $SSH_HOSTNAME
    service: ssh://localhost:22
  - service: http_status:404
EOF

echo "    Config actualizada."

# Añadir DNS para SSH
echo ""
echo "==> Añadiendo registro DNS $SSH_HOSTNAME..."
TUNNEL_NAME=$(cloudflared tunnel list | grep "$TUNNEL_ID" | awk '{print $2}')
cloudflared tunnel route dns "$TUNNEL_NAME" "$SSH_HOSTNAME"

# Reiniciar servicio
echo ""
echo "==> Reiniciando cloudflared..."
sudo systemctl restart cloudflared
sleep 2
sudo systemctl status cloudflared --no-pager | grep "Active:" || true

echo ""
echo "✓ SSH habilitado en el túnel."
echo ""
echo "  En tu máquina Windows, añade a C:\Users\JLu\.ssh\config:"
echo ""
echo "  Host $SSH_HOSTNAME"
echo "    ProxyCommand cloudflared access ssh --hostname %h"
echo "    User $(whoami)"
echo ""
echo "  Luego conecta con: ssh $SSH_HOSTNAME"
