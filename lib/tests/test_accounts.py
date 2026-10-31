"""lib/accounts.py (marvin#974): every credential MARVIN depends on, checked live, judged against its expiry, alerted
once per change. These try to break it: revoked tokens, damaged files, a provider that's down, clock skew, a past
expiry, alert spam, a secret leaking, and the box being asked for a credential."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import accounts as ac  # noqa: E402

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
CANARY = "ghp_CANARYsecretVALUE0123456789abcdef"


def home_with(tmp_path, **files):
    c = tmp_path / ".claude"
    c.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        p = c / name
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text)
    return tmp_path


class Http:
    """A fake provider. `answers` maps a URL prefix to a status, a (status, headers) pair, or an exception."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, url, headers, timeout=10):
        self.calls.append((url, dict(headers)))
        for prefix, a in self.answers.items():
            if url.startswith(prefix):
                if isinstance(a, Exception):
                    raise a
                return a if isinstance(a, tuple) else (a, {})
        raise AssertionError(f"unexpected request {url}")


def ctx(tmp_path, http=None, **kw):
    def run(cmd, timeout=15, env=None):
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"BackendState": "Running", "Self": {}}), "")
    return ac.Ctx(home=tmp_path, now=NOW, http=http or Http({}), run=kw.get("run", run), which=kw.get("which", lambda n: None),
                  pull_only=kw.get("pull_only", False), primary=kw.get("primary", False), platform=kw.get("platform", "linux"))


def row(acc_id, c):
    return ac.check_one(ac.BY_ID[acc_id], c, "mac-mini-1")


GH = "https://api.github.com/"
AN = "https://api.anthropic.com/"


# ── revoked, damaged, missing ───────────────────────────────────────────────────────────────────────────────────────

def test_a_revoked_github_token_is_failed_and_says_so(tmp_path):
    c = ctx(home_with(tmp_path, **{".gh-token": CANARY}), Http({GH: 401}))
    r = row("github-token", c)
    assert r["state"] == "failed" and "rejected" in r["detail"]


@pytest.mark.parametrize("content,why", [
    ("", "empty"), ("   \n", "empty"), ("ghp_one ghp_two", "more than one word"), ("ghp_a\nghp_b", "more than one word"),
    (b"\xff\xfe\x00", "not plain text"), ("ghp_\x07bell", "hidden characters"),
])
def test_a_damaged_token_file_is_failed_without_calling_github(tmp_path, content, why):
    http = Http({})
    r = row("github-token", ctx(home_with(tmp_path, **{".gh-token": content}), http))
    assert r["state"] == "failed" and "damaged" in r["detail"] and why.split()[0] in r["detail"]
    assert http.calls == []


def test_a_missing_required_token_is_failed_but_a_missing_optional_one_is_not_set_up(tmp_path):
    c = ctx(home_with(tmp_path))
    assert row("github-token", c)["state"] == "failed"
    assert row("claude-setup-token", c)["state"] == "failed"
    assert row("anthropic-api-key", c)["state"] == "not_set_up"


def test_damaged_linux_credentials_json_is_failed_not_a_crash(tmp_path):
    for text in ("{trunc", "[]", '{"claudeAiOauth": "x"}'):
        r = row("claude-login", ctx(home_with(tmp_path, **{".credentials.json": text})))
        assert r["state"] == "failed"


# ── provider down is not expired ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("answer", [ac.ProviderDown("URLError"), ac.ProviderDown("HTTP 502"), ac.ProviderDown("TimeoutError")])
def test_a_provider_that_is_down_is_unreachable_never_failed(tmp_path, answer):
    c = ctx(home_with(tmp_path, **{".gh-token": CANARY, ".oauth-token": "sk-ant-oat01-x", ".anthropic-api-key": "sk-ant-api-x"}),
            Http({GH: answer, AN: answer}))
    for acc in ("github-token", "claude-setup-token", "anthropic-api-key"):
        assert row(acc, c)["state"] == "unreachable", acc


def test_github_rate_limit_403_is_no_verdict_but_a_plain_403_is_rejected(tmp_path):
    h = home_with(tmp_path, **{".gh-token": CANARY})
    assert row("github-token", ctx(h, Http({GH: (403, {"x-ratelimit-remaining": "0"})})))["state"] == "unreachable"
    assert row("github-token", ctx(h, Http({GH: (403, {})})))["state"] == "failed"


def test_the_real_http_helper_maps_401_to_a_verdict_and_502_to_provider_down(monkeypatch):
    import urllib.error
    import urllib.request

    def fake(code):
        def urlopen(req, timeout=10):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return urlopen
    monkeypatch.setattr(urllib.request, "urlopen", fake(401))
    assert ac._http_get("https://api.github.com/user", {})[0] == 401
    monkeypatch.setattr(urllib.request, "urlopen", fake(502))
    with pytest.raises(ac.ProviderDown):
        ac._http_get("https://api.github.com/user", {})

    def offline(req, timeout=10):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(ac.ProviderDown):
        ac._http_get("https://api.github.com/user", {})


