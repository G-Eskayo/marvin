#!/usr/bin/env python3
"""Frida dynamic instrumentation wrapper."""
import sys
import json
import argparse
from pathlib import Path

# Add parent directory to path to import re_common
sys.path.insert(0, str(Path(__file__).resolve().parent))

import re_common


def main():
    parser = argparse.ArgumentParser(
        description="Trace function calls using Frida (dynamic instrumentation)"
    )
    parser.add_argument(
        "--target-process",
        required=True,
        help="Process name, PID, or binary path to attach to/spawn",
    )
    parser.add_argument(
        "--function-name",
        required=True,
        help="Function name to trace (e.g., malloc, main)",
    )
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Confirm authorization to analyze this process/binary",
    )
    parser.add_argument(
        "--spawn",
        action="store_true",
        help="Spawn a new process instead of attaching to running one",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="How long to trace for (seconds)",
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

    # If target is a file path (for spawn), validate it
    if args.spawn:
        try:
            re_common.validate_binary_path(args.target_process)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Check for frida
    if not re_common.check_tool_available("frida"):
        print(
            f"Error: Frida not found on PATH. {re_common.install_hint('frida')}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Build frida command
    # Format: frida -p <pid> -c "..." or frida -n <process> -c "..." or frida <binary> -c "..."
    try:
        if args.spawn:
            cmd = ["frida", args.target_process, "-c", f"trace('{args.function_name}')"]
        else:
            # Assume it's a process name or PID
            cmd = ["frida", "-n", args.target_process, "-c", f"trace('{args.function_name}')"]

        result = re_common.run_subprocess(cmd, timeout=args.timeout + 5)

        if result.returncode != 0 and "Process not found" in result.stderr:
            print(
                f"Error: Process '{args.target_process}' not found. "
                f"Is it running? (Or use --spawn to launch it)",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"Target: {args.target_process}")
        print(f"Function: {args.function_name}")
        print(f"Duration: {args.timeout}s\n")
        print("=== Trace Output ===")
        print(result.stdout)
        if result.stderr:
            print("\n=== Errors/Warnings ===")
            print(result.stderr)

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
