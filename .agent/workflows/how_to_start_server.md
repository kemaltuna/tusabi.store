---
description: How to start the server and keep it running (Persistent)
---

# Server Management Guide (Next.js + FastAPI + Cloudflare)

Bu proje Streamlit degil; servisler:
- FastAPI backend: `:8000`
- Next.js frontend: `:3000`
- Cloudflare tunnel (opsiyonel): custom domain icin

## Quick Start

### 1) Local Dev (en hizli)
```bash
./start_all.sh
```
- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000` (`/docs` ile API swagger)

Dur:
```bash
./stop_all.sh
```

### 2) Custom Domain (quiz.tusabi.store) keep-alive
```bash
./scripts/keep_alive_custom.sh
```
URL: `https://quiz.tusabi.store`

### 3) Production-benzeri (foreground + tunnel)
```bash
./scripts/run_medquiz_stack.sh
```
Not: Bu script frontend'i `npm run build` + `npm run start` ile calistirir ve tunnel'i foreground'da tutar.

## Postgres (multi-user icin onerilen)

Postgres'i docker ile baslat:
```bash
docker compose -f docker-compose.postgres.yml up -d
```

Backend'in Postgres'e baglanmasi icin `.env`:
```bash
MEDQUIZ_DB_URL=postgresql://medquiz:medquiz@localhost:5432/medquiz
```

## Logs

```bash
tail -f backend.log
tail -f frontend.log
tail -f cloudflare.log
```

## Check Status / Ports

```bash
lsof -i :8000
lsof -i :3000
ps aux | rg "uvicorn|next-server|cloudflared"
```

## Troubleshooting

### "Frontend geliyor ama API calismiyor"
- `http://localhost:8000/health` kontrol et.
- Next.js rewrite: `new_web_app/frontend/next.config.ts` `/api/*` -> `http://localhost:8000/*`.

### "Custom domain gelmiyor"
- `tail -200 cloudflare.log`
- Tunnel config var mi: `~/.cloudflared/config.yml`

### "Port dolu"
```bash
fuser -k 8000/tcp
fuser -k 3000/tcp
```
