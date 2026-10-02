#!/usr/bin/env python3
"""Variable tracker — tracks declarations and uses of variables across Python and text files."""

import ast
import re
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional


class PythonVariableTracker:
    """Track variable declarations and uses in Python code via AST."""

    def __init__(self):
        self.scopes: Dict[str, Dict] = {}
        self.current_scope = "module"

    def track_file(self, filepath: str) -> Dict[str, Dict]:
        """Track variables in a Python file."""
        with open(filepath) as f:
            content = f.read()

        tree = ast.parse(content, filename=filepath)
        self.scopes = {"module": {}}
        self.current_scope = "module"

        lines = content.split('\n')
        self.visit(tree, lines)

        return self.scopes

    def visit(self, node, lines: List[str]):
        """Recursively visit AST nodes."""
        if isinstance(node, ast.Module):
            for child in node.body:
                self.visit(child, lines)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            old_scope = self.current_scope
            scope_name = f"function:{node.name}:{node.lineno}"
            self.scopes[scope_name] = {}
            self.current_scope = scope_name

            for arg in node.args.args:
                self._declare_var(arg.arg, arg.lineno,
                                _get_annotation_str(arg.annotation) if arg.annotation else "unknown")

            for child in node.body:
                self.visit(child, lines)

            self.current_scope = old_scope

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                self._process_target(target, node.lineno, lines)
            self._process_value(node.value, lines)

        elif isinstance(node, ast.AnnAssign):
            self._process_target(node.target, node.lineno, lines)
            type_str = _get_annotation_str(node.annotation)
            if node.value:
                self._process_value(node.value, lines)
            self._declare_var(_extract_name(node.target), node.lineno, type_str)

        elif isinstance(node, ast.AugAssign):
            self._process_target(node.target, node.lineno, lines)
            self._process_value(node.value, lines)

        elif isinstance(node, ast.For):
            self._process_target(node.target, node.lineno, lines)
            self._process_value(node.iter, lines)
            for child in node.body:
                self.visit(child, lines)
            for child in node.orelse:
                self.visit(child, lines)

        elif isinstance(node, ast.AsyncFor):
            self._process_target(node.target, node.lineno, lines)
            self._process_value(node.iter, lines)
            for child in node.body:
                self.visit(child, lines)
            for child in node.orelse:
                self.visit(child, lines)

        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars:
                    self._process_target(item.optional_vars, node.lineno, lines)
                self._process_value(item.context_expr, lines)
            for child in node.body:
                self.visit(child, lines)

        elif isinstance(node, ast.AsyncWith):
            for item in node.items:
                if item.optional_vars:
                    self._process_target(item.optional_vars, node.lineno, lines)
                self._process_value(item.context_expr, lines)
            for child in node.body:
                self.visit(child, lines)

        elif isinstance(node, ast.If):
            self._process_value(node.test, lines)
            for child in node.body:
                self.visit(child, lines)
            for child in node.orelse:
                self.visit(child, lines)

        elif isinstance(node, (ast.While, ast.comprehension)):
            if hasattr(node, 'test'):
                self._process_value(node.test, lines)
            if hasattr(node, 'body'):
                for child in node.body:
                    self.visit(child, lines)
            if hasattr(node, 'orelse'):
                for child in node.orelse:
                    self.visit(child, lines)

        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for generator in node.generators:
                self.visit(generator, lines)

        else:
            for child in ast.iter_child_nodes(node):
                self.visit(child, lines)

    def _process_target(self, target, lineno: int, lines: List[str]):
        """Process assignment target to extract declared names."""
        if isinstance(target, ast.Name):
            inferred_type = _infer_type(target, lines)
            self._declare_var(target.id, lineno, inferred_type)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._process_target(elt, lineno, lines)

    def _process_value(self, node, lines: List[str]):
        """Process value expressions to find uses of variables."""
        if isinstance(node, ast.Name):
            self._use_var(node.id, node.lineno)
        else:
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    self._use_var(child.id, child.lineno)

    def _declare_var(self, name: str, lineno: int, type_str: str):
        """Record a variable declaration."""
        if name not in self.scopes[self.current_scope]:
            self.scopes[self.current_scope][name] = {
                "declared_line": lineno,
                "type": type_str,
                "uses": []
            }

    def _use_var(self, name: str, lineno: int):
        """Record a variable use."""
        if name in self.scopes[self.current_scope]:
            if lineno != self.scopes[self.current_scope][name]["declared_line"]:
                self.scopes[self.current_scope][name]["uses"].append(lineno)


