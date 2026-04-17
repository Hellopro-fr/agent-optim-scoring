#!/bin/bash
# Deployment script PROD — VM HelloPro
# Usage: bash scripts/deploy.sh
set -e

cd "$(dirname "$0")/.."

echo "== Pull latest code =="
git pull --rebase

echo "== Rebuild and restart dashboard =="
docker compose up -d --build

echo "== Waiting for health check =="
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sf http://localhost:5050/health >/dev/null 2>&1; then
        echo ""
        echo "[OK] Dashboard up — http://localhost:5050"
        curl -s http://localhost:5050/health
        echo ""
        exit 0
    fi
    sleep 2
done

echo "[FAIL] Dashboard did not respond within 20s"
docker compose logs --tail=30 optim-dashboard
exit 1
