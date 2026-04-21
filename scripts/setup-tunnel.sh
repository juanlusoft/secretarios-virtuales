#!/usr/bin/env bash
set -e

echo ""
echo "==> Instalando Cloudflare Tunnel para secretarios-virtuales"
echo ""

# 1. Instalar cloudflared
if ! command -v cloudflared &>/dev/null; then
    echo "==> Instalando cloudflared..."
    curl -L https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null
    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
    sudo apt update -q && sudo apt install -y cloudflared
    echo "    cloudflared instalado."
else
    echo "==> cloudflared ya instalado, omitiendo."
fi

# 2. Pedir datos
echo ""
read -p "Nombre del túnel (ej: secretarios-martos): " TUNNEL_NAME
read -p "Subdominio completo (ej: martos.jlu.app): " HOSTNAME

# 3. Login en Cloudflare
echo ""
echo "==> Autenticando con Cloudflare..."
echo "    Se abrirá una URL — cópiala en tu navegador y autoriza."
echo ""
cloudflared tunnel login

# 4. Crear túnel
echo ""
echo "==> Creando túnel '$TUNNEL_NAME'..."
cloudflared tunnel create "$TUNNEL_NAME"

# Obtener el ID del túnel
TUNNEL_ID=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
echo "    ID del túnel: $TUNNEL_ID"

# 5. Ruta DNS
echo ""
echo "==> Configurando DNS $HOSTNAME -> túnel..."
cloudflared tunnel route dns "$TUNNEL_NAME" "$HOSTNAME"

# 6. Fichero de configuración
CREDS_FILE="$HOME/.cloudflared/$TUNNEL_ID.json"
sudo mkdir -p /etc/cloudflared
sudo tee /etc/cloudflared/config.yml > /dev/null << EOF
tunnel: $TUNNEL_ID
credentials-file: $CREDS_FILE

ingress:
  - hostname: $HOSTNAME
    service: http://localhost:8080
  - service: http_status:404
EOF
echo "    Config escrita en /etc/cloudflared/config.yml"

# 7. Instalar como servicio systemd
echo ""
echo "==> Instalando servicio systemd..."
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

echo ""
echo "✓ Túnel configurado. Panel accesible en: https://$HOSTNAME"
echo "  Estado: sudo systemctl status cloudflared"
