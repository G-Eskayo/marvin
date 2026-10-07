"""Tests for migrate_ticket_stages.py (#216). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_migrate_ticket_stages.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import migrate_ticket_stages as mig  # noqa: E402


def _write(path: Path, events: list[dict]) -> None:
    path.write_text(json.dumps(events))


def test_plan_maps_both_old_forms_to_owner_and_repo_keys(tmp_path):
    _write(tmp_path / "158.json", [])
    _write(tmp_path / "clarity-captions-7.json", [])
    _write(tmp_path / "g-eskayo__marvin-9.json", [])
    (tmp_path / "notes.txt").write_text("x")
    moves = {src.name: dst.name for src, dst in mig.plan(tmp_path)}
    assert moves == {"158.json": "g-eskayo__marvin-158.json",
                     "clarity-captions-7.json": "g-eskayo__clarity-captions-7.json"}


def test_dry_run_is_the_default_and_moves_nothing(tmp_path, capsys):
    _write(tmp_path / "158.json", [])
    assert mig.main(["--dir", str(tmp_path)]) == 0
    assert (tmp_path / "158.json").exists()
    assert not (tmp_path / "g-eskayo__marvin-158.json").exists()
    assert "158.json -> g-eskayo__marvin-158.json" in capsys.readouterr().out


def test_apply_moves_the_files(tmp_path):
    _write(tmp_path / "158.json", [{"timestamp": "2026-10-01T00:00:00+00:00", "detail": "a"}])
    assert mig.main(["--dir", str(tmp_path), "--apply"]) == 0
    assert not (tmp_path / "158.json").exists()
    assert json.loads((tmp_path / "g-eskayo__marvin-158.json").read_text())[0]["detail"] == "a"


def test_apply_merges_into_an_existing_new_file_in_time_order(tmp_path):
    _write(tmp_path / "158.json", [{"timestamp": "2026-10-01T00:00:00+00:00", "detail": "old"}])
    _write(tmp_path / "g-eskayo__marvin-158.json", [{"timestamp": "2026-10-02T00:00:00+00:00", "detail": "new"}])
    mig.main(["--dir", str(tmp_path), "--apply"])
    events = json.loads((tmp_path / "g-eskayo__marvin-158.json").read_text())
    assert [e["detail"] for e in events] == ["old", "new"]
    assert not (tmp_path / "158.json").exists()
