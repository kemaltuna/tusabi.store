---
description: How to start the server and keep it running (Persistent)
---

# Server Management Guide

## 🚀 Quick Start

### Custom Domain (Production) - **RECOMMENDED**
```bash
./scripts/keep_alive_custom.sh
```
**URL:** https://quiz.tusabi.store

### Temporary URL (Testing)
```bash
./scripts/keep_alive.sh
```
**Find URL:** `grep -o 'https://.*\.trycloudflare.com' cloudflare.log`

---

## 🛑 Stop Everything

```bash
pkill -f streamlit
pkill -f cloudflared
```

---

## 🔍 Check Status

### Is the server running?
```bash
ps aux | grep streamlit
ps aux | grep cloudflared
```

### View logs (real-time)
```bash
# Streamlit logs
tail -f streamlit.log

# Cloudflare tunnel logs
tail -f cloudflare.log
```

### Check what's using port 8501
```bash
lsof -i :8501
```

---

## 🔧 Troubleshooting

### Server won't start
1. Kill old processes:
   ```bash
   pkill -f streamlit
   pkill -f cloudflared
   ```

2. Check for errors:
   ```bash
   tail -50 streamlit.log
   tail -50 cloudflare.log
   ```

3. Start fresh:
   ```bash
   ./scripts/keep_alive_custom.sh
   ```

### Custom domain not working
Check tunnel status:
```bash
./cloudflared tunnel list
./cloudflared tunnel info medquiz
```

### Port 8501 already in use
```bash
lsof -i :8501
kill -9 <PID>
```

---

## 📝 Important Notes

- **Scripts use `nohup`** - Server stays alive even after closing terminal
- **Logs are saved** to `streamlit.log` and `cloudflare.log`
- **Custom domain uses named tunnel** `medquiz`
- **Temporary URL changes** each restart (not persistent)

---

## 🔄 Restart After System Reboot

The server doesn't auto-start after reboot. Run:
```bash
cd /home/yusuf-kemal-tuna/medical_quiz_app
./scripts/keep_alive_custom.sh
```
