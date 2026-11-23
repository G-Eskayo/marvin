# GitHub Webhook Funnel Setup

One-time operational setup for GitHub webhooks via Tailscale Funnel (ticket #566).

## Prerequisites

- Mac Mini (the primary host, `isPrimaryHost()`)
- Tailscale installed and authenticated
- Webhook secret generated and stored

## One-time setup

### 1. Generate and store the webhook secret

On the Mac Mini:

```bash
openssl rand -hex 32 > ~/.claude/.github-webhook-secret
chmod 600 ~/.claude/.github-webhook-secret
```

This file is never committed; it's read by `loadWebhookSecret()` in `gh_auth.js`.

### 2. Enable Tailscale Funnel on the webhook server

```bash
# Start Funnel on port 443, routing to the webhook server on port 7878
tailscale serve --set-path=/github-webhook http://localhost:7878/github-webhook
tailscale funnel 443 on
```

This exposes `https://<mac-mini-tailscale-name>/github-webhook` to GitHub.

### 3. Set the Funnel URL for webhook provisioning

In the webhook-server environment (or `.env`):

```bash
export MARVIN_GITHUB_FUNNEL_URL="https://<mac-mini-tailscale-name>/github-webhook"
```

Replace `<mac-mini-tailscale-name>` with the actual Tailscale name (e.g., `mini-macbook.tail1234.ts.net`).

### 4. Restart the webhook server

The server will:
- Read the secret from the file
- Provision webhooks on all registered repos (idempotent: creates or patches existing ones)
- Log each result

## Secret rotation

If the secret needs to be rotated:

1. Generate a new secret: `openssl rand -hex 32 > ~/.claude/.github-webhook-secret`
2. Run the provisioning step again (or restart the webhook server)
3. GitHub will send old-secret deliveries a 401 (signature mismatch); GitHub automatically retries with the same body
4. No need to manually re-send: GitHub's retry mechanism handles it

## Troubleshooting

### "webhook secret not configured"

The webhook-server started without finding `~/.claude/.github-webhook-secret`. Check:
- File exists and is readable: `ls -la ~/.claude/.github-webhook-secret`
- Server logs show `GitHub webhook secret source: file` at startup

### "invalid signature"

GitHub is sending a signature that doesn't match the secret. This means:
- The secret on the server doesn't match what GitHub has stored
- Run provisioning again to sync them, or rotate the secret and re-provision

### Funnel is down

If `tailscale funnel 443 on` fails or Funnel stops, webhooks will 503. Check:
- Tailscale is still running: `tailscale status`
- Funnel is still enabled: `tailscale funnel status`
- Restart if needed: `tailscale funnel 443 on`

## Monitoring

Health checks:
- `Health` card's `github-funnel` entry (optional, added via `lib/job_catalog.py` in marvin#566 follow-up)
- Webhook delivery logs in the webhook-server stdout: `[github-webhook] <event> on <repo>`
- Failed deliveries are logged under `[webhook-provision]` at startup

## Related

- `dashboard/webhook-server/gh_webhook.js`: signature verification, dedup, allowlist
- `dashboard/webhook-server/gh_webhook_provision.js`: idempotent provisioning via `gh api`
- CONTEXT.md: "Triggers over polling" section, GitHub state bullet
