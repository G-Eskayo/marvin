#!/usr/bin/env python3
"""Scan a project directory and store patterns in the qa-knowledge ChromaDB collection.

Usage:
    ~/.agents/venv/bin/python qa_scan.py /path/to/project
    ~/.agents/venv/bin/python qa_scan.py /path/to/project --dry-run
"""
from __future__ import annotations
import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CHROMA_PATH = Path.home() / ".claude" / "chroma"
COLLECTION  = "qa-knowledge"

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env",
             ".tox", "dist", "build", ".next", ".nuxt", "coverage", "target"}
SKIP_EXT  = {".pyc", ".pyo", ".map", ".min.js", ".min.css", ".lock"}

MARKER_RE = re.compile(r"#\s*(TODO|FIXME|HACK|BUG|XXX|NOTE)\s*:?\s*(.+)", re.IGNORECASE)

# ── complexity + principles analysis ─────────────────────────────────────────

class ComplexityVisitor(ast.NodeVisitor):
    """Walk an AST and collect complexity signals."""

    def __init__(self):
        self.issues: list[dict] = []
        self._loop_depth = 0
        self._nesting_depth = 0

    def _issue(self, kind: str, msg: str, line: int, suggestion: str = ""):
        self.issues.append({"kind": kind, "msg": msg, "line": line, "suggestion": suggestion})

    # ── nested loops → O(n²) or worse ────────────────────────────────────────
    def visit_For(self, node):
        self._loop_depth += 1
        if self._loop_depth >= 2:
            self._issue(
                "complexity",
                f"Nested loop at line {node.lineno} — likely O(n²) or worse.",
                node.lineno,
                "Consider dict/set lookup, sorting + two-pointer, or vectorised ops.",
            )
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_While(self, node):
        self._loop_depth += 1
        if self._loop_depth >= 2:
            self._issue(
                "complexity",
                f"Nested while-loop at line {node.lineno} — likely O(n²) or worse.",
                node.lineno,
                "Restructure with a single pass or auxiliary data structure.",
            )
        self.generic_visit(node)
        self._loop_depth -= 1

    # ── linear search inside a loop → O(n²) ──────────────────────────────────
    def visit_Call(self, node):
        if self._loop_depth >= 1:
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ("index", "find", "count", "remove"):
                    self._issue(
                        "complexity",
                        f"list.{node.func.attr}() inside a loop at line {node.lineno} — O(n²).",
                        node.lineno,
                        "Build a dict/set before the loop for O(1) lookup.",
                    )
        self.generic_visit(node)

    # ── UNIX / KISS: large functions ──────────────────────────────────────────
    def visit_FunctionDef(self, node):
        length = (node.end_lineno or node.lineno) - node.lineno
        if length > 40:
            self._issue(
                "kiss",
                f"Function '{node.name}' at line {node.lineno} is {length} lines long.",
                node.lineno,
                "UNIX principle: do one thing. Extract sub-functions for each logical step.",
            )
        # KISS: too many parameters
        n_args = len(node.args.args) + len(node.args.posonlyargs)
        if n_args > 5:
            self._issue(
                "kiss",
                f"Function '{node.name}' at line {node.lineno} takes {n_args} parameters.",
                node.lineno,
                "KISS: group related args into a dataclass/dict, or split the function.",
            )
        self._nesting_depth += 1
        self.generic_visit(node)
        self._nesting_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    # ── OOP: methods that never use self → potential static ───────────────────
    def visit_ClassDef(self, node):
        for item in ast.walk(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not item.args.args:
                    continue
                first_arg = item.args.args[0].arg
                if first_arg != "self":
                    continue
                uses_self = any(
                    isinstance(n, ast.Name) and n.id == "self"
                    for n in ast.walk(item)
                    if n is not item.args.args[0]
                )
                if not uses_self and item.name not in ("__init__", "__new__", "__class_getitem__"):
                    self._issue(
                        "oop",
                        f"Method '{item.name}' in class '{node.name}' (line {item.lineno}) "
                        f"never uses self — consider @staticmethod or moving it out.",
                        item.lineno,
                        "OOP: static methods signal the method doesn't belong to instance state.",
                    )
        self.generic_visit(node)


def analyze_python_file(path: Path) -> list[dict]:
    """Return complexity/principles issues for a single .py file."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return []
    visitor = ComplexityVisitor()
    visitor.visit(tree)
    for issue in visitor.issues:
        issue["file"] = str(path)
    return visitor.issues


def analyze_complexity(project: Path) -> list[dict]:
    """Run complexity + principles analysis across all Python files."""
    all_issues = []
    for f in _iter_files(project):
        if f.suffix == ".py":
            all_issues.extend(analyze_python_file(f))
    return all_issues


# ── stack detection ───────────────────────────────────────────────────────────

def detect_stack(project: Path) -> list[str]:
    stack = []
    if (project / "requirements.txt").exists() or \
       (project / "pyproject.toml").exists() or \
       (project / "setup.py").exists():
        stack.append("python")
    if (project / "package.json").exists():
        stack.append("javascript")
    if (project / "go.mod").exists():
        stack.append("go")
    if (project / "Cargo.toml").exists():
        stack.append("rust")
    if (project / "pom.xml").exists() or list(project.glob("*.gradle")):
        stack.append("java")
    if not stack:
        # fallback: count source files
        exts = {}
        for f in _iter_files(project):
            exts[f.suffix] = exts.get(f.suffix, 0) + 1
        mapping = {".py": "python", ".js": "javascript", ".ts": "typescript",
                   ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby"}
        top = sorted(exts.items(), key=lambda x: -x[1])[:3]
        for ext, _ in top:
            if ext in mapping:
                stack.append(mapping[ext])
    return list(dict.fromkeys(stack))  # dedup, order preserved


# ── dependency extraction ─────────────────────────────────────────────────────

def extract_dependencies(project: Path) -> list[dict]:
    deps = []

    req = project / "requirements.txt"
    if req.exists():
        for line in req.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = re.split(r"[>=<!;\[]", line)[0].strip()
            if name:
                deps.append({"name": name.lower(), "source": "requirements.txt", "language": "python"})

    pkg = project / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                for name in data.get(section, {}):
                    deps.append({"name": name.lower(), "source": "package.json", "language": "javascript"})
        except (json.JSONDecodeError, AttributeError):
            pass

    pyproj = project / "pyproject.toml"
    if pyproj.exists():
        # simple regex parse — avoid toml dep
        for m in re.finditer(r'"([a-zA-Z0-9_-]+)(?:[>=<!][^"]*)?"\s*,', pyproj.read_text()):
            deps.append({"name": m.group(1).lower(), "source": "pyproject.toml", "language": "python"})

    # deduplicate by name
    seen = set()
    result = []
    for d in deps:
        if d["name"] not in seen:
            seen.add(d["name"])
            result.append(d)
    return result


# ── import extraction ─────────────────────────────────────────────────────────

def extract_imports(project: Path) -> set[str]:
    """Return set of top-level module names imported across all .py files."""
    modules: set[str] = set()
    for f in _iter_files(project):
        if f.suffix != ".py":
            continue
        try:
            tree = ast.parse(f.read_text(errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    modules.add(node.module.split(".")[0])
    return modules


# ── marker extraction ─────────────────────────────────────────────────────────

def extract_markers(project: Path) -> list[dict]:
    """Return TODO/FIXME/HACK/BUG comments with file + line context."""
    markers = []
    for f in _iter_files(project):
        if f.suffix in {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".sh"}:
            try:
                for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                    m = MARKER_RE.search(line)
                    if m:
                        markers.append({
                            "marker": m.group(1).upper(),
                            "text": m.group(2).strip(),
                            "file": str(f.relative_to(project)),
                            "line": i,
                        })
            except OSError:
                continue
    return markers


# ── helpers ───────────────────────────────────────────────────────────────────

def _iter_files(project: Path):
    for f in project.rglob("*"):
        if f.is_file() and not any(part in SKIP_DIRS for part in f.parts) \
                and f.suffix not in SKIP_EXT:
            yield f


def _make_id(text: str) -> str:
    import hashlib
    return "qa-" + hashlib.sha256(text.encode()).hexdigest()[:16]


# ── store ─────────────────────────────────────────────────────────────────────

def store_entries(entries: list[dict], dry_run: bool = False) -> int:
    if dry_run:
        return len(entries)
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    col = client.get_or_create_collection(COLLECTION)
    existing = set(col.get()["ids"])
    new = [e for e in entries if e["id"] not in existing]
    if new:
        col.add(
            documents=[e["document"] for e in new],
            metadatas=[e["metadata"] for e in new],
            ids=[e["id"] for e in new],
        )
    return len(new)


# ── main ──────────────────────────────────────────────────────────────────────

def scan(project: Path, dry_run: bool = False) -> list[dict]:
    project = project.resolve()
    name = project.name
    now = datetime.now(timezone.utc).isoformat()

    entries: list[dict] = []

    def add(document: str, category: str, **meta):
        entries.append({
            "id": _make_id(document),
            "document": document,
            "metadata": {
                "category": category,
                "source": "project-scan",
                "project": name,
                "created_at": now,
                "language": meta.pop("language", "all"),
                "library": meta.pop("library", ""),
                "tags": meta.pop("tags", ""),
                "confidence": meta.pop("confidence", "medium"),
                **meta,
            },
        })

    # stack
    stack = detect_stack(project)
    add(f"Project '{name}' uses stack: {', '.join(stack) or 'unknown'}",
        "config", tags=",".join(stack), language=",".join(stack))

    # dependencies → one entry per library
    deps = extract_dependencies(project)
    for d in deps:
        add(f"Project '{name}' depends on library: {d['name']} (from {d['source']})",
            "library", library=d["name"], language=d["language"],
            tags=f"{d['name']},{d['language']}")

    # import patterns
    imports = extract_imports(project)
    stdlib = {"os", "sys", "re", "json", "pathlib", "collections", "itertools",
              "functools", "typing", "datetime", "math", "time", "io", "abc",
              "copy", "enum", "logging", "unittest", "argparse", "subprocess",
              "shutil", "tempfile", "hashlib", "random", "string", "struct",
              "threading", "multiprocessing", "asyncio", "socket", "http"}
    third_party = imports - stdlib
    if third_party:
        add(f"Project '{name}' imports these third-party modules: {', '.join(sorted(third_party))}",
            "pattern", language="python", tags=",".join(sorted(third_party)))

    # markers
    markers = extract_markers(project)
    for m in markers:
        category = "failed" if m["marker"] in ("FIXME", "BUG", "HACK") else "pattern"
        add(
            f"[{m['marker']}] in '{name}/{m['file']}' line {m['line']}: {m['text']}",
            category,
            tags=f"{m['marker'].lower()},marker",
            confidence="low",
        )

    # complexity + principles (UNIX, KISS, OOP)
    complexity_issues = analyze_complexity(project)
    kind_to_tags = {
        "complexity": "complexity,performance,optimization",
        "kiss":       "kiss,unix-principle,readability",
        "oop":        "oop,static-method,refactor",
    }
    for issue in complexity_issues:
        rel_file = Path(issue["file"]).relative_to(project) if Path(issue["file"]).is_absolute() else issue["file"]
        doc = (
            f"[{issue['kind'].upper()}] {issue['msg']} "
            f"(file: {rel_file}) "
            f"Suggestion: {issue['suggestion']}"
        )
        add(
            doc,
            "anti-pattern",
            tags=kind_to_tags.get(issue["kind"], issue["kind"]),
            language="python",
            confidence="medium",
        )

    return entries


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan a project into qa-knowledge")
    ap.add_argument("project", help="path to project directory")
    ap.add_argument("--dry-run", action="store_true", help="print entries without storing")
    args = ap.parse_args()

    project = Path(args.project)
    if not project.exists():
        sys.exit(f"project not found: {project}")

    entries = scan(project, dry_run=args.dry_run)

    if args.dry_run:
        for e in entries:
            print(f"[{e['metadata']['category']}] {e['document'][:100]}")
        print(f"\n{len(entries)} entries (dry run — nothing stored)")
        return

    added = store_entries(entries)
    print(f"Scanned '{project.name}': {len(entries)} entries found, {added} new stored in {COLLECTION}")


if __name__ == "__main__":
    main()
