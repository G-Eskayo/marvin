"""MARVIN runs as gileskayo on the Macs and as marvin on mac-mini-2012 (ADR 0069), so no code may hard-code
/Users/gileskayo. Use Path.home() locally, or $HOME in a command string that runs on another machine."""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Tests that check home paths get *redacted* must contain one to redact.
ALLOWED = {
    "brain-map/export_snapshot.py",
    "brain-map/tests/test_deploy_snapshot.py",
    "brain-map/scripts/test_export_snapshot.py",
    "lib/tests/test_no_hardcoded_home.py",
}


def test_no_code_hard_codes_the_mac_home_directory():
    out = subprocess.run(
        ["git", "grep", "-l", "/Users/gileskayo", "--", "*.py", "*.sh", "*.json", "*.js", "*.jsx", "*.ts"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.split()
    offenders = sorted(set(out) - ALLOWED)
    assert offenders == [], f"hard-coded /Users/gileskayo in: {offenders}"


def test_bench_task_cwd_accepts_a_tilde():
    src = (REPO / "bench" / "bench.py").read_text()
    assert 'task.get("cwd", str(Path.home()))).expanduser()' in src
