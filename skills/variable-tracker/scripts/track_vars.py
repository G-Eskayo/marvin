#!/usr/bin/env python3
"""Variable tracker CLI: find definitions and uses of Python variables."""
from __future__ import annotations

import ast
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def get_changed_files_since_ref(ref: str, search_path: str = ".") -> set[str]:
    """Get files changed since git ref, searching from search_path."""
    try:
        # Find git root from the search path
        git_root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=search_path,
        )
        git_root = git_root_result.stdout.strip()

        # Get changed files from git root
        result = subprocess.run(
            ["git", "diff", "--name-only", ref],
            capture_output=True,
            text=True,
            check=True,
            cwd=git_root,
        )

        # Convert relative paths to absolute
        if result.stdout.strip():
            rel_paths = result.stdout.strip().split("\n")
            abs_paths = {str(Path(git_root) / p) for p in rel_paths}
            return abs_paths
        return set()
    except subprocess.CalledProcessError:
        return set()


def should_skip_dir(path: Path) -> bool:
    """Check if directory should be skipped during traversal."""
    skip_dirs = {"venv", "node_modules", ".git", "__pycache__", ".venv"}
    return path.name in skip_dirs


def collect_python_files(paths: list[str], since_ref: str | None = None) -> list[Path]:
    """Collect Python files from paths, handling both files and directories."""
    python_files = []
    changed_files = None

    if since_ref:
        # Use the first path as the search point for finding git root
        search_path = paths[0] if paths else "."
        changed_files = get_changed_files_since_ref(since_ref, search_path=search_path)

    for path_str in paths:
        path = Path(path_str)

        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")

        if path.is_file():
            if path.suffix == ".py":
                if changed_files is None or str(path) in changed_files:
                    python_files.append(path)
        else:
            # Directory: recurse with skip logic
            for py_file in path.rglob("*.py"):
                # Skip files in skipped directories
                if any(should_skip_dir(p) for p in py_file.parents):
                    continue
                if changed_files is None or str(py_file) in changed_files:
                    python_files.append(py_file)

    return sorted(set(python_files))