class TextVariableTracker:
    """Fallback: approximate variable tracking via regex for non-Python files."""

    def track_file(self, filepath: str) -> Dict[str, Dict]:
        """Track variables in a text file (approximate)."""
        with open(filepath) as f:
            content = f.read()

        lines = content.split('\n')
        scope = {}

        for line_num, line in enumerate(lines, 1):
            # Detect declarations: const/let/var <name> =
            decl_match = re.search(r'\b(const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=', line)
            if decl_match:
                var_name = decl_match.group(2)
                if var_name not in scope:
                    scope[var_name] = {
                        "declared_line": line_num,
                        "type": "unknown (regex-detected)",
                        "uses": []
                    }

        for line_num, line in enumerate(lines, 1):
            for var_name in scope:
                if line_num != scope[var_name]["declared_line"]:
                    if re.search(rf'\b{re.escape(var_name)}\b', line):
                        scope[var_name]["uses"].append(line_num)

        return {"module": scope}


def _extract_name(node) -> str:
    """Extract variable name from a target node."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        names = []
        for elt in node.elts:
            names.append(_extract_name(elt))
        return f"({', '.join(names)})"
    else:
        return "unknown"


def _get_annotation_str(annotation) -> str:
    """Convert an annotation AST node to a string."""
    if annotation is None:
        return "unknown"
    return ast.unparse(annotation)


def _infer_type(node, lines: List[str]) -> str:
    """Infer type from a Name node's context (simplified)."""
    return "unknown"


def format_compact_table(all_scopes: Dict[str, Dict], filter_var: Optional[str] = None) -> str:
    """Format tracked variables as a compact table."""
    output = []

    for scope_name, variables in all_scopes.items():
        if scope_name == "module":
            scope_label = "module scope"
        else:
            scope_label = scope_name.replace("function:", "").replace(":", " L")

        output.append(f"\n**{scope_label}**\n")

        for var_name in sorted(variables.keys(), key=lambda k: variables[k]["declared_line"]):
            if filter_var and var_name != filter_var:
                continue

            info = variables[var_name]
            var_type = info["type"]
            declared = info["declared_line"]
            uses = info["uses"]

            if uses:
                uses_str = f"L{', L'.join(str(u) for u in sorted(set(uses)))}"
                output.append(f"- **{var_name}** ({var_type}, declared L{declared}) → used: {uses_str}")
            else:
                output.append(f"- **{var_name}** ({var_type}, declared L{declared}) → unused")

    return "".join(output)


def format_json_output(all_scopes: Dict[str, Dict], filter_var: Optional[str] = None) -> str:
    """Format as JSON."""
    result = {}

    for scope_name, variables in all_scopes.items():
        scope_data = {}
        for var_name, info in variables.items():
            if filter_var and var_name != filter_var:
                continue
            scope_data[var_name] = {
                "declared_line": info["declared_line"],
                "type": info["type"],
                "uses": sorted(set(info["uses"]))
            }
        result[scope_name] = scope_data

    return json.dumps(result, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Track variable declarations and uses")
    parser.add_argument("paths", nargs="+", help="File paths to analyze")
    parser.add_argument("--var", help="Filter to a specific variable name")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    all_results = {}

    for path_str in args.paths:
        path = Path(path_str)
        if not path.exists():
            print(f"Error: {path} does not exist", file=sys.stderr)
            sys.exit(1)

        if path.suffix == ".py":
            tracker = PythonVariableTracker()
        else:
            tracker = TextVariableTracker()

        scopes = tracker.track_file(str(path))
        all_results[path_str] = scopes

    if args.json:
        # Flatten for JSON output
        combined = {}
        for path_str, scopes in all_results.items():
            combined[path_str] = {}
            for scope_name, variables in scopes.items():
                combined[path_str][scope_name] = {}
                for var_name, info in variables.items():
                    if args.var and var_name != args.var:
                        continue
                    combined[path_str][scope_name][var_name] = {
                        "declared_line": info["declared_line"],
                        "type": info["type"],
                        "uses": sorted(set(info["uses"]))
                    }
        print(json.dumps(combined, indent=2))
    else:
        for path_str, scopes in all_results.items():
            print(f"\n## {path_str}\n")
            print(format_compact_table(scopes, args.var))


if __name__ == "__main__":
    main()