# ── expiry: known, estimated, past, skew ────────────────────────────────────────────────────────────────────────────

def test_a_known_expiry_inside_the_window_is_amber_with_days_left(tmp_path):
    exp = "2026-11-08 12:00:00 UTC"
    r = row("github-token", ctx(home_with(tmp_path, **{".gh-token": CANARY}), Http({GH: (200, {"github-authentication-token-expiration": exp, "x-oauth-scopes": "repo, workflow"})})))
    assert r["state"] == "expiring" and "2026-11-08" in r["detail"] and "9 days left" in r["detail"]
    assert r["expires_at"].startswith("2026-11-08")


def test_an_expiry_date_in_the_past_is_failed_even_if_the_live_check_passed(tmp_path):
    r = row("github-token", ctx(home_with(tmp_path, **{".gh-token": CANARY}), Http({GH: (200, {"github-authentication-token-expiration": "2026-10-01 00:00:00 UTC"})})))
    assert r["state"] == "failed" and "expired" in r["detail"]


def test_setup_token_expiry_is_estimated_from_the_file_age_and_warns_30_days_ahead(tmp_path):
    h = home_with(tmp_path, **{".oauth-token": "sk-ant-oat01-x"})
    made = (NOW - timedelta(days=340)).timestamp()
    os.utime(h / ".claude" / ".oauth-token", (made, made))
    r = row("claude-setup-token", ctx(h, Http({AN: 200})))
    assert r["state"] == "expiring" and r["estimated"] is True and "about" in r["detail"]


def test_box_style_credentials_json_refresh_expiry_is_read_as_metadata(tmp_path):
    exp_ms = int((NOW + timedelta(days=13)).timestamp() * 1000)
    creds = json.dumps({"claudeAiOauth": {"accessToken": CANARY, "refreshToken": CANARY, "refreshTokenExpiresAt": exp_ms, "subscriptionType": "max"}})
    r = row("claude-login", ctx(home_with(tmp_path, **{".credentials.json": creds})))
    assert r["state"] == "expiring" and "13 days left" in r["detail"]
    assert CANARY not in json.dumps(r)


def test_garbage_expiry_values_are_ignored_not_trusted(tmp_path):
    for bad in ("soon", "", None, "2026-13-45"):
        assert ac.parse_time(bad) is None


def test_remote_rows_are_rejudged_on_the_minis_clock_and_skew_is_noted():
    exp = (NOW + timedelta(days=5)).isoformat()
    remote = [{"id": "tailscale", "state": "works", "detail": "on the tailnet", "expires_at": exp, "estimated": False,
               "checked_at": (NOW - timedelta(days=30)).isoformat()},   # its clock says a month ago: it thinks 35 days left
              {"id": "not-an-account", "state": "works"}]
    out = ac.rejudge_remote(remote, NOW)
    assert len(out) == 1
    assert out[0]["state"] == "expiring" and "5 days left" in out[0]["detail"]
    assert "clock is" in out[0]["detail"] and "behind" in out[0]["detail"]


# ── the box is never asked for a credential ─────────────────────────────────────────────────────────────────────────

def test_on_a_pull_only_node_secrets_are_not_needed_and_nothing_is_asked(tmp_path):
    http = Http({})
    c = ctx(home_with(tmp_path), http, pull_only=True)
    rows = {a.id: ac.check_one(a, c, "mac-mini-2012") for a in ac.ACCOUNTS}
    for acc in ("github-token", "gh-login", "claude-setup-token", "anthropic-api-key", "marvin-bot", "ngrok"):
        assert rows[acc]["state"] == "not_needed", acc
    assert http.calls == []
    assert ac.alerts_due(list(rows.values()), {})[0] == [r for r in rows.values() if r["state"] in ac.ALERTABLE]


# ── secrets never leak ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_secret_never_reaches_the_output_argv_or_the_alert(tmp_path, capsys):
    h = home_with(tmp_path, **{".gh-token": CANARY, ".oauth-token": CANARY, ".anthropic-api-key": CANARY, ".marvin-bot-token": CANARY})
    http = Http({GH: 401, AN: 401})
    runs = []
    c = ac.Ctx(home=h, now=NOW, http=http, platform="darwin", primary=True,
               run=lambda cmd, timeout=15, env=None: runs.append(cmd) or subprocess.CompletedProcess(cmd, 1, "", "invalid"),
               which=lambda n: f"/usr/bin/{n}")
    rows = [ac.check_one(a, c, "mac-mini-1") for a in ac.ACCOUNTS]
    blob = json.dumps(rows) + "".join(" ".join(ac.alert_message(r)) for r in rows) + json.dumps(runs)
    assert CANARY not in blob
    assert all(CANARY not in " ".join(map(str, cmd)) for cmd in runs)
    # it went only as a header to the provider
    assert any(CANARY in " ".join(h.values()) for _, h in http.calls)
    assert all(u.startswith(("https://api.github.com/", "https://api.anthropic.com/")) for u, _ in http.calls)


