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


def test_electron_builder_never_tries_to_publish_auto_update_files():
    # 2026-10-15: every signed build crashed after making the app ("Cannot read properties of null (reading 'channel')",
    # plus the "Cannot cleanup" seen since at least 10-14) because electron-builder tried to write auto-update files
    # with no publish target. The install then fell back to an ad-hoc signature, which can cost macOS permissions.
    # MARVIN updates itself by rebuilding (dashboard_rebuild.py), never through electron-builder's updater.
    import json
    pkg = json.loads((SCRIPT.parents[1] / "package.json").read_text())
    assert "publish" in pkg["build"] and pkg["build"]["publish"] is None


# Tests 8-12: marvin#1106 - wait for in-flight merges to finish before restarting the webhook
def test_polls_merge_queue_before_restarting_webhook():
    text = SCRIPT.read_text()
    assert "merge-queue" in text
    assert "http://127.0.0.1" in text


def test_polling_checks_for_running_merges_not_null():
    text = SCRIPT.read_text()
    # The polling loop must check each repo's "running" value (URL or null), not just grep for the key.
    assert '"running"' in text and ("for line in" in text or "grep" in text)
    # Explicitly should NOT have the old broken regex that treats false/0/null as still merging.
    assert "[^n]" not in text, "polling must not use regex [^n] which treats false as merging"
    # Must check for null specifically, since running values are URLs (truthy) or null (falsy)
    assert '!= "null"' in text, "polling must check if running value is not null"


def test_polling_is_bounded_to_approximately_10_minutes():
    text = SCRIPT.read_text()
    assert "MAX_WAIT" in text
    assert "10 * 60" in text or "600" in text


def test_polling_interval_is_approximately_5_seconds():
    text = SCRIPT.read_text()
    assert "POLL_INTERVAL" in text
    assert "POLL_INTERVAL=5" in text


def test_polling_logs_when_bound_is_hit():
    text = SCRIPT.read_text()
    assert "waiting for merges took longer" in text or "proceeding anyway" in text
    # The message must be reachable: it prints when elapsed >= MAX_WAIT, not just when elapsed > MAX_WAIT - POLL_INTERVAL.
    # Verify the condition is not impossible by checking the logic around the message.
    import re
    # Find the condition that triggers the message
    condition = re.search(r'\[\s*"\$STILL_MERGING"\s*=\s*"true"\s*\]\s*&&\s*\[\s*\$ELAPSED\s*-ge\s*\$MAX_WAIT\s*\]', text)
    assert condition, "polling must log when ELAPSED >= MAX_WAIT, making the message reachable"
