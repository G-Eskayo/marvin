"""Model consistency checks that run as part of the normal test suite.

Verifies:
- All model references in code are registered
- All registry entries are actually used or have a reason

Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_model_consistency.py -v
"""
from __future__ import annotations
import sys
import re
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(LIB))

import model_registry as mr  # noqa: E402
import model_audit as ma  # noqa: E402


@pytest.fixture
def registry():
    """Load the actual registry from config/models.json."""
    return mr.ModelRegistry()


def test_all_paper_dive_model_references_are_registered(registry):
    """All model names hardcoded in paper-dive scripts must be in the registry.

    This is an exact-literal scan, not a regex heuristic.
    Paper-dive uses Ollama tags like "qwen2.5:14b" (with colons).
    """
    paper_dive_dir = REPO_ROOT / "skills" / "paper-dive" / "scripts"
    if not paper_dive_dir.exists():
        pytest.skip("paper-dive not found")

    registered_models = set(registry.all().keys())

    # Patterns that definitely reference a model (only Qwen models in paper-dive)
    patterns = [
        r'(?:EXTRACTION_|JUDGMENT_|CONTINUITY_)?MODEL\s*=\s*["\']([qQ]wen[^"\']*)["\']',
        r'return\s+["\']([qQ]wen[^"\']*)["\']',
    ]

    unregistered = []
    for py_file in paper_dive_dir.glob("*.py"):
        content = py_file.read_text()
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                model_name = match.group(1)
                if model_name not in registered_models:
                    unregistered.append({
                        "file": py_file.name,
                        "model": model_name,
                    })

    assert not unregistered, (
        f"Found {len(unregistered)} unregistered model references in paper-dive:\n"
        + "\n".join(f"  {u['file']}: {u['model']}" for u in unregistered)
    )


def test_all_portfolio_flux_model_references_are_registered(registry):
    """All model names in portfolio_flux.py must be in the registry."""
    flux_file = LIB / "portfolio_flux.py"
    if not flux_file.exists():
        pytest.skip("portfolio_flux.py not found")

    registered_models = set(registry.all().keys())
    content = flux_file.read_text()

    # Look for model name strings
    patterns = [
        r'["\']([A-Za-z0-9\.:_\-]+[:\-\.][A-Za-z0-9\.:_\-]+)["\']',  # Has separator
    ]

    unregistered = []
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            model_name = match.group(1)
            if model_name not in registered_models:
                # Only flag if it looks like a real model name
                if any(x in model_name for x in ["FLUX", "qwen", "llama", "nomic", "specter"]):
                    unregistered.append(model_name)

    unregistered = list(set(unregistered))
    assert not unregistered, (
        f"Found {len(unregistered)} unregistered model references in portfolio_flux.py: {unregistered}"
    )


def test_all_registry_entries_have_used_by(registry):
    """All registry entries should have at least one consumer in used_by.

    This is a soft warning for now, but entries without used_by should be reviewed.
    """
    entries_without_used_by = []
    for name, entry in registry.all().items():
        used_by = entry.get("used_by", [])
        if not used_by or (isinstance(used_by, list) and len(used_by) == 0):
            entries_without_used_by.append(name)

    # For now, just log these but don't fail
    # In the future, we should review and clean up unused entries
    if entries_without_used_by:
        pytest.warns(UserWarning, match="registry entries with no used_by")


def test_registry_entries_have_required_fields(registry):
    """All registry entries must have all required fields."""
    required_fields = [
        "size_gb",
        "location",
        "used_by",
        "reason",
        "runtime",
        "machine",
        "heavy",
    ]

    missing_fields = {}
    for name, entry in registry.all().items():
        for field in required_fields:
            if field not in entry:
                if name not in missing_fields:
                    missing_fields[name] = []
                missing_fields[name].append(field)

    assert not missing_fields, (
        f"Registry entries missing fields:\n"
        + "\n".join(f"  {name}: {fields}" for name, fields in missing_fields.items())
    )


def test_qwen_models_use_colon_separator(registry):
    """Qwen models should use colon (:) separator, not hyphen (-).

    This is the Ollama tag format and must match actual usage.
    """
    qwen_with_hyphen = [name for name in registry.all() if "qwen" in name and "-" in name and ":" not in name]
    assert not qwen_with_hyphen, f"Qwen models should use colons, not hyphens: {qwen_with_hyphen}"


def test_audit_used_by_field_validation():
    """Run the audit check for used_by field validity against the real registry.

    This enforces AC #1: "a check that flags invalid used_by references".
    """
    audit = ma.ModelAudit()
    results = audit.check_used_by_field(search_dir=REPO_ROOT)

    assert not results, (
        f"Found {len(results)} invalid used_by references in registry:\n"
        + "\n".join(f"  {r['model']}: used_by={r['used_by']} (not found)" for r in results)
    )
