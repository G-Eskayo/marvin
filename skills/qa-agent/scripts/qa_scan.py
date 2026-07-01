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

# ── domain inference ──────────────────────────────────────────────────────────

_PROJECT_DOMAIN: dict[str, str] = {
    "marvin-bench":          "bench-harness",
    "marvin":                "python-agents",
    ".agents":               "python-agents",
    "hermes-agent":          "python-agents",
    "resume-tailor":         "python-agents",
    "charter":               "aws-cloud",
    "charter-cost-platform": "aws-cloud",
}

_CONTENT_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "bench-harness":  ["bench", "benchmark", "profile", "lean", "recall",
                       "token", "scoring", "grading", "task-00", "marvin profile"],
    "aws-cloud":      ["aws", "lambda", "s3", "eventbridge", "neptune", "bedrock",
                       "ecs", "aurora", "iam", "cloudtrail", "cloudwatch", "sns", "sqs"],
    "python-agents":  ["chromadb", "claude", "skill", "hook", "venv", "agent",
                       "memory", "retrieval", "embedding", "marvin", "ollama", "nomic"],
    "devtools":       ["git", "github", "keychain", "gitignore", "setup.sh",
                       "launchd", "plist", "zshrc", "alias"],
    "data-pipeline":  ["pipeline", "etl", "ingestion", "idempotent", "batch",
                       "dedup", "jsonl", "hash"],
    "web-backend":    ["fastapi", "flask", "api", "rest", "endpoint",
                       "pydantic", "openapi", "http", "router"],
    "ml-ops":         ["llm", "fine-tun", "training", "inference", "classification",
                       "embedding model", "quantization", "vllm", "tensorrt"],
}


def infer_domain(project_name: str, document: str,
                 library: str = "", tags: str = "") -> str:
    """Return best-guess domain from project name, then content keywords."""
    for key, domain in _PROJECT_DOMAIN.items():
        if key.lower() in project_name.lower():
            return domain
    text = f"{document} {library} {tags}".lower()
    scores = {d: sum(1 for kw in kws if kw in text)
              for d, kws in _CONTENT_DOMAIN_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""

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


# ── quality: verbosity · naming · logic · comment quality ────────────────────

class QualityVisitor(ast.NodeVisitor):
    """Detect verbosity, naming, and logic anti-patterns via AST."""

    GENERIC_PARAMS = frozenset({
        "data", "result", "res", "temp", "tmp", "ret", "retval",
        "foo", "bar", "baz", "stuff", "thing", "obj", "val", "info",
    })

    def __init__(self):
        self.issues: list[dict] = []
        self._file = ""

    def _issue(self, kind: str, msg: str, line: int, suggestion: str = ""):
        self.issues.append({"kind": kind, "msg": msg, "line": line,
                            "suggestion": suggestion, "file": self._file})

    # ── == True/False and == None / != None ──────────────────────────────────
    def visit_Compare(self, node):
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(comp, ast.Constant):
                if type(comp.value) is bool and isinstance(op, (ast.Eq, ast.NotEq)):
                    self._issue(
                        "verbosity",
                        f"Comparison to `{comp.value!r}` at line {node.lineno} — use truthiness directly.",
                        node.lineno,
                        "`if flag:` / `if not flag:` — never `if flag == True:`.",
                    )
                elif comp.value is None and isinstance(op, (ast.Eq, ast.NotEq)):
                    op_str = "==" if isinstance(op, ast.Eq) else "!="
                    fix = "is" if isinstance(op, ast.Eq) else "is not"
                    self._issue(
                        "style",
                        f"`{op_str} None` at line {node.lineno} — use `{fix} None` (PEP 8 E711).",
                        node.lineno,
                        f"Replace with `{fix} None`.",
                    )
        # len(x) == 0 and len(x) != 0
        if (isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name)
                and node.left.func.id == "len"
                and len(node.ops) == 1
                and isinstance(node.comparators[0], ast.Constant)
                and node.comparators[0].value == 0):
            op = node.ops[0]
            if isinstance(op, (ast.Eq, ast.NotEq)):
                alt = "not seq" if isinstance(op, ast.Eq) else "seq"
                self._issue(
                    "verbosity",
                    f"`len(...) {'==' if isinstance(op, ast.Eq) else '!='} 0` at line {node.lineno} — use truthiness.",
                    node.lineno,
                    f"Use `{alt}` — empty containers are falsy in Python.",
                )
        self.generic_visit(node)

    # ── not not x double-negation ────────────────────────────────────────────
    def visit_UnaryOp(self, node):
        if (isinstance(node.op, ast.Not)
                and isinstance(node.operand, ast.UnaryOp)
                and isinstance(node.operand.op, ast.Not)):
            self._issue(
                "verbosity",
                f"Double negation `not not ...` at line {node.lineno}.",
                node.lineno,
                "Use `bool(x)` or rely on truthiness directly.",
            )
        self.generic_visit(node)

    # ── if True: / if False: unconditional dead code ─────────────────────────
    def visit_If(self, node):
        if isinstance(node.test, ast.Constant) and node.test.value in (True, False):
            self._issue(
                "logic",
                f"`if {node.test.value}:` is an unconditional branch at line {node.lineno} — dead code.",
                node.lineno,
                "Remove the condition or delete the dead branch.",
            )
        self.generic_visit(node)

    # ── generic parameter names ───────────────────────────────────────────────
    def visit_FunctionDef(self, node):
        for arg in node.args.args + node.args.posonlyargs:
            if arg.arg in self.GENERIC_PARAMS:
                self._issue(
                    "naming",
                    f"Generic parameter name `{arg.arg}` in `{node.name}()` at line {node.lineno}.",
                    node.lineno,
                    "Name the parameter after its role, not its type or a placeholder.",
                )
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


