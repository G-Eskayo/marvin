"""The health sweep tells the owner when a check turns red (#1123): the gap behind 23 h of broken sync and 18 h of a
down site that nobody was told about. disk:headroom used to have its own notifier (retired); it is a check like any."""
from __future__ import annotations
import sys
from datetime import date, timedelta
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import health_checks as hc  # noqa: E402

D0 = date(2026, 11, 4)


def _c(cid, sev, label=None, detail="d"):
    return {"id": cid, "severity": sev, "label": label or cid, "detail": detail}


def test_a_check_turning_red_alerts_with_its_label_and_detail(tmp_path):
    fired = []
    out = hc.alert_red_checks([_c("sync:stuck", "red", "Code sync", "stuck 23 h"), _c("x", "green")],
                              tmp_path / "m.json", fire=lambda t, m: fired.append((t, m)), today=D0)
    assert fired == [("MARVIN: Code sync is red", "stuck 23 h")] and out == "1 new"


def test_every_15_minute_sweep_of_the_same_red_alerts_once_a_day(tmp_path):
    fired = []
    for day in range(2):
        for _ in range(96):
            hc.alert_red_checks([_c("disk:headroom@mac-mini-1", "red")], tmp_path / "m.json",
                                fire=lambda t, m: fired.append(t), today=D0 + timedelta(days=day))
    assert len(fired) == 2


def test_fifteen_reds_on_the_first_sweep_are_one_banner_not_fifteen(tmp_path):
    fired = []
    hc.alert_red_checks([_c(f"c{i}", "red") for i in range(15)], tmp_path / "m.json",
                        fire=lambda t, m: fired.append(t), today=D0)
    assert fired == ["MARVIN: 15 things turned red"]


def test_checks_without_an_id_or_that_are_not_dicts_are_ignored(tmp_path):
    assert hc.alert_red_checks([None, {"severity": "red"}, {"id": 3, "severity": "red"}], tmp_path / "m.json",
                               fire=lambda t, m: None, today=D0) == "nothing changed"


def test_the_retired_disk_notifier_is_gone():
    assert not (LIB / "disk_forecast_notify.py").exists()
    assert "disk_forecast_notify" not in (LIB / "health_checks.py").read_text()
