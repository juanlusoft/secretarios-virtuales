#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$SCRIPT_DIR/infrastructure/docker-compose.yml"

echo "Recreando sv-vllm-chat con configuración actual..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile gpu up -d vllm-chat --force-recreate

echo "Esperando a que el modelo esté listo (puede tardar 10-15 min la primera vez)..."
START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
while true; do
    if docker logs sv-vllm-chat --since "$START_TIME" 2>&1 | grep -q "Application startup complete"; then
        break
    fi
    if docker logs sv-vllm-chat --since "$START_TIME" 2>&1 | grep -q "Engine core initialization failed"; then
        echo "❌ Error al inicializar. Revisa: docker logs sv-vllm-chat --since $START_TIME 2>&1 | grep -i error"
        exit 1
    fi
    last=$(docker logs sv-vllm-chat --since "$START_TIME" 2>&1 | grep "INFO" | tail -1 | sed 's/.*INFO //' 2>/dev/null || echo "cargando...")
    echo "  → $last"
    sleep 15
done

echo "✅ vLLM listo."
