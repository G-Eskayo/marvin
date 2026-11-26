#!/bin/bash
# marvin#566: set up Tailscale Funnel to expose the GitHub webhook endpoint from this machine.
# Idempotent: safe to run multiple times. Rotation steps for the secret are documented here.

set -e

WEBHOOK_SECRET_FILE="${HOME}/.claude/.webhook-secret"
LOCAL_PORT="${1:-7878}"
WEBHOOK_PATH="github-webhook"
FUNNEL_PORT="443"

# Ensure the secret file exists and contains a 32-byte (256-bit) random value.
if [ ! -f "$WEBHOOK_SECRET_FILE" ]; then
  echo "[setup] Creating new webhook secret at $WEBHOOK_SECRET_FILE"
  mkdir -p "$(dirname "$WEBHOOK_SECRET_FILE")"
  openssl rand -hex 32 > "$WEBHOOK_SECRET_FILE"
  chmod 600 "$WEBHOOK_SECRET_FILE"
  echo "[setup] Secret created. Register this in GitHub:"
  echo "  $(cat "$WEBHOOK_SECRET_FILE")"
else
  echo "[setup] Webhook secret file already exists. Current secret:"
  echo "  $(cat "$WEBHOOK_SECRET_FILE")"
fi

# Expose the webhook endpoint via Funnel (requires Tailscale and owner approval).
# Funnel only supports ports 443, 8443, and 10000; use 443 by default.
# Use the new syntax: expose only the webhook path via HTTPS on the funnel port.
echo "[setup] Setting up Tailscale Funnel on port $FUNNEL_PORT, exposing only /$WEBHOOK_PATH"
tailscale funnel --bg --https="$FUNNEL_PORT" --set-path="/$WEBHOOK_PATH" "http://localhost:$LOCAL_PORT/$WEBHOOK_PATH"

# Show the public URL.
PUBLIC_URL=$(tailscale status | grep -i "online\|relay" | head -1 | awk '{print $1}')
if [ -z "$PUBLIC_URL" ]; then
  PUBLIC_URL="<tailscale-domain>.ts.net"
fi
echo "[setup] Funnel active. Webhook URL: https://$PUBLIC_URL/$WEBHOOK_PATH"

# Secret rotation: to rotate the webhook secret, run:
#   openssl rand -hex 32 > ~/.claude/.webhook-secret
#   Update the GitHub App or webhook's secret in the web UI.
#   Restart the webhook server: systemctl restart marvin-webhook-server
# (Or manually: kill the old process and run: node dashboard/webhook-server/index.js)

echo "[setup] Complete. See dashboard/webhook-server/README.md for GitHub webhook registration."
