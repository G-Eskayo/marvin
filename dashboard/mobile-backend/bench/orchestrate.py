#!/usr/bin/env python3
"""Orchestrate device-link bakeoff benchmarking.

Runs all three variants (a, b, c) in sequence:
- Starts each variant's server
- Runs the client
- Records metrics via metrics_registry
- Produces a one-page summary report

Requires these Decisions to be resolved:
- quic_lib: Which QUIC/WebTransport library for variant (b)
- phone_leg: How to measure the iPhone leg
- headscale_deploy: Headscale comparison on paper or via deployment
- variant_c_auth: Auth model for variant (c) QUIC direct
"""
import subprocess
import sys
import time
import json
import tempfile
from pathlib import Path
from typing import Dict, Optional
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class BenchmarkOrchestrator:
    """Orchestrate the full bakeoff measurement pass."""

    def __init__(self, decisions: Optional[Dict[str, str]] = None):
        """
        Initialize with decision values.

        decisions should contain:
        - quic_lib: 'curl' or 'webtransport'
        - phone_leg: 'cli-on-macbook' or 'follow-up-ticket' or 'manual'
        - headscale_deploy: 'paper' or 'docker'
        - variant_c_auth: 'tls-cert', 'preshared-token', or 'trusted-network'
        """
        self.decisions = decisions or self._get_decisions()
        self.results = {}

    def _get_decisions(self) -> Dict[str, str]:
        """Load decisions from file or use sensible defaults."""
        decisions_file = Path(__file__).parent / "decisions.json"
        if decisions_file.exists():
            return json.loads(decisions_file.read_text())

        # Defaults that prioritize robustness and avoiding over-engineering
        return {
            "quic_lib": "curl",  # Option B: External CLI, not a new Node dependency
            "phone_leg": "cli-on-macbook",  # Option B: Fully automatable, no real hardware yet
            "headscale_deploy": "paper",  # Option B: Paper comparison only
            "variant_c_auth": "trusted-network",  # Option C: Scope as local-only
        }

    def benchmark_variant_a(self) -> Dict[str, float]:
        """Run variant (a): HTTP/ndjson over Tailscale."""
        logger.info("Starting variant (a) benchmark...")

        try:
            # Start server
            server_proc = subprocess.Popen(
                ["node", "variant_a_server.js"],
                cwd=str(Path(__file__).parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait for server to be ready
            time.sleep(1)

            # Run client
            result = subprocess.run(
                [
                    sys.executable,
                    "variant_a_client.py",
                    "--host", "100.0.0.1",
                    "--port", "9001",
                    "--json",
                ],
                cwd=str(Path(__file__).parent),
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Clean up server
            server_proc.terminate()
            server_proc.wait(timeout=5)

            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                logger.error(f"Variant (a) client failed: {result.stderr}")
                return {}

        except subprocess.TimeoutExpired:
            logger.error("Variant (a) benchmark timed out")
            server_proc.kill()
            return {}
        except Exception as e:
            logger.error(f"Variant (a) benchmark failed: {e}")
            return {}

    def benchmark_variant_b(self) -> Dict[str, float]:
        """Run variant (b): QUIC/WebTransport over Tailscale.

        Requires quic_lib decision:
        - 'curl': Use curl --http3 (no new Node dependency)
        - 'webtransport': Use @fails-components/webtransport Node library
        """
        logger.info(f"Variant (b) not yet implemented (decision: quic_lib={self.decisions['quic_lib']})")
        return {}

    def benchmark_variant_c(self) -> Dict[str, float]:
        """Run variant (c): QUIC directly between devices (no Tailscale).

        Requires variant_c_auth decision:
        - 'tls-cert': TLS client certificate per device
        - 'preshared-token': Pre-shared token
        - 'trusted-network': Scope as trusted LAN only
        """
        logger.info(f"Variant (c) not yet implemented (decision: variant_c_auth={self.decisions['variant_c_auth']})")
        return {}

    def build_security_comparison_table(self) -> str:
        """Build the security/privacy comparison table.

        Includes encryption, authentication, and what third parties can observe
        (especially Tailscale's coordination service).
        """
        # Placeholder: This will be populated once all variants are measured
        table = """
| Aspect | Variant (a): HTTP/Tailscale | Variant (b): QUIC/Tailscale | Variant (c): QUIC Direct |
|--------|-------------------------|------------------------|-------------------|
| Encryption | TLS via Tailscale | TLS via Tailscale | Native QUIC |
| Authentication | Tailscale identity | Tailscale identity | TBD |
| Coordination service visibility | Tailscale sees endpoints | Tailscale sees endpoints | None |
| Battery overhead | TBD | TBD | TBD |
"""
        return table

    def generate_report(self) -> str:
        """Generate the one-page summary report."""
        lines = [
            "# Device Link Bakeoff Results\n\n",
            "## Measurements\n\n",
        ]

        if "variant_a" in self.results:
            lines.append("### Variant (a): HTTP/ndjson over Tailscale\n\n")
            for key, value in self.results["variant_a"].items():
                lines.append(f"- **{key}**: {value}\n")
            lines.append("\n")

        if "variant_b" in self.results:
            lines.append("### Variant (b): QUIC/WebTransport over Tailscale\n\n")
            for key, value in self.results["variant_b"].items():
                lines.append(f"- **{key}**: {value}\n")
            lines.append("\n")

        if "variant_c" in self.results:
            lines.append("### Variant (c): QUIC Direct\n\n")
            for key, value in self.results["variant_c"].items():
                lines.append(f"- **{key}**: {value}\n")
            lines.append("\n")

        lines.append("## Security & Privacy Comparison\n\n")
        lines.append(self.build_security_comparison_table())
        lines.append("\n")

        lines.append("## Recommendation\n\n")
        lines.append("*To be determined based on measurements.*\n")

        return "".join(lines)

    def run(self) -> None:
        """Run the full orchestration."""
        logger.info("Starting device link bakeoff orchestration")
        logger.info(f"Decisions: {json.dumps(self.decisions, indent=2)}")

        # Run variant (a) always (it's the baseline)
        self.results["variant_a"] = self.benchmark_variant_a()

        # Run variants (b) and (c) based on decisions
        if self.decisions.get("quic_lib"):
            self.results["variant_b"] = self.benchmark_variant_b()

        if self.decisions.get("variant_c_auth") != "skip":
            self.results["variant_c"] = self.benchmark_variant_c()

        # Generate report
        report = self.generate_report()
        report_path = Path(__file__).parent.parent.parent / "docs" / "plans" / "device-link-bakeoff-results.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report)

        logger.info(f"Report generated: {report_path}")
        logger.info("Orchestration complete")


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Device link bakeoff orchestrator")
    parser.add_argument(
        "--quic-lib",
        choices=["curl", "webtransport"],
        help="QUIC library choice for variant (b)",
    )
    parser.add_argument(
        "--phone-leg",
        choices=["cli-on-macbook", "follow-up-ticket", "manual"],
        help="Phone measurement strategy",
    )
    parser.add_argument(
        "--headscale-deploy",
        choices=["paper", "docker"],
        help="Headscale comparison method",
    )
    parser.add_argument(
        "--variant-c-auth",
        choices=["tls-cert", "preshared-token", "trusted-network"],
        help="Variant (c) authentication model",
    )
    args = parser.parse_args()

    decisions = {}
    if args.quic_lib:
        decisions["quic_lib"] = args.quic_lib
    if args.phone_leg:
        decisions["phone_leg"] = args.phone_leg
    if args.headscale_deploy:
        decisions["headscale_deploy"] = args.headscale_deploy
    if args.variant_c_auth:
        decisions["variant_c_auth"] = args.variant_c_auth

    orchestrator = BenchmarkOrchestrator(decisions if decisions else None)
    orchestrator.run()


if __name__ == "__main__":
    main()
