#!/usr/bin/env python3
"""Ghidra headless analysis wrapper."""
import sys
import json
import argparse
import tempfile
from pathlib import Path

# Add parent directory to path to import re_common
sys.path.insert(0, str(Path(__file__).resolve().parent))

import re_common


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a binary using Ghidra (static analysis, decompilation)"
    )
    parser.add_argument("--binary", required=True, help="Path to the binary to analyze")
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Confirm authorization to analyze this binary",
    )
    parser.add_argument(
        "--function-name",
        default=None,
        help="Specific function to decompile (optional)",
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "text"],
        default="text",
        help="Output format",
    )

    args = parser.parse_args()

    # Check authorization
    if not args.authorized:
        if sys.argv.count("--authorized") == 0:
            try:
                re_common.check_authorization()
            except RuntimeError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

    # Validate binary path
    try:
        re_common.validate_binary_path(args.binary)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Check for analyzeHeadless
    if not re_common.check_tool_available("analyzeHeadless"):
        print(
            f"Error: Ghidra analyzeHeadless not found on PATH. "
            f"{re_common.install_hint('analyzeHeadless')}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Create a temporary project directory for analysis
    with tempfile.TemporaryDirectory(prefix="ghidra_") as tmpdir:
        project_dir = Path(tmpdir)
        project_name = "analysis"

        try:
            # Run analyzeHeadless to import and analyze the binary
            # Format: analyzeHeadless <project_dir> <project_name> [options] -import <binary> -analyze
            cmd = [
                "analyzeHeadless",
                str(project_dir),
                project_name,
                "-import",
                args.binary,
                "-analyze",
            ]

            result = re_common.run_subprocess(cmd, timeout=60)

            if result.returncode != 0:
                print(
                    f"Error: Ghidra analysis failed.\nStdout: {result.stdout}\nStderr: {result.stderr}",
                    file=sys.stderr,
                )
                sys.exit(1)

            # Parse output (this is simplified; real implementation would run a Ghidra script)
            if args.output_format == "json":
                output = {
                    "binary": args.binary,
                    "tool": "Ghidra",
                    "analysis_output": result.stdout,
                }
                print(json.dumps(output, indent=2))
            else:
                print(f"Binary: {args.binary}")
                print(f"Tool: Ghidra\n")
                print("=== Analysis Output ===")
                print(result.stdout)

        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