class VariableExtractor(ast.NodeVisitor):
    """Extract variable definitions and uses from Python AST."""

    def __init__(self, filename: str):
        self.filename = filename
        self.scope_stack = ["[module]"]
        self.variables: dict[tuple[str, str], dict[str, Any]] = {}

    def current_scope(self) -> str:
        return self.scope_stack[-1]

    def register_var(
        self,
        name: str,
        kind: str,
        line: int,
        snippet: str,
        var_type: str = "",
    ) -> None:
        """Register a variable definition."""
        key = (name, self.current_scope())
        if key not in self.variables:
            self.variables[key] = {
                "name": name,
                "scope": self.current_scope(),
                "file": self.filename,
                "definitions": [],
                "uses": [],
            }
        self.variables[key]["definitions"].append({
            "line": line,
            "kind": kind,
            "snippet": snippet,
            "type": var_type,
        })

    def register_use(self, name: str, line: int, snippet: str) -> None:
        """Register a variable use."""
        key = (name, self.current_scope())
        if key not in self.variables:
            # Use before definition in this scope; create entry for it
            self.variables[key] = {
                "name": name,
                "scope": self.current_scope(),
                "file": self.filename,
                "definitions": [],
                "uses": [],
            }
        self.variables[key]["uses"].append({
            "line": line,
            "snippet": snippet,
        })

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Enter function scope."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Enter async function scope."""
        self._visit_function(node)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Common logic for function defs."""
        self.scope_stack.append(node.name)

        # Track function parameters as definitions
        for arg in node.args.args:
            self.register_var(arg.arg, "param", arg.lineno, arg.arg)
        for arg in node.args.posonlyargs:
            self.register_var(arg.arg, "param", arg.lineno, arg.arg)
        for arg in node.args.kwonlyargs:
            self.register_var(arg.arg, "param", arg.lineno, arg.arg)
        if node.args.vararg:
            self.register_var(
                node.args.vararg.arg, "param", node.args.vararg.lineno, f"*{node.args.vararg.arg}"
            )
        if node.args.kwarg:
            self.register_var(
                node.args.kwarg.arg, "param", node.args.kwarg.lineno, f"**{node.args.kwarg.arg}"
            )

        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Handle assignment statements."""
        # Get a snippet of the assignment
        snippet = self._get_snippet(node)

        for target in node.targets:
            for name in self._extract_names_from_target(target):
                self.register_var(name, "assign", node.lineno, snippet)

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Handle annotated assignment."""
        snippet = self._get_snippet(node)
        var_type = ast.unparse(node.annotation) if node.annotation else ""

        for name in self._extract_names_from_target(node.target):
            self.register_var(name, "annassign", node.lineno, snippet, var_type)

        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Handle augmented assignment (+=, etc)."""
        snippet = self._get_snippet(node)

        # AugAssign both defines and uses the target
        for name in self._extract_names_from_target(node.target):
            self.register_use(name, node.lineno, snippet)
            self.register_var(name, "augassign", node.lineno, snippet)

        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        """Handle for loop targets as definitions."""
        snippet = self._get_snippet(node)

        for name in self._extract_names_from_target(node.target):
            self.register_var(name, "for", node.lineno, snippet)

        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        """Handle with statement targets as definitions."""
        for item in node.items:
            if item.optional_vars:
                snippet = self._get_snippet(node)
                for name in self._extract_names_from_target(item.optional_vars):
                    self.register_var(name, "with", node.lineno, snippet)

        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        """Track global declarations."""
        for name in node.names:
            snippet = self._get_snippet(node)
            self.register_var(name, "global", node.lineno, snippet)
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        """Track nonlocal declarations."""
        for name in node.names:
            snippet = self._get_snippet(node)
            self.register_var(name, "nonlocal", node.lineno, snippet)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Track variable uses (Load context)."""
        if isinstance(node.ctx, ast.Load):
            snippet = node.id
            self.register_use(node.id, node.lineno, snippet)
        self.generic_visit(node)

    def _extract_names_from_target(self, target: ast.expr) -> list[str]:
        """Extract variable names from assignment targets."""
        names = []
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
            for elt in target.elts:
                names.extend(self._extract_names_from_target(elt))
        elif isinstance(target, ast.Starred):
            names.extend(self._extract_names_from_target(target.value))
        return names

    def _get_snippet(self, node: ast.AST) -> str:
        """Get a source snippet for a node."""
        try:
            return ast.unparse(node)[:80]
        except Exception:
            return ""


def extract_variables(
    *paths: str,
    name_filter: str | None = None,
    since_ref: str | None = None,
) -> list[dict[str, Any]]:
    """Extract variables from Python files.

    Args:
        *paths: File or directory paths to scan
        name_filter: If set, only return variables with this name
        since_ref: If set, only scan files changed since this git ref

    Returns:
        List of variable records with definitions and uses
    """
    if not paths:
        raise ValueError("At least one path must be provided")

    python_files = collect_python_files(list(paths), since_ref=since_ref)

    all_variables: dict[tuple[str, str, str], dict[str, Any]] = {}

    for py_file in python_files:
        try:
            source = py_file.read_text()
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        extractor = VariableExtractor(str(py_file))
        extractor.visit(tree)

        for (name, scope), var_data in extractor.variables.items():
            key = (name, scope, str(py_file))
            if key not in all_variables:
                all_variables[key] = var_data
            else:
                # Merge definitions and uses
                all_variables[key]["definitions"].extend(var_data["definitions"])
                all_variables[key]["uses"].extend(var_data["uses"])

    result = list(all_variables.values())

    # Filter by name if requested
    if name_filter:
        result = [v for v in result if v["name"] == name_filter]

    return result


def format_text_output(variables: list[dict[str, Any]]) -> str:
    """Format variables for text output."""
    lines = []

    for var in variables:
        name = var["name"]
        scope = var["scope"]
        file_path = var["file"]

        # Infer type from definitions
        var_type = None
        for defn in var["definitions"]:
            if defn.get("type"):
                var_type = defn["type"]
                break

        type_str = f"  ({var_type})" if var_type else ""

        lines.append(f"{name}  {scope}  {file_path}{type_str}")

        for defn in var["definitions"]:
            lines.append(f"  def  L{defn['line']}  {defn['snippet']}")

        for use in var["uses"]:
            lines.append(f"  use  L{use['line']}  {use['snippet']}")

    return "\n".join(lines)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Track Python variable definitions and uses"
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="File or directory paths to scan",
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Filter to a single variable name",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Only scan files changed since this git ref",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    args = parser.parse_args()

    try:
        variables = extract_variables(
            *args.paths,
            name_filter=args.name,
            since_ref=args.since,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.format == "json":
        print(json.dumps(variables, indent=2))
    else:
        print(format_text_output(variables))


if __name__ == "__main__":
    main()
