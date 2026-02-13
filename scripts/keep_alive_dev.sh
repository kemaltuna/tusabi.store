#!/bin/bash
set -euo pipefail

# Dev-mode keep-alive for custom domain (quiz.tusabi.store)
# Starts backend + frontend (dev) + Cloudflare tunnel.

APP_DIR="/home/yusuf-kemal-tuna/medical_quiz_app"
TUNNEL_NAME="medquiz-tunnel"

cd "$APP_DIR" || exit 1

# Ensure Node/NPM are available in non-interactive shells (systemd)
if [ -s "$HOME/.nvm/nvm.sh" ]; then
    export NVM_DIR="$HOME/.nvm"
    . "$NVM_DIR/nvm.sh"
    nvm use --silent default >/dev/null 2>&1 || true
fi
NODE_BIN_DIR="$(ls -d "$HOME/.nvm/versions/node/"*/bin 2>/dev/null | head -n 1 || true)"
if [ -n "${NODE_BIN_DIR:-}" ]; then
    export PATH="$NODE_BIN_DIR:$PATH"
fi

echo "🔄 Stopping old processes..."
pkill -f "cloudflared tunnel" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true
pkill -f "backend.main" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true
pkill -f "next start" 2>/dev/null || true
pkill -f "node.*next" 2>/dev/null || true
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 3000/tcp 2>/dev/null || true

echo "🚀 Starting Medical Quiz App (DEV)..."

cleanup() {
    pkill -f "uvicorn" 2>/dev/null || true
    pkill -f "next dev" 2>/dev/null || true
    pkill -f "cloudflared tunnel" 2>/dev/null || true
}
trap cleanup EXIT

# 1) Backend
cd "$APP_DIR/new_web_app" || exit 1
"$APP_DIR/venv/bin/python" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > "$APP_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "✅ Backend started (PID: $BACKEND_PID)"

sleep 2

# 2) Frontend (dev)
cd "$APP_DIR/new_web_app/frontend" || exit 1
npm run dev > "$APP_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "✅ Frontend started (PID: $FRONTEND_PID)"

sleep 2

# 3) Cloudflare Tunnel (foreground to keep service alive)
cd "$APP_DIR" || exit 1
if [ -f "$APP_DIR/cloudflared" ]; then
    CMD="$APP_DIR/cloudflared"
else
    CMD="cloudflared"
fi

echo "✅ Cloudflare Tunnel starting (foreground)..."
echo "---------------------------------------------------"
echo "🎉 System is running (DEV)!"
echo "---------------------------------------------------"
echo "🌐 URL: https://quiz.tusabi.store"
echo "📄 Backend Logs:    $APP_DIR/backend.log"
echo "📄 Frontend Logs:   $APP_DIR/frontend.log"
echo "📄 Tunnel Logs:     $APP_DIR/cloudflare.log"
echo "---------------------------------------------------"

exec "$CMD" tunnel run "$TUNNEL_NAME" >> "$APP_DIR/cloudflare.log" 2>&1
