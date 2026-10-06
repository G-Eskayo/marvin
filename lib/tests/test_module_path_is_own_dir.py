"""Regression (2026-10-06): the merge gate runs the suite in a clone, but these modules put ~/.agents/lib first on sys.path,
so later imports (ticket_evidence, ...) resolved to the MAIN checkout's older copy and a PR's own tests failed against
main's code (PR 140: test_merged_pr_that_refs_the_ticket_means_looks_done failed only in the full suite, never alone)."""
import re
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
MODULES = ["cron_health.py", "code_sync.py", "session_start_report.py", "ticket_pipeline.py", "task_dispatch.py"]


def test_no_module_hardcodes_the_home_checkout_on_sys_path():
    bad = [m for m in MODULES
           if re.search(r'sys\.path\.insert\(0,.*(Path\.home\(\)|HOME)\s*/\s*"\.agents"\s*/\s*"lib"', (LIB / m).read_text())]
    assert not bad, f"{bad} put ~/.agents/lib first on sys.path; use the module's own directory"
