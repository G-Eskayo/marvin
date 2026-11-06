#!/usr/bin/env python3
"""site_deploy.py — the site's ship step and its alarm (marvin#1122, ADR 0080 I4).

For a project whose site publishes through GitHub Actions (site.yml's deploy job), "shipped" means GitHub's Pages
deployment for that merge succeeded. Then:

  report   (site.yml's `report` job, after every publish run on main)
           failed publish (the build or the deploy failed)  -> main_red's path with the SITE kind: one ticket,
             labelled site-deploy-failed (never main-red or p0, so it never holds a merge); a re-run of the same
             commit adds nothing; a new failing commit adds one line
           published -> close that ticket, then the ship step: each ticket closed by a merge this publish carried
             gets one comment with the live link (marked, so it is said once)
           cancelled (a newer merge replaced the waiting publish) -> nothing: the newer run reports for both
  health   the Health card `site:published`: is main's latest site change live? Reads the deployments, so a publish
           that never ran (no run, no ticket) still shows. Running is yellow; a fresh merge gets GRACE_S before red;
           what couldn't be read is unknown, never red.

Merges that touched only the engine are never told "live on the site": the commits come from `git log -- <paths>`, the
paths site.yml itself triggers on.

    site_deploy.py report --sha <sha> --run <url> --results '<toJSON(needs)>' [--page-url <url>]
    site_deploy.py health
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main_red  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "site.yml"
SITE_CONFIG = ROOT / "site" / "site.config.json"
ENVIRONMENT = "github-pages"
GRACE_S = 30 * 60            # a merge's publish takes a few minutes; red only after this long with nothing live
DEPLOYMENTS_READ = 10        # the newest deployments looked at (each costs one more call for its status)
MAX_COMMITS = 50             # one publish carries at most this many merges' tickets
MARKER = "<!-- marvin:shipped-site -->"
LABEL = "site-deploy-failed"
_LIVE, _RUNNING = {"success"}, {"in_progress", "queued", "pending", "waiting"}


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "").lower()


def _on_domain(url: str | None) -> bool:
    """A publish is the site's only at the configured domain (a legacy main:/docs build is at github.io)."""
    want = configured_url()
    return not url or not want or _host(url) == _host(want)


def _job_names(results: dict) -> dict:
    """site.yml hands over job ids (build); people read job names (Build site)."""
    try:
        import yaml
        jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    except Exception:  # noqa: BLE001 -- the ids are still a fine name
        return results
    return {(jobs.get(k) or {}).get("name", k): v for k, v in results.items()}


def _body(failed: list[str], sha: str, run_url: str) -> str:
    return f"""The site didn't publish: **{', '.join(failed)}** failed on `{sha[:7]}` ([the run]({run_url})). Opened by
site.yml's `report` job (lib/site_deploy.py, #1122). Merges are not held for this; the live site stays at its last
good publish until a later one succeeds, which closes this ticket.

## What to check
1. Open the run above: did the build's checks fail, or the deploy?
2. A deploy that fails at once often means the repo's Pages settings: the source must be "GitHub Actions" and the
   custom domain set (Settings > Pages). That's the owner's to change, not code.
3. Otherwise fix the cause test-first and merge; the next publish closes this.

## Acceptance criteria
- [ ] A later publish on main succeeds (this ticket then closes itself)
"""


SITE = main_red.Kind(
    label=LABEL, labels=["bug", "priority:p1", "needs-triage", LABEL],
    label_help="The site didn't publish to GitHub Pages; merges are not held (#1122)",
    title=lambda sha: f"The site didn't publish at {sha[:7]}",
    body=_body,
    closed=lambda sha, run: f"Published again at `{sha[:7]}` ([the run]({run})). Closing.",
    still=lambda sha, failed, run: f"Still not published at `{sha[:7]}`: {', '.join(failed)} failed ([the run]({run})).",
    once_per_commit=True)


def site_paths() -> list[str]:
    import yaml
    wf = yaml.safe_load(WORKFLOW.read_text())
    on = wf.get("on", wf.get(True)) or {}
    return list((on.get("push") or {}).get("paths") or [])


def configured_url() -> str:
    try:
        return json.loads(SITE_CONFIG.read_text()).get("url") or ""
    except (OSError, ValueError):
        return ""


class Git:
    """main's history, read from this checkout (CI checks out with full history)."""

    def __init__(self, root: Path = ROOT, ref: str | None = None):
        self.root, self.ref = root, ref or os.environ.get("SITE_DEPLOY_REF", "origin/main")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, timeout=60)

    def ancestor(self, a: str, b: str) -> bool | None:
        r = self._run("merge-base", "--is-ancestor", a, b)
        return {0: True, 1: False}.get(r.returncode)   # 128: a commit this checkout doesn't have

    def site_commits(self, a: str, b: str) -> list[str]:
        r = self._run("log", "--format=%H", f"-{MAX_COMMITS}", f"{a}..{b}", "--", *site_paths())
        return list(reversed(r.stdout.split())) if r.returncode == 0 else []

    def last_site_change(self):
        r = self._run("log", "-1", "--format=%H %ct", self.ref, "--", *site_paths())
        if r.returncode != 0 or not r.stdout.strip():
            return None, None
        sha, ts = r.stdout.split()
        return sha, datetime.fromtimestamp(int(ts), timezone.utc)


