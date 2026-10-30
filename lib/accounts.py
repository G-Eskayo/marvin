#!/usr/bin/env python3
"""Every account and credential MARVIN depends on, per machine: does it work, when does it run out, what stops if it
fails, and how to renew it (marvin#974, backend of the Vitals Accounts card #640).

Gil, 2026-10-30: "those accounts that get logged out and need to be logged back in, that should be something I can do
through the Vitals dashboard ... alert me when I need to do it so that it doesn't prevent any holdups."

  check     this machine's accounts, as JSON rows (run locally, and by the Mini over ssh on the other machines)
  sweep     the Mini's whole-network view: local + every other registered machine, judged on the Mini's clock, written
            to ~/.claude/logs/accounts-status.json, then one alert per state change. Called by the health-check sweep
            (its existing 15-minute schedule), never on a timer of its own.

Secrets: a credential is read only to be sent as an HTTP header from this process (urllib), never put in argv, a log,
an alert or the output. Rows carry presence, age, the live verdict and the expiry date a provider exposes.

States: works | expiring (amber: WARN_DAYS before a known expiry, WARN_DAYS_ESTIMATED before an estimated one) |
failed (red: rejected, expired, damaged, or needed and missing) | unreachable (couldn't check: the provider or the
machine didn't answer, which is NOT the same as expired) | not_set_up (optional and absent) | not_needed (e.g. the
GitHub token on mac-mini-2012, which holds no secrets by design, ADR 0069).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

WARN_DAYS = 14
WARN_DAYS_ESTIMATED = 30          # a setup-token's expiry is estimated from the file's age: warn earlier
SETUP_TOKEN_LIFE_DAYS = 365       # `claude setup-token` tokens last about a year
CLOCK_SKEW_NOTE = timedelta(minutes=5)
HTTP_TIMEOUT = 10
STATES = ("works", "expiring", "failed", "unreachable", "not_set_up", "not_needed")
ALERTABLE = ("expiring", "failed")

HOME = Path.home()
STATUS_PATH = HOME / ".claude" / "logs" / "accounts-status.json"
ALERT_STATE_PATH = HOME / ".claude" / "logs" / "accounts-alerted.json"
RENEW = "~/.agents/bin/marvin-renew"


class ProviderDown(Exception):
    """The provider didn't give a verdict (offline, timeout, 5xx, rate limit): not the same as a rejected credential."""


# ── context: everything a check touches, injectable for tests ───────────────────────────────────────────────────────

def _http_get(url: str, headers: dict, timeout: float = HTTP_TIMEOUT) -> tuple[int, dict]:
    """(status, lower-cased headers). Raises ProviderDown when there is no verdict. Never logs the headers."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, {k.lower(): v for k, v in res.headers.items()}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}
        raise ProviderDown(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderDown(type(e).__name__) from None


def _run(cmd: list[str], timeout: float = 15, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


@dataclass
class Ctx:
    home: Path = HOME
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pull_only: bool = False
    primary: bool = False
    platform: str = sys.platform
    http: Callable = _http_get
    run: Callable = _run
    which: Callable = shutil.which


def _ctx_here() -> Ctx:
    import machine_profile
    try:
        pull_only = machine_profile.pull_only()
    except Exception:  # noqa: BLE001
        pull_only = sys.platform != "darwin"
    try:
        me = machine_profile.registry_id()
        primary = (machine_profile._load_registry().get(me) or {}).get("kind") == "desktop" and not pull_only
    except Exception:  # noqa: BLE001
        primary = False
    return Ctx(pull_only=pull_only, primary=primary)


# ── small pure helpers ──────────────────────────────────────────────────────────────────────────────────────────────

def read_token(path: Path) -> tuple[str | None, str | None]:
    """(token, None) or (None, why). A token file holds one printable word; anything else is damaged."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, "missing"
    except OSError as e:
        return None, f"unreadable ({type(e).__name__})"
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None, "damaged (not plain text)"
    tok = text.strip()
    if not tok:
        return None, "damaged (empty)"
    if any(c.isspace() for c in tok) or not tok.isprintable():
        return None, "damaged (more than one word, or hidden characters)"
    return tok, None


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def parse_time(v) -> datetime | None:
    """ISO text, GitHub's '2027-01-14 20:55:38 UTC', or epoch seconds/ms; None for anything else."""
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            secs = v / 1000 if v > 1e11 else v
            return datetime.fromtimestamp(secs, timezone.utc)
        s = str(v).strip()
        if s.endswith(" UTC"):
            s = s[:-4].replace(" ", "T") + "+00:00"
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def judge(state: str, detail: str, expires_at: datetime | None, estimated: bool, now: datetime) -> tuple[str, str]:
    """Apply a known (or estimated) expiry to a live verdict. A past expiry is failed whatever the live check said;
    a near one turns a working account amber. Only a working account is downgraded to amber."""
    if expires_at is None:
        return state, detail
    left = expires_at - now
    when = expires_at.strftime("%Y-%m-%d")
    about = "about " if estimated else ""
    if left <= timedelta(0):
        return "failed", f"expired {about}{when}"
    warn = timedelta(days=WARN_DAYS_ESTIMATED if estimated else WARN_DAYS)
    if state == "works" and left <= warn:
        days = max(0, left.days)
        return "expiring", f"{detail}; runs out {about}{when} ({days} day{'' if days == 1 else 's'} left)"
    return state, detail


