#!/bin/bash
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
cp "$BASE"/weekly-summary.service "$BASE"/weekly-summary.timer \
   "$BASE"/morning-digest.service "$BASE"/morning-digest.timer \
   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now weekly-summary.timer morning-digest.timer
echo "Timers instalados y activos."
systemctl list-timers --all | grep -E "weekly|digest"
