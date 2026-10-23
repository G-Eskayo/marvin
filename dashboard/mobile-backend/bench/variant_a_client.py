#!/usr/bin/env python3
"""Variant (a) bench client: HTTP/ndjson over Tailscale.

Measures RTT, TTFT, and throughput against the real `/live` stream endpoint
and a new `/bench/echo` endpoint on variant (a) server.
"""
import json
import sys
import time
import requests
from pathlib import Path
from typing import Dict, List, Tuple
import statistics

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import lib.metrics_registry as metrics_registry
from dashboard.mobile-backend.bench.harness import (
    PayloadGenerator,
    MetricsRecorder,
    wait_for_server,
)


class VariantAClient:
    """Benchmark client for variant (a) — HTTP over Tailscale."""

    def __init__(self, host: str, port: int = 9001, timeout: int = 30):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{host}:{port}"
        self.metrics = MetricsRecorder("variant_a")

    def wait_ready(self) -> bool:
        """Wait for server to be ready."""
        return wait_for_server(self.host, self.port)

    def measure_rtt(self, num_samples: int = 100) -> Dict[str, float]:
        """Measure round-trip time via /bench/echo."""
        rtts = []
        payload = PayloadGenerator.generate_payload(1024, seed=42)

        for i in range(num_samples):
            try:
                start = time.time()
                response = requests.post(
                    f"{self.base_url}/bench/echo",
                    json=payload,
                    timeout=self.timeout,
                )
                elapsed = (time.time() - start) * 1000  # Convert to ms

                if response.status_code == 200:
                    rtts.append(elapsed)
            except requests.RequestException as e:
                print(f"RTT sample {i} failed: {e}", file=sys.stderr)
                continue

        if rtts:
            return {
                "min_ms": min(rtts),
                "max_ms": max(rtts),
                "mean_ms": statistics.mean(rtts),
                "median_ms": statistics.median(rtts),
                "stdev_ms": statistics.stdev(rtts) if len(rtts) > 1 else 0,
                "samples": len(rtts),
            }
        return {}

    def measure_ttft(self, num_samples: int = 100) -> Dict[str, float]:
        """Measure time-to-first-token against /live stream."""
        ttfts = []

        for i in range(num_samples):
            try:
                start = time.time()
                with requests.get(
                    f"{self.base_url}/live",
                    stream=True,
                    timeout=self.timeout,
                ) as response:
                    if response.status_code == 200:
                        # Read first line (first token)
                        for line in response.iter_lines():
                            if line:
                                ttft = (time.time() - start) * 1000
                                ttfts.append(ttft)
                                break
            except requests.RequestException as e:
                print(f"TTFT sample {i} failed: {e}", file=sys.stderr)
                continue

        if ttfts:
            return {
                "min_ms": min(ttfts),
                "max_ms": max(ttfts),
                "mean_ms": statistics.mean(ttfts),
                "median_ms": statistics.median(ttfts),
                "stdev_ms": statistics.stdev(ttfts) if len(ttfts) > 1 else 0,
                "samples": len(ttfts),
            }
        return {}

    def measure_throughput(self, duration_seconds: int = 10) -> Dict[str, float]:
        """Measure throughput over /live stream."""
        start = time.time()
        bytes_received = 0
        lines_received = 0

        try:
            with requests.get(
                f"{self.base_url}/live",
                stream=True,
                timeout=self.timeout,
            ) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if time.time() - start > duration_seconds:
                            break
                        if line:
                            bytes_received += len(line) + 1  # +1 for newline
                            lines_received += 1
        except requests.RequestException as e:
            print(f"Throughput measurement failed: {e}", file=sys.stderr)

        elapsed = time.time() - start
        if elapsed > 0:
            return {
                "bytes_received": bytes_received,
                "lines_received": lines_received,
                "duration_seconds": elapsed,
                "throughput_kbps": (bytes_received * 8) / (elapsed * 1000),
                "lines_per_second": lines_received / elapsed,
            }
        return {}

    def run_benchmark(self) -> Dict[str, float]:
        """Run all benchmarks and record metrics."""
        print("Starting variant (a) benchmark...")

        if not self.wait_ready():
            print("Server not ready", file=sys.stderr)
            return {}

        self.metrics.start()

        # Run measurements
        rtt_results = self.measure_rtt(num_samples=50)
        print(f"RTT: {rtt_results.get('mean_ms', 'N/A'):.2f}ms")

        ttft_results = self.measure_ttft(num_samples=20)
        print(f"TTFT: {ttft_results.get('mean_ms', 'N/A'):.2f}ms")

        throughput_results = self.measure_throughput(duration_seconds=5)
        print(f"Throughput: {throughput_results.get('throughput_kbps', 'N/A'):.1f} kbps")

        # Record metrics
        all_metrics = {}
        if rtt_results:
            self.metrics.record_metric("rtt_median_ms", rtt_results["median_ms"], higher_is_better=False)
            all_metrics.update(rtt_results)

        if ttft_results:
            self.metrics.record_metric("ttft_median_ms", ttft_results["median_ms"], higher_is_better=False)
            all_metrics.update(ttft_results)

        if throughput_results:
            self.metrics.record_metric(
                "throughput_kbps",
                throughput_results["throughput_kbps"],
                higher_is_better=True,
            )
            all_metrics.update(throughput_results)

        self.metrics.finalize()
        return all_metrics


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Variant (a) benchmark client")
    parser.add_argument("--host", default="100.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=9001, help="Server port")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    client = VariantAClient(args.host, args.port)
    results = client.run_benchmark()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for key, value in results.items():
            if isinstance(value, float):
                print(f"{key}: {value:.2f}")
            else:
                print(f"{key}: {value}")


if __name__ == "__main__":
    main()