# ── comment quality (text-based) ──────────────────────────────────────────────

_FILLER_RE = re.compile(
    r"\b(basically|simply|just|literally|obviously|clearly|easily|quickly)\b",
    re.IGNORECASE,
)
_VAGUE_RE = re.compile(
    r"#\s*(fix\s*this|temp|not\s*sure|idk|unclear|figure\s*out|whatever|handles?\s+stuff)",
    re.IGNORECASE,
)
_BARE_MARKER_RE = re.compile(r"#\s*(TODO|FIXME|HACK|BUG)\s*$", re.IGNORECASE)


def analyze_comment_quality(path: Path) -> list[dict]:
    """Scan source lines for comment quality issues: vague markers, filler words,
    bare TODOs with no description, and uninformative inline comments."""
    issues: list[dict] = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()

        # bare marker with no body
        if _BARE_MARKER_RE.match(stripped):
            marker = _BARE_MARKER_RE.match(stripped).group(1).upper()
            issues.append({
                "kind": "comment",
                "msg": f"Bare `{marker}` with no description at line {lineno}.",
                "line": lineno,
                "suggestion": "Add context: what needs doing and why.",
                "file": str(path),
            })
            continue

        # vague / unhelpful markers
        if _VAGUE_RE.match(stripped):
            body = stripped.lstrip("#").strip()
            issues.append({
                "kind": "comment",
                "msg": f"Vague comment `{body[:60]}` at line {lineno}.",
                "line": lineno,
                "suggestion": "Be specific: what is wrong and what the correct behaviour is.",
                "file": str(path),
            })
            continue

        # filler words anywhere in a comment line
        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip()
            m = _FILLER_RE.search(body)
            if m:
                issues.append({
                    "kind": "verbosity",
                    "msg": f"Filler word `{m.group(1)}` in comment at line {lineno}: `{body[:80]}`",
                    "line": lineno,
                    "suggestion": "Remove the filler — state the fact directly.",
                    "file": str(path),
                })

        # inline comment that is too short to be useful
        # use " #" (space before hash) to avoid matching # inside strings
        if " #" in line and not stripped.startswith("#"):
            inline = line[line.rfind(" #") + 2:].strip()
            # require at least one word character — filters out punctuation-only noise
            if 0 < len(inline) < 5 and re.search(r"[a-zA-Z0-9]", inline) \
                    and not inline.startswith(("noqa", "type:", "fmt:")):
                issues.append({
                    "kind": "comment",
                    "msg": f"Uninformative inline comment `# {inline}` at line {lineno}.",
                    "line": lineno,
                    "suggestion": "Explain WHY, not what — or remove it.",
                    "file": str(path),
                })

    return issues