def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


# ── the inventory ───────────────────────────────────────────────────────────────────────────────────────────────────
# Each check returns {state, detail, expires_at?, estimated?, note?}. `blocks` is what stops when it fails: what makes
# the alert worth reading. `renew` is the safest step the provider allows: a helper tab running bin/marvin-renew
# (Gil types or approves the login himself; MARVIN never enters a credential), or the exact command and where.

def check_claude_setup_token(ctx: Ctx) -> dict:
    path = ctx.home / ".claude" / ".oauth-token"
    tok, why = read_token(path)
    if tok is None:
        return {"state": "failed", "detail": f"~/.claude/.oauth-token {why}"}
    made = _mtime(path)
    expires = made + timedelta(days=SETUP_TOKEN_LIFE_DAYS) if made else None
    try:
        status, _ = ctx.http("https://api.anthropic.com/v1/models?limit=1", {
            "Authorization": f"Bearer {tok}", "anthropic-version": "2023-06-01", "anthropic-beta": "oauth-2025-04-20"})
    except ProviderDown as e:
        return {"state": "unreachable", "detail": f"Anthropic didn't answer ({e})", "expires_at": expires, "estimated": True}
    if status in (401, 403):
        return {"state": "failed", "detail": "Anthropic rejected the setup-token (revoked or expired)", "expires_at": expires, "estimated": True}
    return {"state": "works", "detail": f"Anthropic accepts it; made {made:%Y-%m-%d}" if made else "Anthropic accepts it",
            "expires_at": expires, "estimated": True}


def check_claude_login(ctx: Ctx) -> dict:
    """The interactive login (Claude Code refreshes it itself). On Linux its refresh token's expiry is plain metadata in
    ~/.claude/.credentials.json; on a Mac it lives in the keychain, checked by presence only (reading it could prompt)."""
    if ctx.platform == "darwin":
        sec = "/usr/bin/security"
        try:
            r = ctx.run([sec, "find-generic-password", "-s", "Claude Code-credentials"], timeout=10)
        except Exception as e:  # noqa: BLE001
            return {"state": "unreachable", "detail": f"couldn't ask the keychain ({type(e).__name__})"}
        if r.returncode != 0:
            return {"state": "failed", "detail": "no Claude login in the keychain: open `claude` and type /login"}
        return {"state": "works", "detail": "signed in (keychain; Claude Code renews it while it's used)"}
    path = ctx.home / ".claude" / ".credentials.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {"state": "failed", "detail": "not signed in: no ~/.claude/.credentials.json"}
    except (OSError, ValueError):
        return {"state": "failed", "detail": "~/.claude/.credentials.json is damaged"}
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        return {"state": "failed", "detail": "not signed in to Claude (no claudeAiOauth entry)"}
    exp = parse_time(oauth.get("refreshTokenExpiresAt"))
    plan = str(oauth.get("subscriptionType") or "").strip()
    return {"state": "works", "detail": f"signed in{f' ({plan})' if plan else ''}", "expires_at": exp, "estimated": False}


