#!/usr/bin/env bash
#
# fix-db-and-deploy.sh — Arregla problemas recurrentes de la BD y relanza el despliegue.
#
# Qué hace (en orden, todos los pasos son idempotentes):
#   1. Verifica que NO se ejecuta como root (deploy.sh necesita el usuario normal
#      para que systemd escriba User=$CURRENT_USER y el venv se use correctamente).
#   2. Cachea credenciales sudo al inicio (sudo -v) para que el resto no prompt.
#   3. Asegura que el contenedor sv-postgres está corriendo.
#   4. Corrige el propietario del PGDATA: dentro del contenedor chown -R
#      postgres:postgres /var/lib/postgresql/data. Necesario cuando el bind-mount
#      queda con UID del host (1000:1000) en vez del UID del usuario postgres
#      dentro de la imagen (999), lo que provoca errores tipo
#      "could not open file \"global/pg_filenode.map\": Permission denied".
#   5. Reinicia sv-postgres y espera a pg_isready.
#   6. Sincroniza la contraseña del role svuser con el valor de POSTGRES_PASSWORD
#      en .env (ALTER USER). Necesario porque POSTGRES_PASSWORD solo aplica en
#      la primera inicialización del volumen; si alguien cambia la password en
#      .env después, el role sigue con la antigua y la app falla con
#      "password authentication failed for user \"svuser\"".
#   7. Ejecuta bash deploy.sh (migraciones + units systemd + arranque servicios).
#
# Cuándo usarlo:
#   - El despliegue falla en migraciones con error de permisos de PostgreSQL.
#   - La app no puede autenticarse contra la BD pero el contenedor está "healthy".
#   - Tras restaurar un backup del PGDATA o rotar POSTGRES_PASSWORD en .env.
#
# Uso:
#   bash scripts/fix-db-and-deploy.sh
#
# Requisitos:
#   - Ejecutado como el usuario dueño del proyecto (no con sudo).
#   - sv-postgres existente (docker compose -f infrastructure/docker-compose.yml up -d postgres).
#   - .env con POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / DATABASE_URL.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
CONTAINER="sv-postgres"

if [ "$(id -u)" = "0" ]; then
    echo "ERROR: No ejecutes este script con sudo. Lánzalo como tu usuario normal."
    echo "       El script pedirá sudo internamente cuando lo necesite."
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: No se encuentra $ENV_FILE"
    exit 1
fi

# Cargar credenciales de la BD desde .env
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${POSTGRES_USER:?falta POSTGRES_USER en .env}"
: "${POSTGRES_PASSWORD:?falta POSTGRES_PASSWORD en .env}"
: "${POSTGRES_DB:?falta POSTGRES_DB en .env}"

echo "==> Cacheando credenciales sudo..."
sudo -v

echo ""
echo "==> Comprobando contenedor $CONTAINER..."
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: contenedor $CONTAINER no existe. Arráncalo con:"
    echo "       docker compose -f infrastructure/docker-compose.yml up -d postgres"
    exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "    Contenedor parado, arrancando..."
    docker start "$CONTAINER" >/dev/null
fi

echo ""
echo "==> Corrigiendo propietario del PGDATA (idempotente)..."
docker exec -u 0 "$CONTAINER" chown -R postgres:postgres /var/lib/postgresql/data

echo ""
echo "==> Reiniciando $CONTAINER..."
docker restart "$CONTAINER" >/dev/null

echo -n "    Esperando a pg_isready"
for _ in $(seq 1 30); do
    if docker exec "$CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        echo " OK"
        break
    fi
    echo -n "."
    sleep 2
done

if ! docker exec "$CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    echo ""
    echo "ERROR: postgres no respondió a pg_isready tras 60s. Revisa:"
    echo "       docker logs $CONTAINER --tail 50"
    exit 1
fi

echo ""
echo "==> Sincronizando password del role $POSTGRES_USER con .env..."
# Socket local (-h /var/run/postgresql) para evitar autenticación por password.
# Pasamos la SQL por stdin porque psql -c no hace interpolación de -v.
docker exec -i "$CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -h /var/run/postgresql \
    -v ON_ERROR_STOP=1 -v role="$POSTGRES_USER" -v pwd="$POSTGRES_PASSWORD" >/dev/null <<'SQL'
ALTER USER :"role" WITH PASSWORD :'pwd';
SQL
echo "    Password sincronizada."

echo ""
echo "==> Lanzando deploy.sh..."
cd "$PROJECT_DIR"
bash deploy.sh
