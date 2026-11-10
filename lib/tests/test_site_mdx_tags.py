"""The site's MDX treats `<word>` as a JSX tag: an unclosed one fails the whole site build (PR #1244's "(closed <date>)",
2026-11-10). Placeholders like <date> belong in code spans. This catches it before CI does, without the site's node deps.
"""
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "site" / "src" / "content" / "docs"
_CODE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]*`", re.S)
_OPEN = re.compile(r"<([a-z][\w-]*)(?:\s[^<>]*)?>")


def unclosed(text: str) -> list[str]:
    plain = _CODE.sub(" ", text)
    return [m.group(0) for m in _OPEN.finditer(plain)
            if not m.group(0).endswith("/>") and f"</{m.group(1)}>" not in plain[m.end():]]


def test_no_unclosed_lowercase_tags_outside_code():
    bad = {str(f.relative_to(DOCS)): unclosed(f.read_text()) for f in DOCS.rglob("*.mdx")}
    assert {k: v for k, v in bad.items() if v} == {}


def test_the_rule_itself():
    assert unclosed("(closed <date>)") == ["<date>"]
    assert unclosed("(closed `<date>`)") == [] and unclosed("<details>x</details>") == [] and unclosed("<br/>") == []
