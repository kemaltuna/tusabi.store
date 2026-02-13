#!/bin/bash

# Keep-alive script for CUSTOM DOMAIN (quiz.tusabi.store)
# This uses a named tunnel instead of temporary URL

APP_DIR="/home/yusuf-kemal-tuna/medical_quiz_app"
cd "$APP_DIR" || exit

TUNNEL_NAME="medquiz-tunnel"

echo "🔄 Stopping old processes..."
pkill -f "streamlit run app.py" 2>/dev/null
pkill -f "uvicorn" 2>/dev/null
pkill -f "backend.main" 2>/dev/null
pkill -f "next-server" 2>/dev/null
pkill -f "node.*next" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
fuser -k 8000/tcp 2>/dev/null
fuser -k 3000/tcp 2>/dev/null

echo "🚀 Starting Medical Quiz App (Custom Domain)..."

# 1. Activate Virtual Environment
source venv/bin/activate

# 2. Start FastAPI backend
cd "$APP_DIR/new_web_app" || exit
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > "$APP_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "✅ Backend started (PID: $BACKEND_PID)"

# Wait for backend to initialize
sleep 5

# 3. Start Next.js frontend (production)
cd "$APP_DIR/new_web_app/frontend" || exit
npm run build > "$APP_DIR/frontend_build.log" 2>&1
nohup npm run start > "$APP_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "✅ Frontend started (PID: $FRONTEND_PID)"

# Wait for frontend to initialize
sleep 5

# 4. Start Named Cloudflare Tunnel
echo "🌐 Starting Cloudflare Tunnel: $TUNNEL_NAME..."

# Check if tunnel is configured
if [ ! -f ~/.cloudflared/config.yml ]; then
    echo "❌ Error: Tunnel not configured yet!"
    echo "Please run: ./scripts/setup_custom_domain.sh"
    exit 1
fi

# Check if binary exists locally
cd "$APP_DIR" || exit
if [ -f "$APP_DIR/cloudflared" ]; then
    CMD="$APP_DIR/cloudflared"
else
    CMD="cloudflared"
fi

nohup $CMD tunnel run $TUNNEL_NAME > "$APP_DIR/cloudflare.log" 2>&1 &
CF_PID=$!
echo "✅ Cloudflare Tunnel started (PID: $CF_PID)"

echo "---------------------------------------------------"
echo "🎉 System is running on CUSTOM DOMAIN!"
echo "---------------------------------------------------"
echo "🌐 URL: https://quiz.tusabi.store"
echo "📄 Backend Logs:    $APP_DIR/backend.log"
echo "📄 Frontend Logs:   $APP_DIR/frontend.log"
echo "📄 Frontend Build:  $APP_DIR/frontend_build.log"
echo "📄 Tunnel Logs:     $APP_DIR/cloudflare.log"
echo "---------------------------------------------------"
