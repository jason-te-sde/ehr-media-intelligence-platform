#!/usr/bin/env bash
# Docker entrypoint:
#   1. Pick a store directory — prefer mounted /data, fall back to baked demo.
#   2. Build demo data on first boot if neither is populated.
#   3. Hand off to uvicorn on $PORT (Hugging Face Spaces = 7860; Render = $PORT).
set -euo pipefail

STORE_DIR="${STORE_DIR:-/app/store}"
DEMO_DIR="/app/demo"

mkdir -p "$STORE_DIR"

# 1) If a persistent volume is mounted at /data, prefer it.
if [ -d "/data/store" ] && [ "$(ls -A /data/store 2>/dev/null || true)" ]; then
    echo "[entrypoint] using persistent /data/store"
    STORE_DIR=/data/store
fi

# 2) If chosen STORE_DIR is empty, seed from baked demo.
if [ ! -s "$STORE_DIR/store.db" ]; then
    if [ -s "$DEMO_DIR/store.db" ]; then
        echo "[entrypoint] seeding $STORE_DIR from baked demo"
        cp -R "$DEMO_DIR/." "$STORE_DIR/"
    else
        echo "[entrypoint] no baked demo; building a tiny one (~3 min)…"
        python scripts/prepare_demo_data.py --limit 25 --target "$STORE_DIR"
    fi
fi

# Symlink into the app's working store/ so backend.* finds it.
ln -sfn "$STORE_DIR" /app/store

PORT="${PORT:-7860}"
echo "[entrypoint] starting uvicorn on 0.0.0.0:$PORT (provider=$LLM_PROVIDER)"
exec uvicorn backend.api.main:app --host 0.0.0.0 --port "$PORT"
