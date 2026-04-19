#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$SCRIPT_DIR/infrastructure/docker-compose.yml"

echo "Recreando sv-vllm-chat con configuración actual..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile gpu up -d vllm-chat --force-recreate

echo "Esperando a que el modelo esté listo (puede tardar 10-15 min la primera vez)..."
until docker logs sv-vllm-chat 2>&1 | grep -q "Application startup complete"; do
    sleep 10
    # Show progress
    last=$(docker logs sv-vllm-chat 2>&1 | grep "INFO" | tail -1 | sed 's/.*INFO //')
    echo "  → $last"
done

echo "✅ vLLM listo."
