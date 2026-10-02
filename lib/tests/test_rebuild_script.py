"""dashboard/scripts/rebuild_and_install.sh must install dependencies before building.

Found 2026-10-02: the laptop's dashboard app was a month stale because it is only
ever rebuilt where a merge happened, and a manual rebuild there then FAILED with
"Rollup failed to resolve import react-markdown" -- a dependency added on 2026-10-01
that the laptop's node_modules never received, because the script went straight to
`npm run build:mac`. A rebuild must not assume node_modules is current.
"""
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "dashboard" / "scripts" / "rebuild_and_install.sh"


def test_installs_dependencies_before_building():
    text = SCRIPT.read_text()
    assert "npm install" in text or "npm ci" in text
    install_at = min(i for i in (text.find("npm install"), text.find("npm ci")) if i != -1)
    assert install_at < text.index("npm run build:mac")


def test_installing_is_quiet_about_audit_and_funding_noise():
    assert "--no-audit" in SCRIPT.read_text()