def _deployments(repo: str, gh):
    """Newest first: (sha, state, live url). Each status is fetched only when asked for (a generator)."""
    ds = json.loads(gh(["api", f"repos/{repo}/deployments?environment={ENVIRONMENT}&per_page={DEPLOYMENTS_READ}"]) or "[]")
    for d in ds:
        st = json.loads(gh(["api", f"repos/{repo}/deployments/{d['id']}/statuses?per_page=1"]) or "[]")
        yield d["sha"], (st[0].get("state") if st else "pending"), (st[0].get("environment_url") if st else None)


def _tickets_closed_by(commit: str, repo: str, gh) -> list[int]:
    prs = json.loads(gh(["api", f"repos/{repo}/commits/{commit}/pulls"]) or "[]")
    out: list[int] = []
    for p in prs:
        if not p.get("merged_at"):
            continue
        d = json.loads(gh(["pr", "view", str(p["number"]), "--repo", repo, "--json", "closingIssuesReferences"]) or "{}")
        out += [r["number"] for r in d.get("closingIssuesReferences") or []]
    return out


def ship(sha: str, page_url: str, run_url: str, repo: str, gh=main_red._gh, git=None) -> dict:
    """The ship step: every ticket closed by a site-changing merge this publish carried hears the live link once."""
    git = git or Git()
    url = page_url or configured_url()
    errors: list[str] = []
    prev = None
    try:
        for d_sha, state, url in _deployments(repo, gh):
            if d_sha != sha and state in _LIVE and _on_domain(url):
                prev = d_sha
                break
    except (subprocess.CalledProcessError, ValueError, KeyError) as e:
        errors.append(f"deployments: {e}")
    commits = git.site_commits(prev, sha) if prev and git.ancestor(prev, sha) else []
    if sha not in commits:
        commits.append(sha)
    tickets: list[int] = []
    for c in commits:
        try:
            tickets += [t for t in _tickets_closed_by(c, repo, gh) if t not in tickets]
        except (subprocess.CalledProcessError, ValueError, KeyError) as e:
            errors.append(f"{c[:7]}: {e}")
    commented: list[int] = []
    for t in tickets:
        try:
            d = json.loads(gh(["issue", "view", str(t), "--repo", repo, "--json", "comments"]) or "{}")
            if any(MARKER in ((c or {}).get("body") or "") for c in d.get("comments") or []):
                continue
            gh(["issue", "comment", str(t), "--repo", repo, "--body",
                f"Live: {url} (published from `{sha[:7]}`, [the run]({run_url})). {MARKER}"])
            commented.append(t)
        except (subprocess.CalledProcessError, ValueError) as e:
            errors.append(f"#{t}: {e}")
    return {"commits": commits, "tickets": tickets, "commented": commented, "errors": errors}


def report(results: dict, sha: str, run_url: str, repo: str, page_url: str = "", gh=main_red._gh, git=None) -> dict:
    out = main_red.report(_job_names(results), sha, run_url, repo, gh=gh, kind=SITE)
    if out["state"] == "green":
        out["shipped"] = ship(sha, page_url, run_url, repo, gh=gh, git=git)
    return out


def health(repo: str, gh=main_red._gh, git=None, now: datetime | None = None) -> dict:
    """{severity, detail}: is main's latest site change live?"""
    git = git or Git()
    now = now or datetime.now(timezone.utc)
    site, when = git.last_site_change()
    if not site:
        return {"severity": "green", "detail": "the site hasn't changed on main"}
    live_from = None
    try:
        for d_sha, state, url in _deployments(repo, gh):
            covers = d_sha == site or git.ancestor(site, d_sha)
            if not covers:
                if state in _LIVE and live_from is None:
                    live_from = d_sha
                continue
            if state in _LIVE:
                want = configured_url()
                if not _on_domain(url):
                    return {"severity": "yellow", "detail": f"`{d_sha[:7]}` published to {url}, not to {want} yet "
                                                            "(the repo's Pages source or custom domain isn't set)"}
                return {"severity": "green", "detail": f"live at {url or want} from `{d_sha[:7]}`"}
            if state in _RUNNING:
                return {"severity": "yellow", "detail": f"publishing `{site[:7]}` now"}
            return {"severity": "red", "detail": f"the publish of `{site[:7]}` failed ({state}); the live site is "
                                                 f"{'from `' + live_from[:7] + '`' if live_from else 'not up'}"}
    except (subprocess.CalledProcessError, ValueError, KeyError) as e:
        return {"severity": "unknown", "detail": f"couldn't read the Pages deployments: {str(e)[:100]}"}
    older = f"the live site is from `{live_from[:7]}`" if live_from else "nothing has published yet"
    if when and (now - when).total_seconds() < GRACE_S:
        return {"severity": "yellow", "detail": f"`{site[:7]}` merged {int((now - when).total_seconds() // 60)} min ago, "
                                                f"waiting for its publish; {older}"}
    return {"severity": "red", "detail": f"main's latest site change `{site[:7]}` never published; {older}"}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="site_deploy.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("--sha", required=True)
    r.add_argument("--run", required=True)
    r.add_argument("--results", required=True)
    r.add_argument("--page-url", default="")
    r.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    h = sub.add_parser("health")
    h.add_argument("--repo", default="")
    a = ap.parse_args(argv)
    if a.cmd == "health":
        repo = a.repo or json.loads(SITE_CONFIG.read_text()).get("repo", "")
        print(json.dumps(health(repo)))
        return 0
    try:
        results = json.loads(a.results)
    except ValueError as e:
        sys.exit(f"site_deploy: --results is not JSON ({e})")
    if not isinstance(results, dict) or not a.repo:
        sys.exit("site_deploy: --results must be an object, and --repo (or $GITHUB_REPOSITORY) is needed")
    print(json.dumps(report(results, a.sha, a.run, a.repo, a.page_url)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
