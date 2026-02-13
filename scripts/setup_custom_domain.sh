#!/bin/bash

# Custom Domain Setup for quiz.tusabi.store
# This script helps you configure a persistent Cloudflare Tunnel

APP_DIR="/home/yusuf-kemal-tuna/medical_quiz_app"
cd "$APP_DIR" || exit

DOMAIN="quiz.tusabi.store"
TUNNEL_NAME="medquiz-tunnel"

echo "🌐 Custom Domain Setup for: $DOMAIN"
echo "================================================"

# Step 1: Authenticate with Cloudflare
echo ""
echo "Step 1: Authenticate Cloudflared (if not already done)"
echo "-------------------------------------------------------"
echo "Run the following command and follow the browser login:"
echo ""
echo "  ./cloudflared tunnel login"
echo ""
read -p "Have you completed authentication? (y/n): " auth_done

if [[ "$auth_done" != "y" ]]; then
    echo "Please run: ./cloudflared tunnel login"
    echo "Then run this script again."
    exit 1
fi

# Step 2: Create named tunnel
echo ""
echo "Step 2: Creating Named Tunnel: $TUNNEL_NAME"
echo "-------------------------------------------------------"
./cloudflared tunnel create $TUNNEL_NAME

# This creates a JSON file with tunnel credentials
# Usually saved to ~/.cloudflared/<TUNNEL_ID>.json

# Step 3: Get Tunnel ID
TUNNEL_ID=$(./cloudflared tunnel list | grep $TUNNEL_NAME | awk '{print $1}')

if [[ -z "$TUNNEL_ID" ]]; then
    echo "❌ Failed to create tunnel. Please check errors above."
    exit 1
fi

echo "✅ Tunnel created: $TUNNEL_NAME (ID: $TUNNEL_ID)"

# Step 4: Create config file
echo ""
echo "Step 3: Creating Tunnel Config File"
echo "-------------------------------------------------------"

cat > ~/.cloudflared/config.yml <<EOF
tunnel: $TUNNEL_ID
credentials-file: /home/yusuf-kemal-tuna/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $DOMAIN
    service: http://localhost:3000
  - service: http_status:404
EOF

echo "✅ Config created at: ~/.cloudflared/config.yml"

# Step 4: DNS Configuration (Manual)
echo ""
echo "Step 4: Configure DNS in Cloudflare Dashboard"
echo "-------------------------------------------------------"
echo "⚠️  IMPORTANT: You must manually add DNS record in Cloudflare:"
echo ""
echo "1. Go to: https://dash.cloudflare.com"
echo "2. Select domain: tusabi.store"
echo "3. Go to DNS > Records"
echo "4. Add a CNAME record:"
echo "   - Name: quiz"
echo "   - Target: $TUNNEL_ID.cfargotunnel.com"
echo "   - Proxy: Enabled (Orange cloud)"
echo ""
echo "Alternatively, run this command to auto-configure DNS:"
echo ""
echo "  ./cloudflared tunnel route dns $TUNNEL_NAME $DOMAIN"
echo ""
read -p "Have you configured DNS? (y/n): " dns_done

if [[ "$dns_done" != "y" ]]; then
    echo ""
    echo "Run the DNS command above or configure it manually in Cloudflare dashboard."
    echo "Then run the tunnel with: ./cloudflared tunnel run $TUNNEL_NAME"
    exit 0
fi

# Step 5: Run the tunnel
echo ""
echo "Step 5: Starting Tunnel"
echo "-------------------------------------------------------"
echo "Running: ./cloudflared tunnel run $TUNNEL_NAME"
echo ""
echo "Your app should now be accessible at: https://$DOMAIN"
echo ""
echo "To keep this running in the background, use:"
echo "  nohup ./cloudflared tunnel run $TUNNEL_NAME > cloudflare.log 2>&1 &"
echo ""

./cloudflared tunnel run $TUNNEL_NAME