def _github_live(ctx: Ctx, tok: str, who: str) -> dict:
    try:
        status, headers = ctx.http("https://api.github.com/user", {
            "Authorization": f"token {tok}", "Accept": "application/vnd.github+json", "User-Agent": "marvin-accounts"})
    except ProviderDown as e:
        return {"state": "unreachable", "detail": f"GitHub didn't answer ({e})"}
    if status in (401, 403):
        if status == 403 and headers.get("x-ratelimit-remaining") == "0":
            return {"state": "unreachable", "detail": "GitHub rate limit; no verdict"}
        return {"state": "failed", "detail": f"GitHub rejected {who} (revoked or expired)"}
    exp = parse_time(headers.get("github-authentication-token-expiration"))
    scopes = {s.strip() for s in (headers.get("x-oauth-scopes") or "").split(",") if s.strip()}
    note = ""
    if scopes and "repo" not in scopes:
        return {"state": "failed", "detail": f"{who} works but lacks the repo scope"}
    if scopes and "workflow" not in scopes:
        note = "; no workflow scope (a push touching .github/workflows fails)"
    return {"state": "works", "detail": f"GitHub accepts {who}{note}", "expires_at": exp, "estimated": False}


def check_github_token(ctx: Ctx) -> dict:
    tok, why = read_token(ctx.home / ".claude" / ".gh-token")
    if tok is None:
        return {"state": "failed", "detail": f"~/.claude/.gh-token {why}"}
    return _github_live(ctx, tok, "the shared token")


def check_marvin_bot(ctx: Ctx) -> dict:
    tok, why = read_token(ctx.home / ".claude" / ".marvin-bot-token")
    if tok is None:
        return {"state": "failed", "detail": f"~/.claude/.marvin-bot-token {why}"}
    return _github_live(ctx, tok, "the MARVIN-bot token")


def check_gh_login(ctx: Ctx) -> dict:
    """gh's own stored login, with MARVIN's shared token taken out of the environment so it can't hide a dead one."""
    gh = ctx.which("gh")
    if not gh:
        return {"state": "not_set_up", "detail": "gh isn't installed"}
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    env["MARVIN_GH_PRIORITY"] = "background"
    try:
        r = ctx.run([gh, "auth", "status", "--hostname", "github.com"], timeout=20, env=env)
    except Exception as e:  # noqa: BLE001
        return {"state": "unreachable", "detail": f"couldn't run gh ({type(e).__name__})"}
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0:
        return {"state": "works", "detail": "gh's own login works"}
    if "rate limit" in out.lower() or "error connecting" in out.lower():
        return {"state": "unreachable", "detail": "GitHub didn't answer gh"}
    if "not logged" in out.lower():
        return {"state": "not_set_up", "detail": "gh has no login of its own (MARVIN's jobs use the shared token)"}
    return {"state": "failed", "detail": "gh's own login is invalid (MARVIN's jobs use the shared token; gh typed at a terminal fails)"}


def check_anthropic_key(ctx: Ctx) -> dict:
    path = ctx.home / ".claude" / ".anthropic-api-key"
    tok, why = read_token(path)
    if tok is None:
        if why == "missing":
            return {"state": "not_set_up", "detail": "no API key (only needed for builds paid from the API credit)"}
        return {"state": "failed", "detail": f"~/.claude/.anthropic-api-key {why}"}
    try:
        status, _ = ctx.http("https://api.anthropic.com/v1/models?limit=1", {"x-api-key": tok, "anthropic-version": "2023-06-01"})
    except ProviderDown as e:
        return {"state": "unreachable", "detail": f"Anthropic didn't answer ({e})"}
    if status in (401, 403):
        return {"state": "failed", "detail": "Anthropic rejected the API key"}
    credit = _credit_state(ctx)
    if credit and credit.get("ok") is False:
        why = " ".join(str(credit.get("why") or "no reason recorded").split())[:120]
        return {"state": "failed", "detail": f"the key works but its credit isn't ready: {why}"}
    return {"state": "works", "detail": "Anthropic accepts the key" + ("; credit ready" if credit and credit.get("ok") else "")}


