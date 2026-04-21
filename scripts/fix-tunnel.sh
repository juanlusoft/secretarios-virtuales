#!/usr/bin/env bash
set -e

echo ""
echo "==> Finalizando instalación del túnel Cloudflare..."

# Copiar config al lugar que espera el servicio systemd
if [ -f "$HOME/.cloudflared/config.yml" ]; then
    sudo mkdir -p /etc/cloudflared
    sudo cp "$HOME/.cloudflared/config.yml" /etc/cloudflared/config.yml
    echo "    Config copiada a /etc/cloudflared/config.yml"
else
    echo "ERROR: No se encontró ~/.cloudflared/config.yml"
    exit 1
fi

sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

echo ""
sudo systemctl status cloudflared --no-pager | grep -E "Active:|error" || true
echo ""
echo "✓ Túnel activo. Comprueba https://$(grep hostname /etc/cloudflared/config.yml | awk '{print $3}')"
