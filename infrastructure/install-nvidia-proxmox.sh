#!/usr/bin/env bash
# install-nvidia-proxmox.sh
# Instala drivers NVIDIA en el host de Proxmox VE (Debian Bookworm / PVE 8.x)
# Probado con RTX 3080. Requiere reinicio al finalizar.
# Uso: bash install-nvidia-proxmox.sh

set -euo pipefail

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
step() { echo -e "\n${BOLD}══ $* ══${NC}"; }

echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     NVIDIA DRIVER — Proxmox VE (RTX 3080)           ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}\n"

# ─── Comprobaciones previas ──────────────────────────────────────────────────

[[ $EUID -eq 0 ]] || fail "Ejecuta este script como root: sudo bash $0"

if ! command -v pveversion &>/dev/null; then
    fail "Este script es para Proxmox VE. No se detectó pveversion."
fi

PVE_VER=$(pveversion | grep -oP 'pve-manager/\K[0-9]+' | head -1)
KERNEL=$(uname -r)
info "Proxmox VE $PVE_VER detectado — kernel: $KERNEL"

# ─── 1. Repos non-free ───────────────────────────────────────────────────────
step "1/5 · Habilitando repositorios non-free"

SOURCES_FILE="/etc/apt/sources.list"

# Añade non-free y non-free-firmware si no están ya
if grep -q "non-free-firmware" "$SOURCES_FILE"; then
    ok "Repositorios non-free ya configurados"
else
    info "Añadiendo contrib non-free non-free-firmware a $SOURCES_FILE ..."
    # Modifica la línea del repo principal de Debian (bookworm o similar)
    sed -i 's/^\(deb.*debian\.org\/debian.*bookworm[[:space:]]*main\)$/\1 contrib non-free non-free-firmware/' "$SOURCES_FILE"
    sed -i 's/^\(deb.*debian\.org\/debian.*bookworm-updates[[:space:]]*main\)$/\1 contrib non-free non-free-firmware/' "$SOURCES_FILE"
    # Verifica que el cambio se aplicó; si no, añade línea directa
    if ! grep -q "non-free-firmware" "$SOURCES_FILE"; then
        warn "sed no modificó el sources.list. Añadiendo línea directa..."
        echo "deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware" >> "$SOURCES_FILE"
    fi
    ok "Repositorios non-free añadidos"
fi

apt-get update -qq
ok "Lista de paquetes actualizada"

# ─── 2. Cabeceras del kernel PVE ────────────────────────────────────────────
step "2/5 · Cabeceras del kernel Proxmox"

HEADERS_PKG="pve-headers-${KERNEL}"

if dpkg -l "$HEADERS_PKG" &>/dev/null 2>&1; then
    ok "Cabeceras ya instaladas: $HEADERS_PKG"
else
    info "Instalando $HEADERS_PKG ..."
    if apt-get install -y "$HEADERS_PKG"; then
        ok "Cabeceras instaladas"
    else
        warn "Paquete exacto no encontrado. Instalando pve-headers genérico..."
        apt-get install -y pve-headers
        ok "pve-headers instalado"
    fi
fi

# ─── 3. Driver NVIDIA ────────────────────────────────────────────────────────
step "3/5 · Driver NVIDIA"

if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
    CURRENT=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
    ok "Driver NVIDIA ya instalado (versión $CURRENT)"
    read -rp "  ¿Reinstalar/actualizar de todas formas? [s/N] " ans
    [[ "${ans,,}" == "s" ]] || { info "Saltando instalación de driver."; }
fi

info "Instalando nvidia-driver y firmware..."
apt-get install -y nvidia-driver firmware-misc-nonfree
ok "Driver NVIDIA instalado"

# ─── 4. Deshabilitar nouveau ─────────────────────────────────────────────────
step "4/5 · Deshabilitando driver nouveau"

BLACKLIST_FILE="/etc/modprobe.d/blacklist-nouveau.conf"

if [[ -f "$BLACKLIST_FILE" ]]; then
    ok "nouveau ya está en blacklist"
else
    cat > "$BLACKLIST_FILE" <<'EOF'
blacklist nouveau
options nouveau modeset=0
EOF
    ok "nouveau añadido a blacklist"
fi

# ─── 5. Actualizar initramfs ─────────────────────────────────────────────────
step "5/5 · Actualizando initramfs"

update-initramfs -u -k all
ok "initramfs actualizado"

# ─── Resumen ─────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              INSTALACIÓN COMPLETADA                 ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Tras reiniciar, verifica con:${NC}"
echo -e "    ${BOLD}nvidia-smi${NC}"
echo ""
echo -e "  ${CYAN}Si vas a hacer PCIe passthrough a una VM:${NC}"
echo -e "    Añade en /etc/default/grub:"
echo -e "    ${BOLD}GRUB_CMDLINE_LINUX_DEFAULT=\"quiet intel_iommu=on iommu=pt\"${NC}"
echo -e "    Luego: ${BOLD}update-grub && reboot${NC}"
echo ""

read -rp "  ¿Reiniciar ahora? [S/n] " reboot_ans
if [[ "${reboot_ans,,}" != "n" ]]; then
    info "Reiniciando..."
    reboot
else
    warn "Reinicio pendiente. El driver no estará activo hasta que reinicies."
fi