def _credit_state(ctx: Ctx) -> dict | None:
    try:
        d = json.loads((ctx.home / ".claude" / "dispatch" / "credit-state.json").read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def check_tailscale(ctx: Ctx) -> dict:
    try:
        import host_os
        ts = host_os.tailscale_bin() or ctx.which("tailscale")
    except Exception:  # noqa: BLE001
        ts = ctx.which("tailscale")
    if not ts:
        return {"state": "failed", "detail": "Tailscale isn't installed"}
    try:
        r = ctx.run([ts, "status", "--json"], timeout=10, env={**os.environ, "TERM": "dumb"})
        st = json.loads(r.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        return {"state": "unreachable", "detail": f"couldn't ask Tailscale ({type(e).__name__})"}
    backend = st.get("BackendState")
    if backend == "NeedsLogin":
        return {"state": "failed", "detail": "Tailscale needs a login: this machine is off the tailnet"}
    if backend != "Running":
        return {"state": "unreachable", "detail": f"Tailscale is {backend or 'not running'}"}
    exp = parse_time((st.get("Self") or {}).get("KeyExpiry"))
    detail = "on the tailnet" + ("" if exp else "; key expiry is off")
    return {"state": "works", "detail": detail, "expires_at": exp, "estimated": False}


def check_ngrok(ctx: Ctx) -> dict:
    ng = ctx.which("ngrok") or next((p for p in ("/opt/homebrew/bin/ngrok", "/usr/local/bin/ngrok") if Path(p).exists()), None)
    if not ng:
        return {"state": "not_set_up", "detail": "ngrok isn't installed here"}
    try:
        r = ctx.run([ng, "config", "check"], timeout=10)
    except Exception as e:  # noqa: BLE001
        return {"state": "unreachable", "detail": f"couldn't run ngrok ({type(e).__name__})"}
    if r.returncode != 0:
        return {"state": "failed", "detail": "ngrok's config (with its authtoken) is invalid"}
    return {"state": "works", "detail": "config valid (a config check, not a live login)"}


@dataclass(frozen=True)
class Account:
    id: str
    label: str
    check: Callable[[Ctx], dict]
    blocks: str
    renew: dict
    needed: Callable[[Ctx], bool] = lambda ctx: not ctx.pull_only
    optional: bool = False   # missing = not_set_up instead of failed
    alert: bool = True


def _tab(account: str, title: str) -> dict:
    return {"how": "tab", "title": title, "command": f"{RENEW} {account}"}


ACCOUNTS: tuple[Account, ...] = (
    Account("claude-setup-token", "Claude setup-token (builders)", check_claude_setup_token,
            "every ticket build and every headless `claude -p` job on this machine, including phone notifications",
            _tab("claude-setup-token", "Renew Claude setup-token")),
    Account("claude-login", "Claude login (interactive)", check_claude_login,
            "Claude sessions you start at this machine's keyboard",
            {"how": "command", "command": "claude, then type /login", "where": "a terminal on this machine"},
            needed=lambda ctx: True),
    Account("github-token", "GitHub (shared token)", check_github_token,
            "every MARVIN GitHub call here: the dashboard's PR list and boards, the ticket pipeline, merges",
            _tab("github", "Renew GitHub")),
    Account("gh-login", "GitHub (gh's own login)", check_gh_login,
            "gh typed at a terminal here (MARVIN's own jobs use the shared token)",
            _tab("github", "Renew GitHub"), optional=True, alert=False),
    Account("marvin-bot", "MARVIN-bot GitHub token", check_marvin_bot,
            "mac-mini-2012's ticket builds: their pushes and PRs (handed to each build VM)",
            {"how": "tab", "title": "Renew MARVIN-bot token", "command": f"{RENEW} marvin-bot-token",
             "steps": "sign in to github.com as MARVIN-bot-gil, Settings > Developer settings > Tokens (classic), "
                      "regenerate with the repo scope, then paste it into the tab"},
            needed=lambda ctx: ctx.primary),
    Account("anthropic-api-key", "Anthropic API key (credit)", check_anthropic_key,
            "extra ticket builds paid from the monthly API credit, beyond the plan's own slots",
            {"how": "tab", "title": "Renew Anthropic API key", "command": f"{RENEW} anthropic-api-key",
             "steps": "console.anthropic.com > API keys > Create key, then paste it into the tab"},
            optional=True),
    Account("tailscale", "Tailscale node key", check_tailscale,
            "everything between machines: dispatch, code sync, the box's mirror and observer feed, remote health",
            {"how": "command", "command": "sudo tailscale up --force-reauth (Linux) or the Tailscale menu > Log in (Mac); "
                                          "or turn off key expiry for this machine in the Tailscale admin console",
             "where": "this machine"},
            needed=lambda ctx: True),
    Account("ngrok", "ngrok tunnel (Marlin)", check_ngrok,
            "the Marlin tunnel's public address (not MARVIN core)",
            {"how": "command", "command": "ngrok config add-authtoken (token from dashboard.ngrok.com)", "where": "the Mac mini"},
            needed=lambda ctx: ctx.primary, optional=True, alert=False),
)
BY_ID = {a.id: a for a in ACCOUNTS}


def check_one(acc: Account, ctx: Ctx, machine: str) -> dict:
    row = {"id": acc.id, "machine": machine, "label": acc.label, "blocks": acc.blocks, "renew": acc.renew,
           "alert": acc.alert, "needed": acc.needed(ctx), "checked_at": _iso(ctx.now)}
    if not row["needed"]:
        return {**row, "state": "not_needed", "detail": "not needed on this machine", "expires_at": None, "estimated": False}
    try:
        got = acc.check(ctx) or {}
    except Exception as e:  # noqa: BLE001 -- one broken check never hides the others
        got = {"state": "unreachable", "detail": f"the check itself failed ({type(e).__name__})"}
    state = got.get("state") if got.get("state") in STATES else "unreachable"
    if acc.optional and state == "failed" and "missing" in str(got.get("detail", "")):
        state = "not_set_up"
    exp = got.get("expires_at")
    exp = exp if isinstance(exp, datetime) else parse_time(exp)
    state, detail = judge(state, str(got.get("detail") or ""), exp, bool(got.get("estimated")), ctx.now)
    return {**row, "state": state, "detail": detail, "expires_at": _iso(exp), "estimated": bool(got.get("estimated")),
            "verified_at": _iso(ctx.now) if state in ("works", "expiring", "failed") else None}


def check_here(ctx: Ctx | None = None, machine: str | None = None, only: str | None = None) -> list[dict]:
    ctx = ctx or _ctx_here()
    if machine is None:
        import machine_profile
        machine = machine_profile.registry_id()
    return [check_one(a, ctx, machine) for a in ACCOUNTS if only in (None, a.id)]


# ── the Mini's whole-network view ───────────────────────────────────────────────────────────────────────────────────

REMOTE_COMMAND = "~/.agents/venv/bin/python ~/.agents/lib/accounts.py check --json"
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


def rejudge_remote(rows: list[dict], now: datetime) -> list[dict]:
    """Rows from another machine, judged on this machine's clock. A skewed clock there is noted, not trusted."""
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get("id") not in BY_ID:
            continue
        r = dict(r)
        theirs = parse_time(r.get("checked_at"))
        if theirs and abs(theirs - now) > CLOCK_SKEW_NOTE:
            mins = int((theirs - now).total_seconds() // 60)
            r["detail"] = f"{r.get('detail', '')} (its clock is {abs(mins)} min {'ahead' if mins > 0 else 'behind'})"
        exp = parse_time(r.get("expires_at"))
        if r.get("state") in ("works", "expiring") and exp:
            base = "works" if r.get("state") == "expiring" else r["state"]
            detail = str(r.get("detail", "")).split("; runs out ")[0]
            r["state"], r["detail"] = judge(base, detail, exp, bool(r.get("estimated")), now)
        out.append(r)
    return out


def machine_unreachable(machine: str, why: str, now: datetime) -> list[dict]:
    return [{"id": a.id, "machine": machine, "label": a.label, "blocks": a.blocks, "renew": a.renew, "alert": a.alert,
             "needed": None, "state": "unreachable", "detail": f"couldn't check: {why}", "expires_at": None,
             "estimated": False, "checked_at": _iso(now), "verified_at": None} for a in ACCOUNTS]


def check_remote(host: str, machine: str, now: datetime, run=_run) -> list[dict]:
    try:
        r = run(["ssh", *SSH_OPTS, host, REMOTE_COMMAND], timeout=90)
    except Exception as e:  # noqa: BLE001
        return machine_unreachable(machine, f"{machine} didn't answer ({type(e).__name__})", now)
    if r.returncode != 0:
        return machine_unreachable(machine, f"{machine} didn't answer (ssh exit {r.returncode})", now)
    try:
        rows = json.loads(r.stdout).get("accounts", [])
    except (ValueError, AttributeError):
        return machine_unreachable(machine, f"{machine} sent an unreadable answer", now)
    return [{**x, "machine": machine} for x in rejudge_remote(rows, now)]


def sweep(ctx: Ctx | None = None, run=_run) -> dict:
    import machine_profile
    ctx = ctx or _ctx_here()
    me = machine_profile.registry_id()
    rows = check_here(ctx, me)
    for dev, info in machine_profile.remote_devices().items():
        host = (info or {}).get("tailscale_hostname")
        if host:
            rows += check_remote(host, dev, ctx.now, run=run)
    return {"generated_at": _iso(ctx.now), "by": me, "accounts": rows}


def write_status(status: dict, path: Path = STATUS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(status, f, indent=2)
    os.replace(tmp, path)


# ── alerts: once per state change ───────────────────────────────────────────────────────────────────────────────────

def _renew_text(renew: dict) -> str:
    if renew.get("how") == "tab":
        return f"Renew in Vitals > Accounts, or run {renew['command']}"
    return f"{renew.get('command')} ({renew.get('where', 'this machine')})"


def alert_message(row: dict) -> tuple[str, str]:
    where = row.get("machine", "?")
    if row["state"] == "works":
        return f"MARVIN: {row['label']} fixed", f"{row['label']} on {where} works again."
    title = f"MARVIN: {row['label']} {'runs out soon' if row['state'] == 'expiring' else 'stopped working'}"
    msg = f"{row['label']} on {where}: {row.get('detail', '')}. Blocks: {row.get('blocks', '')}. {_renew_text(row.get('renew') or {})}."
    return title, " ".join(msg.split())[:400]


def alerts_due(rows: list[dict], last: dict) -> tuple[list[dict], dict]:
    """(rows to alert about, the new remembered states). Pure. 'unreachable', 'not_set_up' and 'not_needed' never
    alert and never overwrite what was remembered, so a provider blip can't re-send an alert when it clears."""
    due, seen = [], dict(last)
    for r in rows:
        if not r.get("alert", True):
            continue
        key = f"{r.get('id')}@{r.get('machine')}"
        state, before = r.get("state"), last.get(key)
        if state in ALERTABLE:
            if before != state:
                due.append(r)
            seen[key] = state
        elif state == "works":
            if before in ALERTABLE:
                due.append(r)
            seen[key] = "works"
    return due, seen


def alert_changes(rows: list[dict], path: Path = ALERT_STATE_PATH, fire=None) -> list[dict]:
    try:
        last = json.loads(path.read_text())
        last = last if isinstance(last, dict) else {}
    except (OSError, ValueError):
        last = {}
    due, seen = alerts_due(rows, last)
    if fire is None:
        import mr_notification
        fire = lambda title, msg: mr_notification.notify_regression(title, msg)  # noqa: E731  desktop + phone + dashboard
    for r in due:
        try:
            fire(*alert_message(r))
        except Exception:  # noqa: BLE001 -- an alert failing never breaks the sweep
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(seen, indent=2, sort_keys=True))
    os.replace(tmp, path)
    return due


def sweep_and_alert() -> dict:
    """The health-check sweep's hook (its 15-minute schedule): only on a full node, which sees every machine."""
    ctx = _ctx_here()
    if ctx.pull_only:
        return {}
    status = sweep(ctx)
    write_status(status)
    alert_changes(status["accounts"])
    return status


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="accounts.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="this machine's accounts")
    c.add_argument("--json", action="store_true")
    c.add_argument("--only", choices=sorted(BY_ID))
    s = sub.add_parser("sweep", help="every machine, written and alerted (what the health sweep runs)")
    s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        rows = check_here(only=a.only)
        out = {"checked_at": _iso(datetime.now(timezone.utc)), "accounts": rows}
    else:
        out = sweep_and_alert()
        rows = out.get("accounts", [])
    if getattr(a, "json", False):
        print(json.dumps(out, indent=2))
    else:
        for r in rows:
            exp = f"  (expires {r['expires_at'][:10]}{' est.' if r.get('estimated') else ''})" if r.get("expires_at") else ""
            print(f"{r['state']:<12} {r['machine']:<16} {r['label']:<32} {r['detail']}{exp}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
