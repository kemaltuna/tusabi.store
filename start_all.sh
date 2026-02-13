#!/bin/bash
# ==========================================================
# MedQuiz Pro - Full Stack Launcher
# Kills everything first, then starts backend + frontend
# ==========================================================

cd /home/yusuf-kemal-tuna/medical_quiz_app

echo "🛑 Killing existing processes..."

# Kill any uvicorn/fastapi processes
pkill -f "uvicorn" 2>/dev/null
pkill -f "backend.main" 2>/dev/null

# Kill any next.js processes  
pkill -f "next-server" 2>/dev/null
pkill -f "node.*next" 2>/dev/null

# Kill anything on ports 8000 and 3000
fuser -k 8000/tcp 2>/dev/null
fuser -k 3000/tcp 2>/dev/null

# Wait a moment for processes to die
sleep 2

echo "✅ All processes killed"

# Activate virtual environment
source venv/bin/activate

echo "🚀 Starting FastAPI Backend on port 8000..."
cd new_web_app
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > ../backend.log 2>&1 &
BACKEND_PID=$!
echo "   Backend PID: $BACKEND_PID"

sleep 2

echo "🚀 Starting Next.js Frontend on port 3000..."
cd frontend
nohup npm run dev > ../../frontend.log 2>&1 &
FRONTEND_PID=$!
echo "   Frontend PID: $FRONTEND_PID"

cd ../..

sleep 3

echo ""
echo "=========================================="
echo "✅ All services started!"
echo "=========================================="
echo ""
echo "📍 Backend:  http://localhost:8000"
echo "📍 Frontend: http://localhost:3000"
echo ""
echo "📄 Logs:"
echo "   tail -f backend.log"
echo "   tail -f frontend.log"
echo ""
echo "🛑 To stop everything, run:"
echo "   ./stop_all.sh"
echo "=========================================="