def analyze_quality(project: Path) -> list[dict]:
    """Run verbosity, naming, logic, and comment-quality checks across all Python files."""
    all_issues: list[dict] = []
    for f in _iter_files(project):
        if f.suffix == ".py":
            try:
                tree = ast.parse(f.read_text(errors="replace"))
            except SyntaxError:
                continue
            visitor = QualityVisitor()
            visitor._file = str(f)
            visitor.visit(tree)
            all_issues.extend(visitor.issues)
            all_issues.extend(analyze_comment_quality(f))
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
    seen: set[str] = set()
    new = []
    for e in entries:
        if e["id"] not in existing and e["id"] not in seen:
            seen.add(e["id"])
            new.append(e)
    BATCH = 500
    for i in range(0, len(new), BATCH):
        chunk = new[i:i + BATCH]
        col.add(
            documents=[e["document"] for e in chunk],
            metadatas=[e["metadata"] for e in chunk],
            ids=[e["id"] for e in chunk],
        )
    return len(new)


# ── main ──────────────────────────────────────────────────────────────────────

def scan(project: Path, dry_run: bool = False) -> list[dict]:
    project = project.resolve()
    name = project.name
    now = datetime.now(timezone.utc).isoformat()

    entries: list[dict] = []

    def add(document: str, category: str, **meta):
        library = meta.pop("library", "")
        tags    = meta.pop("tags", "")
        domain  = meta.pop("domain", infer_domain(name, document, library, tags))
        entries.append({
            "id": _make_id(document),
            "document": document,
            "metadata": {
                "category":   category,
                "source":     "project-scan",
                "project":    name,
                "created_at": now,
                "language":   meta.pop("language", "all"),
                "library":    library,
                "tags":       tags,
                "confidence": meta.pop("confidence", "medium"),
                "domain":     domain,
                "outcome":    meta.pop("outcome", ""),
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

    # quality: verbosity, naming, logic, comment quality
    quality_issues = analyze_quality(project)
    quality_kind_to_tags = {
        "verbosity": "verbosity,style,conciseness",
        "style":     "style,pep8",
        "naming":    "naming,readability",
        "logic":     "logic,dead-code",
        "comment":   "comment,documentation",
    }
    for issue in quality_issues:
        rel_file = Path(issue["file"]).relative_to(project) if Path(issue["file"]).is_absolute() else issue["file"]
        doc = (
            f"[{issue['kind'].upper()}] {issue['msg']} "
            f"(file: {rel_file}) "
            f"Suggestion: {issue['suggestion']}"
        )
        add(
            doc,
            "anti-pattern",
            tags=quality_kind_to_tags.get(issue["kind"], issue["kind"]),
            language="python",
            confidence="low",
        )

    return entries


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan a project into qa-knowledge")
    ap.add_argument("project", help="path to project directory")
    ap.add_argument("--dry-run", action="store_true", help="print entries without storing")
    ap.add_argument("--max-files", type=int, default=200,
                    help="max source files to scan (default 200; use 0 for unlimited)")
    args = ap.parse_args()

    project = Path(args.project)
    if not project.exists():
        sys.exit(f"project not found: {project}")

    if args.max_files > 0:
        # Warn if project is large
        file_count = sum(1 for _ in _iter_files(project))
        if file_count > args.max_files:
            print(f"Note: project has {file_count} files; scanning first {args.max_files}. Use --max-files 0 to scan all.", file=sys.stderr)

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
