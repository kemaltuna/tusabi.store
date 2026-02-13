#!/bin/bash
set -euo pipefail

APP_DIR="/home/yusuf-kemal-tuna/medical_quiz_app"
TUNNEL_NAME="medquiz-tunnel"

cd "$APP_DIR"

if [ -s "$HOME/.nvm/nvm.sh" ]; then
    export NVM_DIR="$HOME/.nvm"
    . "$NVM_DIR/nvm.sh"
    nvm use --silent default >/dev/null 2>&1 || true
fi

source "$APP_DIR/venv/bin/activate"

cd "$APP_DIR/new_web_app"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

cd "$APP_DIR/new_web_app/frontend"
npm run build
npm run start &
FRONTEND_PID=$!

cleanup() {
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

cd "$APP_DIR"
exec "$APP_DIR/cloudflared" tunnel run "$TUNNEL_NAME"
