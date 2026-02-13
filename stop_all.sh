#!/bin/bash
# ==========================================================
# MedQuiz Pro - Stop All Services
# ==========================================================

echo "🛑 Stopping all MedQuiz services..."

# Kill uvicorn/fastapi
pkill -f "uvicorn" 2>/dev/null
pkill -f "backend.main" 2>/dev/null

# Kill next.js
pkill -f "next-server" 2>/dev/null
pkill -f "node.*next" 2>/dev/null

# Kill cloudflared tunnel
pkill -f "cloudflared tunnel" 2>/dev/null

# Force kill on ports
fuser -k 8000/tcp 2>/dev/null
fuser -k 3000/tcp 2>/dev/null

echo "✅ All services stopped"