def test_gh_login_check_runs_gh_without_the_shared_token_in_its_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", CANARY)
    seen = {}

    def run(cmd, timeout=15, env=None):
        seen["env"] = env
        return subprocess.CompletedProcess(cmd, 1, "", "The token in default is invalid")
    c = ac.Ctx(home=tmp_path, now=NOW, run=run, which=lambda n: "/usr/bin/gh")
    r = row("gh-login", c)
    assert "GH_TOKEN" not in seen["env"] and r["state"] == "failed"


# ── alerts: once per change ─────────────────────────────────────────────────────────────────────────────────────────

def _r(state, acc="github-token", machine="mac-mini-1", alert=True):
    return {"id": acc, "machine": machine, "label": ac.BY_ID[acc].label, "state": state, "detail": "d",
            "blocks": "b", "renew": ac.BY_ID[acc].renew, "alert": alert}


def test_the_same_failure_on_100_sweeps_alerts_once(tmp_path):
    fired = []
    path = tmp_path / "alerted.json"
    for _ in range(100):
        ac.alert_changes([_r("failed")], path, fire=lambda t, m: fired.append(t))
    assert len(fired) == 1


def test_amber_then_red_then_fixed_is_three_alerts_and_provider_blips_add_none(tmp_path):
    fired = []
    path = tmp_path / "alerted.json"
    seq = ["works", "expiring", "unreachable", "expiring", "failed", "unreachable", "failed", "not_set_up", "works", "works", "unreachable", "works"]
    for s in seq:
        ac.alert_changes([_r(s)], path, fire=lambda t, m: fired.append(t))
    assert fired == ["MARVIN: GitHub (shared token) runs out soon", "MARVIN: GitHub (shared token) stopped working",
                     "MARVIN: GitHub (shared token) fixed"]


def test_a_first_sweep_of_healthy_accounts_alerts_nothing_and_quiet_accounts_never_alert(tmp_path):
    fired = []
    ac.alert_changes([_r("works"), _r("failed", acc="gh-login", alert=False)], tmp_path / "a.json", fire=lambda t, m: fired.append(t))
    assert fired == []


def test_a_corrupt_alert_state_file_is_started_over_not_a_crash(tmp_path):
    path = tmp_path / "a.json"
    path.write_text("{oops")
    fired = []
    ac.alert_changes([_r("failed")], path, fire=lambda t, m: fired.append(t))
    assert len(fired) == 1 and json.loads(path.read_text()) == {"github-token@mac-mini-1": "failed"}


def test_an_alert_that_throws_never_stops_the_others_or_the_sweep(tmp_path):
    calls = []

    def fire(t, m):
        calls.append(t)
        raise RuntimeError("push failed")
    due = ac.alert_changes([_r("failed"), _r("failed", machine="macbook-pro-1")], tmp_path / "a.json", fire=fire)
    assert len(due) == 2 and len(calls) == 2


def test_the_alert_says_what_it_blocks_and_how_to_fix_it():
    title, msg = ac.alert_message(_r("failed", acc="claude-setup-token"))
    assert "stopped working" in title and "Blocks: b" in msg and "marvin-renew claude-setup-token" in msg


# ── machines that can't be reached ──────────────────────────────────────────────────────────────────────────────────

def test_an_unreachable_machine_is_couldnt_check_for_every_account_and_never_alerts(tmp_path):
    rows = ac.check_remote("lap", "macbook-pro-1", NOW, run=lambda cmd, timeout=90: subprocess.CompletedProcess(cmd, 255, "", "timeout"))
    assert {r["state"] for r in rows} == {"unreachable"} and len(rows) == len(ac.ACCOUNTS)
    assert ac.alerts_due(rows, {"github-token@macbook-pro-1": "failed"})[0] == []


def test_a_garbled_remote_answer_is_couldnt_check(tmp_path):
    rows = ac.check_remote("lap", "macbook-pro-1", NOW, run=lambda cmd, timeout=90: subprocess.CompletedProcess(cmd, 0, "not json", ""))
    assert {r["state"] for r in rows} == {"unreachable"}


def test_the_remote_command_is_fixed_text_with_no_secret(tmp_path):
    sent = []
    ac.check_remote("lap", "macbook-pro-1", NOW, run=lambda cmd, timeout=90: sent.append(cmd) or subprocess.CompletedProcess(cmd, 1, "", ""))
    assert sent[0][-1] == ac.REMOTE_COMMAND and "BatchMode=yes" in sent[0]


def test_a_check_that_crashes_is_one_unreachable_row(tmp_path, monkeypatch):
    bad = ac.Account("x", "X", lambda c: 1 / 0, "nothing", {"how": "command", "command": "x"})
    r = ac.check_one(bad, ctx(tmp_path), "m")
    assert r["state"] == "unreachable" and "ZeroDivisionError" in r["detail"]


def test_status_file_is_written_private_and_atomic(tmp_path):
    p = tmp_path / "logs" / "accounts-status.json"
    ac.write_status({"accounts": []}, p)
    assert oct(p.stat().st_mode & 0o777) == "0o600" and sorted(x.name for x in p.parent.iterdir()) == ["accounts-status.json"]
