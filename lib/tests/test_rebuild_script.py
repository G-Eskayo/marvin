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


# #442 rename to MARVIN and #443 failure-only backoff
def test_installs_MARVIN_app_and_removes_the_old_MARVIN_Metrics_app():
    text = SCRIPT.read_text()
    assert 'APP_NAME="MARVIN.app"' in text
    assert "MARVIN Metrics.app" in text            # the legacy copy is handled...
    assert 'rm -rf "$LEGACY_DEST"' in text         # ...by removing it after the new one is in place
    assert text.index('rm -rf "$LEGACY_DEST"') > text.index('installing to $DEST')


def test_quits_whichever_name_is_running_before_replacing_it():
    text = SCRIPT.read_text()
    assert 'quit app "MARVIN"' in text and 'quit app "MARVIN Metrics"' in text


def test_a_failed_build_is_marked_and_a_successful_one_clears_the_mark():
    text = SCRIPT.read_text()
    assert "dashboard-rebuild-failed" in text
    on_error = text[text.index("on_error()"):text.index("trap ")]
    assert "dashboard-rebuild-failed" in on_error  # written on failure
    assert text.rindex("dashboard-rebuild-failed") > text.index("installing to $DEST")  # cleared after a good install
