#!/usr/bin/env python3
"""Radare2/Rizin static analysis wrapper."""
import sys
import json
import argparse
from pathlib import Path

# Add parent directory to path to import re_common
sys.path.insert(0, str(Path(__file__).resolve().parent))

import re_common


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a binary using Radare2 or Rizin (static analysis)"
    )
    parser.add_argument("--binary", required=True, help="Path to the binary to analyze")
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Confirm authorization to analyze this binary",
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

    # Check for radare2 or rizin
    tool = None
    if re_common.check_tool_available("rizin"):
        tool = "rizin"
    elif re_common.check_tool_available("r2"):
        tool = "r2"
    else:
        print(
            f"Error: radare2/rizin not found on PATH. {re_common.install_hint('r2')}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Run radare2/rizin analysis
    # Use -A flag for auto-analysis, -c to run commands
    try:
        # Get functions
        result_funcs = re_common.run_subprocess(
            [tool, "-A", "-c", "afl", args.binary],
            timeout=30,
        )

        # Get strings
        result_strings = re_common.run_subprocess(
            [tool, "-A", "-c", "iz", args.binary],
            timeout=30,
        )

        # Get imports
        result_imports = re_common.run_subprocess(
            [tool, "-A", "-c", "ii", args.binary],
            timeout=30,
        )

        if args.output_format == "json":
            output = {
                "binary": args.binary,
                "tool": tool,
                "functions": result_funcs.stdout if result_funcs.returncode == 0 else "",
                "strings": result_strings.stdout if result_strings.returncode == 0 else "",
                "imports": result_imports.stdout if result_imports.returncode == 0 else "",
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"Binary: {args.binary}")
            print(f"Tool: {tool}\n")
            print("=== Functions ===")
            print(result_funcs.stdout)
            print("\n=== Strings ===")
            print(result_strings.stdout)
            print("\n=== Imports ===")
            print(result_imports.stdout)

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
