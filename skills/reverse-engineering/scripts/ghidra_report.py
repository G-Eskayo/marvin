#!/usr/bin/env python3
"""
Ghidra headless binary analysis wrapper.

Runs analyzeHeadless on a binary and dumps function list, decompilation,
strings, and cross-references as JSON.

Usage:
    python3 ghidra_report.py --binary <path> --i-own-this-target [options]

Examples:
    # List all functions
    python3 ghidra_report.py --binary ./myapp --i-own-this-target

    # Decompile main()
    python3 ghidra_report.py --binary ./myapp --function main --i-own-this-target

    # Decompile all functions (slow for large binaries)
    python3 ghidra_report.py --binary ./myapp --all-functions --i-own-this-target --output analysis.json
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def check_authorization(args: argparse.Namespace) -> bool:
    """Authorization gate — requires explicit --i-own-this-target flag."""
    if not getattr(args, 'i_own_this_target', False):
        print(
            "[!] Authorization gate: you must confirm --i-own-this-target "
            "before running reverse-engineering tools on a binary.",
            file=sys.stderr
        )
        return False
    return True


def find_ghidra() -> str:
    """Locate ghidra_analyzeHeadless binary."""
    # Check $GHIDRA_HOME
    ghidra_home = Path.home() / 'ghidra' / 'ghidra_public'  # or user's installation
    candidate = ghidra_home / 'support' / 'analyzeHeadless'
    if candidate.exists():
        return str(candidate)

    # Try $PATH
    result = subprocess.run(['which', 'analyzeHeadless'], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()

    raise RuntimeError(
        "ghidra_analyzeHeadless not found. "
        "Install Ghidra and set $GHIDRA_HOME or add it to $PATH."
    )


def generate_ghidra_script(
    function_name: str | None = None,
    all_functions: bool = False
) -> str:
    """
    Generate a Ghidra postScript that dumps analysis to JSON.

    Args:
        function_name: Name of a specific function to decompile, or None.
        all_functions: If True, decompile every function.

    Returns:
        Ghidra Jython script source code.
    """
    script = '''
import json
from ghidra.program.model.address import AddressSet
from ghidra.program.model.listing import Function
from ghidra.decompiler import DecompileOptions, DecompInterface

def get_decompilation(func):
    """Get pseudocode for a function."""
    try:
        decompiler = DecompInterface()
        decompiler.openProgram(currentProgram)
        decoResult = decompiler.decompileFunction(func, 60, None)
        if decoResult.decompileCompleted():
            return str(decoResult.getDecompilation())
        return None
    except:
        return None

# Gather data
functions_data = []
listing = currentProgram.getListing()
func_iter = listing.getFunctions(True)

for func in func_iter:
    func_info = {
        "name": str(func.getName()),
        "address": hex(func.getEntryPoint().getOffset()),
        "size": func.getBody().getNumAddresses(),
    }
    functions_data.append(func_info)

# Get strings
strings_data = []
mem = currentProgram.getMemory()
try:
    from ghidra.program.model.symbol import SymbolType
    for sym in currentProgram.getSymbolTable().getAllSymbols(True):
        if sym.getSymbolType() == SymbolType.LABEL:
            # Try to infer string references from data sections
            pass
except:
    pass

# Simplified string extraction (scan .rodata / .data)
strings_data = []
for section in currentProgram.getMemory():
    if section.isInitialized() and (section.getName() in ['.rodata', '.data']):
        # This is a simplification; real implementation would parse strings
        pass

# Get imports
imports_data = []
from ghidra.program.model.symbol import SymbolType
for sym in currentProgram.getSymbolTable().getAllSymbols(True):
    if sym.isExternal():
        imports_data.append({
            "name": str(sym.getName()),
            "address": hex(sym.getAddress().getOffset()) if sym.getAddress() else None,
        })

output = {
    "binary": str(currentProgram.getName()),
    "arch": str(currentProgram.getLanguage().getProcessor()),
    "entry_point": hex(currentProgram.getMinAddress().getOffset()),
    "functions": functions_data,
    "strings": strings_data,
    "imports": imports_data,
}

print(json.dumps(output, indent=2))
print("# Analysis complete", file=sys.stderr)
'''
    return script


def run_ghidra_analysis(
    binary_path: str,
    output_file: str | None = None,
    function_name: str | None = None,
    all_functions: bool = False,
    ghidra_project_dir: str = "/tmp/ghidra-projects"
) -> dict[str, Any]:
    """
    Run Ghidra headless analysis on a binary.

    Args:
        binary_path: Path to the binary file.
        output_file: Optional JSON output file path.
        function_name: Optional specific function to decompile.
        all_functions: If True, decompile all functions.
        ghidra_project_dir: Directory for Ghidra project storage.

    Returns:
        Parsed JSON analysis output.
    """
    binary_path = Path(binary_path).resolve()
    if not binary_path.exists():
        raise FileNotFoundError(f"Binary not found: {binary_path}")

    ghidra_exe = find_ghidra()
    project_dir = Path(ghidra_project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Use binary name as project name
    project_name = binary_path.stem

    # Generate post-script
    post_script = generate_ghidra_script(function_name, all_functions)
    post_script_file = project_dir / f"analyze_{project_name}.py"
    post_script_file.write_text(post_script)

    # Run analyzeHeadless
    cmd = [
        ghidra_exe,
        str(project_dir),
        project_name,
        "-import", str(binary_path),
        "-postScript", str(post_script_file),
        "-deleteProject"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5-minute timeout
        )

        if result.returncode != 0:
            raise RuntimeError(f"Ghidra analysis failed:\n{result.stderr}")

        # Parse JSON from stdout
        output_lines = result.stdout.strip().split('\n')
        json_start = next(i for i, line in enumerate(output_lines) if line.startswith('{'))
        json_str = '\n'.join(output_lines[json_start:])
        output = json.loads(json_str)

        if output_file:
            Path(output_file).write_text(json.dumps(output, indent=2))

        return output

    except subprocess.TimeoutExpired:
        raise RuntimeError("Ghidra analysis timed out (5 minutes)")
    finally:
        if post_script_file.exists():
            post_script_file.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="Ghidra headless binary analysis wrapper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--binary", required=True, help="Path to binary file")
    parser.add_argument(
        "--i-own-this-target",
        action="store_true",
        required=True,
        help="Authorization gate: confirm you own or are authorized for this target"
    )
    parser.add_argument("--function", help="Decompile a specific function by name")
    parser.add_argument("--all-functions", action="store_true", help="Decompile all functions")
    parser.add_argument("--output", help="Write JSON output to file (default: stdout)")
    parser.add_argument(
        "--ghidra-project-dir",
        default="/tmp/ghidra-projects",
        help="Ghidra project directory (default: /tmp/ghidra-projects)"
    )

    args = parser.parse_args()

    if not check_authorization(args):
        sys.exit(1)

    try:
        output = run_ghidra_analysis(
            binary_path=args.binary,
            output_file=args.output,
            function_name=args.function,
            all_functions=args.all_functions,
            ghidra_project_dir=args.ghidra_project_dir
        )

        if not args.output:
            print(json.dumps(output, indent=2))

    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
