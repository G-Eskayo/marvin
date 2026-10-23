#!/usr/bin/env node
/**
 * Variant (a): Baseline bench server - HTTP/ndjson over Tailscale
 *
 * Reuses dashboard/mobile-backend's real device_gate.js and routing pattern.
 * Provides a minimal /bench/echo endpoint for RTT/TTFT/throughput measurement.
 * Not mounted on production index.js - this is standalone for benchmarking only.
 */
import { createServer } from "http";
import { homedir } from "os";
import path from "path";
import { fileURLToPath } from "url";
import { execFile } from "child_process";
import { promisify } from "util";
import { whois, loadAllowlist, isAllowed } from "../device_gate.js";

const execFileP = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ALLOWLIST_PATH = path.join(homedir(), ".claude", "mobile-allowlist.json");
const TAILSCALE_BIN = "/Applications/Tailscale.app/Contents/MacOS/Tailscale";

// Configuration
const PORT = parseInt(process.env.BENCH_PORT || "9001");
const TAILSCALE_IP = process.env.TAILSCALE_IP || null;

// Resolve this machine's Tailscale IPv4 address. Fails loud and exits non-zero if unresolvable.
async function resolveTailscaleIp() {
  try {
    const { stdout } = await execFileP(TAILSCALE_BIN, ["ip", "-4"]);
    const ip = stdout.trim();
    if (!ip) {
      console.error("ERROR: tailscale ip -4 returned empty");
      process.exit(1);
    }
    console.log(`Resolved Tailscale IPv4: ${ip}`);
    return ip;
  } catch (err) {
    console.error(`ERROR: Failed to resolve Tailscale IPv4: ${err.message}`);
    process.exit(1);
  }
}

// Simple router for bench endpoints
function createRouter(allowlist) {
  return {
    "/bench/echo": (req, res) => handleEcho(req, res, allowlist),
    "/bench/health": handleHealth,
  };
}

// Echo endpoint: reflect request body back with timing info
async function handleEcho(req, res, allowlist) {
  const startTime = Date.now();

  // Check authorization via Tailscale whois
  const clientIp = req.headers["x-tailscale-client-ip"] || req.socket.remoteAddress;
  const peer = await whois(clientIp, execFileP);

  if (!isAllowed(peer, allowlist)) {
    res.writeHead(403, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Unauthorized device" }));
    return;
  }

  // Collect request body
  let body = "";
  req.on("data", (chunk) => {
    if (body.length + chunk.length > 100 * 1024 * 1024) {
      res.writeHead(413, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Payload too large" }));
      return;
    }
    body += chunk;
  });

  req.on("end", () => {
    const processingTime = Date.now() - startTime;

    // Parse incoming JSON
    let incoming;
    try {
      incoming = JSON.parse(body);
    } catch (e) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Invalid JSON", message: e.message }));
      return;
    }

    // Echo response with timing
    const response = {
      echo: incoming,
      timing: {
        received_ms: processingTime,
        server_time_ms: Date.now() % 1000,
      },
    };

    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(response));
  });
}

// Health check endpoint
async function handleHealth(req, res) {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ status: "healthy" }));
}

// Main server
async function main() {
  const ip = TAILSCALE_IP || (await resolveTailscaleIp());
  const allowlist = loadAllowlist(ALLOWLIST_PATH);

  const router = createRouter(allowlist);
  const server = createServer((req, res) => {
    const handler = router[req.url];
    if (handler) {
      handler(req, res).catch((err) => {
        console.error("Handler error:", err);
        res.writeHead(500);
        res.end("Internal Server Error");
      });
    } else {
      res.writeHead(404);
      res.end("Not Found");
    }
  });

  server.listen(PORT, ip, () => {
    console.log(`Bench server (variant a) listening on ${ip}:${PORT}`);
  });

  // Graceful shutdown
  process.on("SIGTERM", () => {
    console.log("Shutting down gracefully");
    server.close(() => {
      process.exit(0);
    });
  });
}

main().catch((err) => {
  console.error("Failed to start server:", err);
  process.exit(1);
});
