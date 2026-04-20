#!/usr/bin/env bash
set -e

# Load env
set -a
source "$(dirname "$0")/../../.env"
set +a

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/secretarios}"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/secretarios_${TIMESTAMP}.sql.gz"

echo "==> Backup iniciado: $FILE"
pg_dump "$DATABASE_URL" | gzip > "$FILE"
echo "==> Backup completado: $(du -sh "$FILE" | cut -f1)"

# Keep only last 7 backups
cd "$BACKUP_DIR"
ls -t secretarios_*.sql.gz | tail -n +8 | xargs -r rm --
echo "==> Backups actuales: $(ls secretarios_*.sql.gz | wc -l)"
